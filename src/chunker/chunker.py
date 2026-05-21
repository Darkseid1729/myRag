"""Overlap-aware code chunker.

This module provides chunking on top of the parsed AST chunks from the
tree-sitter parser.  When a parsed chunk exceeds `max_tokens`, it is
split using a sliding window with `overlap_tokens` overlap so that
context is preserved across boundaries.

Design decisions:
- Split on newlines only (never mid-token) to keep code valid.
- Overlap preserves the last N tokens of the previous window in the
  next window so the embedding model has context.
- Min-token filter prevents storing near-empty shards.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.config import get_config
from src.parser.tree_sitter_parser import ParsedChunk
from src.utils import count_tokens_approx, get_logger

logger = get_logger(__name__)


@dataclass
class Chunk:
    """A fully processed, storage-ready code chunk."""

    chunk_type: str
    name: str | None
    text: str
    start_line: int
    end_line: int
    symbols: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    exports: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def token_count(self) -> int:
        return count_tokens_approx(self.text)


def _split_with_overlap(
    lines: list[str],
    start_line: int,
    max_tokens: int,
    overlap_tokens: int,
    min_tokens: int,
) -> list[tuple[list[str], int]]:
    """Split a list of lines into windows with token overlap.

    Returns list of (window_lines, window_start_line_1indexed).
    """
    windows: list[tuple[list[str], int]] = []
    i = 0
    n = len(lines)
    while i < n:
        window: list[str] = []
        tokens = 0
        j = i
        while j < n:
            line = lines[j]
            line_tokens = count_tokens_approx(line) + 1  # +1 for newline
            if tokens + line_tokens > max_tokens and window:
                break
            window.append(line)
            tokens += line_tokens
            j += 1

        if tokens >= min_tokens:
            windows.append((window, start_line + i))

        if j >= n:
            break

        # Advance i but keep overlap_tokens worth of lines
        overlap_lines: list[str] = []
        overlap_tok = 0
        for line in reversed(window):
            lt = count_tokens_approx(line) + 1
            if overlap_tok + lt > overlap_tokens:
                break
            overlap_lines.insert(0, line)
            overlap_tok += lt

        # Move i forward past non-overlapping lines
        new_i = j - len(overlap_lines)
        if new_i <= i:
            # Guard against infinite loops: always advance at least 1 line
            new_i = i + max(1, len(window) // 2)
        i = new_i

    return windows


def chunk_parsed(parsed: ParsedChunk) -> list[Chunk]:
    """Convert a ParsedChunk into one or more storage-ready Chunks.

    If the parsed chunk is within the token budget it is returned as-is.
    If it exceeds the budget it is split with overlap.
    """
    cfg = get_config()["indexer"]
    max_tokens: int = cfg["max_chunk_tokens"]
    min_tokens: int = cfg["min_chunk_tokens"]
    overlap_tokens: int = cfg["overlap_tokens"]

    token_count = count_tokens_approx(parsed.text)

    # Fast path — chunk fits without splitting
    if token_count <= max_tokens:
        if token_count < min_tokens and parsed.chunk_type not in (
            "COMPONENT", "HOOK", "IMPORT_BLOCK"
        ):
            return []
        return [
            Chunk(
                chunk_type=parsed.chunk_type,
                name=parsed.name,
                text=parsed.text,
                start_line=parsed.start_line,
                end_line=parsed.end_line,
                symbols=parsed.symbols,
                imports=parsed.imports,
                exports=parsed.exports,
                metadata=parsed.metadata,
            )
        ]

    # Split path
    lines = parsed.text.splitlines()
    windows = _split_with_overlap(
        lines, parsed.start_line, max_tokens, overlap_tokens, min_tokens
    )
    result: list[Chunk] = []
    for idx, (win_lines, win_start) in enumerate(windows):
        text = "\n".join(win_lines)
        win_end = win_start + len(win_lines) - 1
        # Only first shard keeps the original name to avoid confusion
        name = parsed.name if idx == 0 else f"{parsed.name}[{idx}]" if parsed.name else None
        # ALL shards inherit symbols so every shard can be found by symbol lookup.
        # Shards beyond the first get the parent symbols with a shard suffix stripped.
        shard_symbols = parsed.symbols  # always propagate full symbol set
        result.append(
            Chunk(
                chunk_type=parsed.chunk_type,
                name=name,
                text=text,
                start_line=win_start,
                end_line=win_end,
                symbols=shard_symbols,
                imports=parsed.imports,
                exports=parsed.exports,
                metadata={**parsed.metadata, "shard_index": idx, "shard_total": len(windows)},
            )
        )
    return result


def chunk_all(parsed_chunks: list[ParsedChunk]) -> list[Chunk]:
    """Apply chunking to a full list of parsed chunks from a single file."""
    result: list[Chunk] = []
    for pc in parsed_chunks:
        result.extend(chunk_parsed(pc))
    return result
