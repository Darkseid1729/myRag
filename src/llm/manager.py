"""LLM manager: routes generation calls to configured providers."""

from __future__ import annotations

from typing import Iterable

from src.config import get_config
from src.llm.providers import ollama_generate, llamacpp_generate, openai_generate


def generate(prompt: str, stream: bool | None = None) -> str | Iterable[str]:
    cfg = get_config()
    provider = cfg["llm"]["provider"].lower()
    do_stream = cfg["llm"].get("stream", True) if stream is None else stream

    if provider == "none":
        raise RuntimeError("LLM provider is set to 'none'")

    if provider == "ollama":
        return ollama_generate(
            cfg["llm"]["ollama_base_url"],
            cfg["llm"]["ollama_model"],
            prompt,
            do_stream,
        )

    if provider == "llamacpp":
        return llamacpp_generate(cfg["llm"]["llamacpp_base_url"], prompt, do_stream)

    if provider == "openai":
        return openai_generate(cfg["llm"]["openai_model"], prompt, do_stream)

    raise RuntimeError(f"Unknown LLM provider: {provider}")
