"""Example TypeScript plugin (no-op, placeholder for future TS-specific hooks)."""

from __future__ import annotations

name = "typescript_plugin"


def on_chunk(chunk: object) -> None:
    # Placeholder hook: no-op to demonstrate plugin wiring.
    return None
