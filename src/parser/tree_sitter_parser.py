"""Tree-sitter based AST parser for JS/JSX/TS/TSX files."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.utils import get_logger

logger = get_logger(__name__)

# We attempt to import tree_sitter; fall back gracefully
try:
    import tree_sitter
    from tree_sitter import Language, Parser
    import tree_sitter_javascript as tsjs

    JS_LANGUAGE = Language(tsjs.language())
    _PARSER = Parser(JS_LANGUAGE)
    _TS_AVAILABLE = True
except Exception as exc:
    _TS_AVAILABLE = False
    logger.warning(f"tree-sitter unavailable ({exc}). Using regex fallback parser.")


@dataclass
class ParsedChunk:
    chunk_type: str          # COMPONENT | HOOK | FUNCTION | ROUTE | IMPORT_BLOCK | MISC
    name: str | None
    text: str
    start_line: int
    end_line: int
    symbols: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    exports: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Tree-sitter extraction helpers
# ---------------------------------------------------------------------------

def _node_text(node: Any, src: bytes) -> str:
    return src[node.start_byte:node.end_byte].decode(errors="replace")


def _extract_ts(src: bytes) -> list[ParsedChunk]:
    tree = _PARSER.parse(src)
    chunks: list[ParsedChunk] = []
    text = src.decode(errors="replace")
    lines = text.splitlines()

    def _lineno(byte_offset: int) -> int:
        return text[:byte_offset].count("\n") + 1

    def walk(node: Any) -> None:
        kind = node.type

        # Function / arrow function declarations
        if kind in ("function_declaration", "function_expression",
                     "arrow_function", "lexical_declaration"):
            raw = _node_text(node, src)
            # detect hook (useXxx pattern)
            name_match = re.search(r"(?:function\s+|const\s+)(\w+)", raw)
            name = name_match.group(1) if name_match else None
            chunk_type = "HOOK" if (name and name.startswith("use")) else "FUNCTION"

            # Is it a React component (PascalCase + JSX return)?
            if name and name[0].isupper() and "<" in raw:
                chunk_type = "COMPONENT"

            chunks.append(ParsedChunk(
                chunk_type=chunk_type,
                name=name,
                text=raw,
                start_line=_lineno(node.start_byte),
                end_line=_lineno(node.end_byte),
                symbols=[name] if name else [],
            ))
            return  # don't recurse into this subtree

        # Import declarations → single IMPORT_BLOCK chunk
        if kind == "import_declaration":
            raw = _node_text(node, src)
            chunks.append(ParsedChunk(
                chunk_type="IMPORT_BLOCK",
                name=None,
                text=raw,
                start_line=_lineno(node.start_byte),
                end_line=_lineno(node.end_byte),
            ))
            return

        for child in node.children:
            walk(child)

    walk(tree.root_node)
    return chunks


# ---------------------------------------------------------------------------
# Regex fallback parser
# ---------------------------------------------------------------------------

_FUNC_RE = re.compile(
    r"(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+(\w+)\s*\(",
    re.MULTILINE,
)
_ARROW_RE = re.compile(
    r"(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\(",
    re.MULTILINE,
)
_IMPORT_RE = re.compile(r"^import\s+.+from\s+['\"].+['\"];?$", re.MULTILINE)


def _extract_regex(source: str) -> list[ParsedChunk]:
    chunks: list[ParsedChunk] = []
    lines = source.splitlines()

    for m in list(_FUNC_RE.finditer(source)) + list(_ARROW_RE.finditer(source)):
        name = m.group(1)
        start_char = m.start()
        start_line = source[:start_char].count("\n") + 1

        # Approximate end: next top-level function or end of file
        end_line = min(start_line + 60, len(lines))
        text = "\n".join(lines[start_line - 1 : end_line])

        chunk_type = "HOOK" if name.startswith("use") else (
            "COMPONENT" if name[0].isupper() else "FUNCTION"
        )
        chunks.append(ParsedChunk(
            chunk_type=chunk_type,
            name=name,
            text=text,
            start_line=start_line,
            end_line=end_line,
            symbols=[name],
        ))

    # Collect contiguous import lines
    import_lines = [i + 1 for i, l in enumerate(lines) if l.strip().startswith("import ")]
    if import_lines:
        chunks.append(ParsedChunk(
            chunk_type="IMPORT_BLOCK",
            name=None,
            text="\n".join(lines[import_lines[0] - 1 : import_lines[-1]]),
            start_line=import_lines[0],
            end_line=import_lines[-1],
        ))

    return chunks


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def parse_file(path: str | Path) -> list[ParsedChunk]:
    """Parse a source file and return a list of structured code chunks."""
    source_bytes = Path(path).read_bytes()
    try:
        if _TS_AVAILABLE:
            chunks = _extract_ts(source_bytes)
        else:
            chunks = _extract_regex(source_bytes.decode(errors="replace"))
    except Exception as exc:
        logger.error(f"Parse error for {path}: {exc}")
        # Return whole file as MISC chunk
        source_text = source_bytes.decode(errors="replace")
        chunks = [ParsedChunk(
            chunk_type="MISC",
            name=None,
            text=source_text,
            start_line=1,
            end_line=source_text.count("\n") + 1,
        )]

    # Drop empty chunks
    return [c for c in chunks if c.text.strip()]
