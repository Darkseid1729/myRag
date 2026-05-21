"""Tests for the context builder."""

import pytest
from src.context.builder import build_context


class _FakeChunk:
    def __init__(self, file_path, start_line, end_line, chunk_type, name, final_score, text):
        self.file_path = file_path
        self.start_line = start_line
        self.end_line = end_line
        self.chunk_type = chunk_type
        self.name = name
        self.final_score = final_score
        self.text = text


def _make_chunks(n=3):
    return [
        _FakeChunk(
            file_path=f"src/components/Comp{i}.tsx",
            start_line=1,
            end_line=20,
            chunk_type="COMPONENT",
            name=f"Comp{i}",
            final_score=0.9 - i * 0.1,
            text=f"export const Comp{i} = () => <div>Component {i}</div>;",
        )
        for i in range(n)
    ]


class TestBuildContext:
    def test_includes_query(self):
        chunks = _make_chunks(2)
        result = build_context("Where is Comp0 defined?", chunks)
        assert "Where is Comp0 defined?" in result

    def test_includes_file_paths(self):
        chunks = _make_chunks(2)
        result = build_context("test query", chunks)
        assert "src/components/Comp0.tsx" in result

    def test_includes_code(self):
        chunks = _make_chunks(1)
        result = build_context("test", chunks)
        assert "export const Comp0" in result

    def test_token_budget_respected(self):
        # Create many large chunks
        big_chunks = [
            _FakeChunk("file.tsx", 1, 100, "FUNCTION", "big", 0.9, "x " * 2000)
            for _ in range(10)
        ]
        result = build_context("test", big_chunks, max_tokens=200)
        # Result should not be enormous despite huge chunks
        from src.utils import count_tokens_approx
        assert count_tokens_approx(result) <= 250  # some tolerance

    def test_includes_instruction_footer(self):
        chunks = _make_chunks(1)
        result = build_context("test", chunks)
        assert "Answer the user" in result

    def test_empty_chunks(self):
        result = build_context("test query", [])
        assert "test query" in result
        assert "Evidence" in result

    def test_code_fence_present(self):
        chunks = _make_chunks(1)
        result = build_context("test", chunks)
        # Should have code fence markers
        assert "```" in result

    def test_score_present(self):
        chunks = _make_chunks(1)
        result = build_context("test", chunks)
        assert "0.9" in result  # score value

    def test_zero_budget_returns_minimal(self):
        chunks = _make_chunks(3)
        result = build_context("test", chunks, max_tokens=1)
        # Should not crash; returns at least the query
        assert isinstance(result, str)
