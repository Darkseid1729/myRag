"""Plugin loader and dispatcher."""

from __future__ import annotations

import importlib
from typing import Iterable

from src.config import get_config
from src.utils import get_logger

logger = get_logger(__name__)


class PluginManager:
    def __init__(self) -> None:
        cfg = get_config()
        self._plugin_paths = cfg.get("plugins", {}).get("enabled", [])
        self._plugins = self._load_plugins(self._plugin_paths)

    def _load_plugins(self, paths: list[str]) -> list[object]:
        plugins: list[object] = []
        for path in paths:
            try:
                mod = importlib.import_module(path)
                plugin = getattr(mod, "plugin", None) or mod
                plugins.append(plugin)
                logger.info(f"Loaded plugin: {path}")
            except Exception as exc:
                logger.warning(f"Failed to load plugin {path}: {exc}")
        return plugins

    def on_chunk(self, chunk: object) -> None:
        for p in self._plugins:
            hook = getattr(p, "on_chunk", None)
            if callable(hook):
                hook(chunk)

    def on_results(self, query: str, results: Iterable[object]) -> None:
        for p in self._plugins:
            hook = getattr(p, "on_results", None)
            if callable(hook):
                hook(query, results)

    def on_prompt(self, prompt: str) -> str:
        out = prompt
        for p in self._plugins:
            hook = getattr(p, "on_prompt", None)
            if callable(hook):
                out = hook(out)
        return out
