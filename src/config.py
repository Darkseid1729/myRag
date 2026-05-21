"""Centralised application configuration loaded from config/default.yaml + .env.

Environment variables take precedence over YAML values.
All keys are documented in .env.example.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

load_dotenv()

_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _ROOT / "config" / "default.yaml"


def _env_int(key: str, default: int) -> int:
    val = os.getenv(key)
    if val is None:
        return default
    try:
        return int(val)
    except ValueError:
        return default


def _env_bool(key: str, default: bool) -> bool:
    val = os.getenv(key)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes")


@lru_cache(maxsize=1)
def get_config() -> dict:
    """Load and return the merged configuration (YAML + env vars).

    This is cached after the first call. Call ``get_config.cache_clear()``
    in tests to reset the cache.
    """
    if not _CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"Configuration file not found: {_CONFIG_PATH}. "
            "Make sure you have config/default.yaml in the project root."
        )

    with open(_CONFIG_PATH, encoding="utf-8") as f:
        cfg: dict[str, Any] = yaml.safe_load(f) or {}

    # ------------------------------------------------------------------ app
    cfg.setdefault("app", {})
    cfg["app"]["host"] = os.getenv("APP_HOST", cfg["app"].get("host", "127.0.0.1"))
    cfg["app"]["port"] = _env_int("APP_PORT", cfg["app"].get("port", 8000))

    # ------------------------------------------------------------------ llm
    cfg.setdefault("llm", {})
    cfg["llm"]["provider"] = os.getenv("LLM_PROVIDER", cfg["llm"].get("provider", "none"))
    cfg["llm"]["ollama_base_url"] = os.getenv(
        "OLLAMA_BASE_URL", cfg["llm"].get("ollama_base_url", "http://localhost:11434")
    )
    cfg["llm"]["ollama_model"] = os.getenv(
        "OLLAMA_MODEL", cfg["llm"].get("ollama_model", "llama3")
    )
    cfg["llm"]["llamacpp_base_url"] = os.getenv(
        "LLAMACPP_BASE_URL", cfg["llm"].get("llamacpp_base_url", "http://localhost:8080")
    )
    cfg["llm"]["openai_model"] = os.getenv(
        "OPENAI_MODEL", cfg["llm"].get("openai_model", "gpt-4o-mini")
    )
    stream_env = os.getenv("LLM_STREAM")
    if stream_env is not None:
        cfg["llm"]["stream"] = stream_env.lower() == "true"
    cfg["llm"].setdefault("stream", True)
    cfg["llm"].setdefault("max_context_tokens", 4096)
    cfg["llm"].setdefault("temperature", 0.2)

    # ------------------------------------------------------------------ embedding
    cfg.setdefault("embedding", {})
    cfg["embedding"]["model"] = os.getenv(
        "EMBEDDING_MODEL", cfg["embedding"].get("model", "all-MiniLM-L6-v2")
    )
    cfg["embedding"].setdefault("dims", 384)
    cfg["embedding"].setdefault("quantize", True)
    cfg["embedding"].setdefault("batch_size", 16)

    # ------------------------------------------------------------------ memory
    cfg.setdefault("memory", {})
    cfg["memory"]["sqlite_page_cache_kb"] = _env_int(
        "SQLITE_PAGE_CACHE_KB", cfg["memory"].get("sqlite_page_cache_kb", 4096)
    )
    cfg["memory"]["vector_lru_cache_kb"] = _env_int(
        "VECTOR_LRU_CACHE_KB", cfg["memory"].get("vector_lru_cache_kb", 1024)
    )
    cfg["memory"].setdefault("graph_bfs_frontier", 512)
    cfg["memory"].setdefault("max_working_set_kb", 1024)

    # ------------------------------------------------------------------ indexer
    cfg.setdefault("indexer", {})
    cfg["indexer"].setdefault("max_chunk_tokens", 300)
    cfg["indexer"].setdefault("min_chunk_tokens", 20)
    cfg["indexer"].setdefault("overlap_tokens", 30)
    cfg["indexer"].setdefault("file_extensions", [".js", ".jsx", ".ts", ".tsx"])
    cfg["indexer"].setdefault(
        "exclude_dirs",
        ["node_modules", ".git", "dist", "build", ".next", "coverage"],
    )

    # ------------------------------------------------------------------ retrieval
    cfg.setdefault("retrieval", {})
    cfg["retrieval"].setdefault("default_top_k", 10)
    cfg["retrieval"].setdefault("fts_candidate_pool", 50)
    cfg["retrieval"].setdefault("max_graph_depth", 4)
    cfg["retrieval"].setdefault("cache_ttl_seconds", 3600)
    cfg["retrieval"].setdefault("use_reranker", False)
    cfg["retrieval"].setdefault("reranker_model", "cross-encoder/ms-marco-MiniLM-L-6-v2")
    cfg["retrieval"].setdefault("reranker_top_k", 10)

    # ------------------------------------------------------------------ logging
    cfg.setdefault("logging", {})
    cfg["logging"]["level"] = os.getenv("LOG_LEVEL", cfg["logging"].get("level", "INFO"))

    # ------------------------------------------------------------------ plugins
    cfg.setdefault("plugins", {})
    cfg["plugins"].setdefault("enabled", [])

    # ------------------------------------------------------------------ derived paths
    cfg["_root"] = str(_ROOT)
    cfg["_models_dir"] = str(
        Path(os.getenv("MODELS_DIR", str(_ROOT / "models")))
    )
    cfg["_data_dir"] = str(
        Path(os.getenv("DATA_DIR", str(_ROOT / "data")))
    )

    return cfg


def get_log_level() -> int:
    """Return the Python logging level integer from config."""
    level_name = get_config()["logging"]["level"].upper()
    return getattr(logging, level_name, logging.INFO)
