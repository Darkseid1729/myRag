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
# Logger — initialised once at module level
# ---------------------------------------------------------------------------

_LOG_INITIALISED = False


def setup_logging(level: int = logging.INFO) -> None:
    """Configure rich logging once.  Safe to call multiple times."""
    global _LOG_INITIALISED
    if _LOG_INITIALISED:
        return
    _LOG_INITIALISED = True
    # Remove any existing handlers on the root logger to avoid duplicates
    root = logging.getLogger()
    root.handlers.clear()
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True, markup=True, show_path=False)],
    )
    root.setLevel(level)


# Bootstrap with INFO on import; callers may call setup_logging() again with
# the configured level once config is available.
setup_logging(logging.INFO)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger.  ``setup_logging`` must have been called first."""
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


def split_camel_case(name: str) -> str:
    """Convert camelCase/PascalCase to space-separated tokens for FTS5."""
    import re
    # Insert space before uppercase letters that follow lowercase
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
    return s.lower()


# ---------------------------------------------------------------------------
# Memory monitor
# ---------------------------------------------------------------------------

def current_rss_mb() -> float:
    """Return the current resident set size in megabytes."""
    proc = psutil.Process()
    return proc.memory_info().rss / (1024 * 1024)


def log_memory(label: str = "") -> None:
    """Log current RSS memory usage at DEBUG level."""
    rss = current_rss_mb()
    tag = f"[{label}] " if label else ""
    logger.debug(f"{tag}RSS: {rss:.1f} MB")
