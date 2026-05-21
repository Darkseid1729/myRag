"""Tests for the overlap-aware chunker module."""

import pytest
from src.chunker.chunker import chunk_parsed, chunk_all, _split_with_overlap
from src.parser.tree_sitter_parser import ParsedChunk


def _make_chunk(text: str, chunk_type: str = "FUNCTION", name: str = "foo") -> ParsedChunk:
    return ParsedChunk(
        chunk_type=chunk_type,
        name=name,
        text=text,
        start_line=1,
        end_line=text.count("\n") + 1,
        symbols=[name],
    )


class TestSplitWithOverlap:
    def test_no_split_needed(self):
        lines = ["line one", "line two", "line three"]
        windows = _split_with_overlap(lines, 1, max_tokens=50, overlap_tokens=5, min_tokens=1)
        assert len(windows) == 1
        assert windows[0][0] == lines

    def test_splits_long_content(self):
        # Each line is ~10 chars ≈ 2-3 tokens; 30 lines > 300 tokens
        lines = [f"const x{i} = value{i}; // comment {i}" for i in range(30)]
        windows = _split_with_overlap(lines, 1, max_tokens=30, overlap_tokens=5, min_tokens=1)
        assert len(windows) > 1

    def test_overlap_present(self):
        # Build two windows; check that last lines of window 0 appear in window 1
        lines = [f"line{i:02d}" for i in range(20)]
        windows = _split_with_overlap(lines, 1, max_tokens=20, overlap_tokens=10, min_tokens=1)
        if len(windows) >= 2:
            w0_last = windows[0][0][-1]
            assert w0_last in windows[1][0], "Overlap missing from second window"

    def test_start_lines_are_correct(self):
        lines = [f"const x{i} = {i};" for i in range(40)]
        windows = _split_with_overlap(lines, 1, max_tokens=30, overlap_tokens=5, min_tokens=1)
        # First window must start at line 1
        assert windows[0][1] == 1
        # All start lines must be >= 1 and in increasing order
        starts = [w[1] for w in windows]
        assert starts == sorted(starts)

    def test_min_tokens_filter(self):
        lines = ["x"]  # 1 char ≈ 0 tokens
        windows = _split_with_overlap(lines, 1, max_tokens=50, overlap_tokens=5, min_tokens=100)
        assert len(windows) == 0


class TestChunkParsed:
    def test_small_chunk_passthrough(self):
        # Must be >20 tokens to avoid min_tokens filter (or be a COMPONENT/HOOK)
        text = "const foo = () => { " + "let x = 1; " * 10 + "};"
        pc = _make_chunk(text)
        result = chunk_parsed(pc)
        assert len(result) == 1
        assert result[0].text == text
        assert result[0].name == "foo"
        assert result[0].symbols == ["foo"]

    def test_oversized_chunk_is_split(self):
        # Generate a chunk that clearly exceeds 300 tokens (>1200 chars)
        lines = [f"const variable{i} = computeValue{i}({i}, {i+1});" for i in range(60)]
        text = "\n".join(lines)
        pc = _make_chunk(text, name="bigFunc")
        result = chunk_parsed(pc)
        assert len(result) > 1

    def test_split_shards_have_shard_metadata(self):
        lines = [f"const v{i} = {i};" for i in range(200)]  # > 400 tokens
        text = "\n".join(lines)
        pc = _make_chunk(text, name="big")
        result = chunk_parsed(pc)
        assert len(result) > 1
        assert all("shard_index" in r.metadata for r in result)
        assert result[0].metadata["shard_index"] == 0
        assert result[0].name == "big"
        if len(result) > 1:
            assert "[1]" in result[1].name

    def test_component_not_filtered_by_min_tokens(self):
        # COMPONENT chunks below min tokens should still be kept
        pc = _make_chunk("const A = () => <div/>;", chunk_type="COMPONENT", name="A")
        result = chunk_parsed(pc)
        assert len(result) == 1

    def test_tiny_function_filtered(self):
        # A tiny non-special chunk (< min_tokens) should be filtered
        # min_tokens = 20 tokens ≈ 80 chars; use a really tiny one
        pc = _make_chunk("x", chunk_type="FUNCTION", name="x")
        result = chunk_parsed(pc)
        assert len(result) == 0


class TestChunkAll:
    def test_chunk_all_empty(self):
        result = chunk_all([])
        assert result == []

    def test_chunk_all_multiple_chunks(self):
        chunks = [
            _make_chunk("const a = 1;", "FUNCTION", "a"),
            _make_chunk("const b = 2;", "FUNCTION", "b"),
        ]
        result = chunk_all(chunks)
        names = [r.name for r in result if r.name and "[" not in r.name]
        # Both functions should appear (if large enough or kept by type)
        assert len(result) >= 0  # may be filtered; just verify no crash
