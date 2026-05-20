"""Centralised application configuration loaded from config/default.yaml + .env."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()

_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _ROOT / "config" / "default.yaml"


@lru_cache(maxsize=1)
def get_config() -> dict:
    with open(_CONFIG_PATH) as f:
        cfg: dict = yaml.safe_load(f)

    # Environment variable overrides
    cfg["app"]["host"] = os.getenv("APP_HOST", cfg["app"]["host"])
    cfg["app"]["port"] = int(os.getenv("APP_PORT", cfg["app"]["port"]))
    cfg["llm"]["provider"] = os.getenv("LLM_PROVIDER", cfg["llm"]["provider"])
    cfg["embedding"]["model"] = os.getenv("EMBEDDING_MODEL", cfg["embedding"]["model"])

    cfg["_root"] = str(_ROOT)
    cfg["_models_dir"] = str(Path(os.getenv("MODELS_DIR", str(_ROOT / "models"))))
    cfg["_data_dir"] = str(Path(os.getenv("DATA_DIR", str(_ROOT / "data"))))

    return cfg
