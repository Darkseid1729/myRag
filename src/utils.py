"""Shared utilities: logging, timing, hashing, text helpers, memory monitor."""

from __future__ import annotations

import hashlib
import logging
import time
from functools import wraps
from pathlib import Path
from typing import Any, Callable

import psutil
from rich.logging import RichHandler


# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------

def get_logger(name: str) -> logging.Logger:
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True, markup=True)],
    )
    return logging.getLogger(name)


logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Timing decorator
# ---------------------------------------------------------------------------

def timed(label: str = ""):
    """Log the wall-clock time of a function call."""
    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            t0 = time.perf_counter()
            result = fn(*args, **kwargs)
            elapsed = (time.perf_counter() - t0) * 1000
            tag = label or fn.__qualname__
            logger.debug(f"[timer] {tag} took {elapsed:.1f} ms")
            return result
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# Hashing helpers
# ---------------------------------------------------------------------------

def sha1_of_string(s: str) -> str:
    return hashlib.sha1(s.encode()).hexdigest()


def sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_of_string(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

def count_tokens_approx(text: str) -> int:
    """Rough token count: ~4 chars per token."""
    return max(1, len(text) // 4)


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    limit = max_tokens * 4
    return text[:limit] if len(text) > limit else text


# ---------------------------------------------------------------------------
# Memory monitor
# ---------------------------------------------------------------------------

def current_rss_mb() -> float:
    """Return the current resident set size in megabytes."""
    proc = psutil.Process()
    return proc.memory_info().rss / (1024 * 1024)
