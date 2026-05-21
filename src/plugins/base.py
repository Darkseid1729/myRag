"""Plugin hook definitions."""

from __future__ import annotations

from typing import Protocol, Iterable


class Plugin(Protocol):
    name: str

    def on_chunk(self, chunk: object) -> None:
        ...

    def on_results(self, query: str, results: Iterable[object]) -> None:
        ...

    def on_prompt(self, prompt: str) -> str:
        ...
