"""File scanner: walks project tree and classifies JS/TS/JSX/TSX source files."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from src.utils import sha256_of_file, sha1_of_string, get_logger

logger = get_logger(__name__)

_DEFAULT_EXTENSIONS = {".js", ".jsx", ".ts", ".tsx"}
_DEFAULT_EXCLUDE = {
    "node_modules", ".git", "dist", "build", ".next",
    "coverage", "__pycache__", ".vite", ".cache",
}

_TYPE_HINTS = {
    "hook": "HOOK",
    "context": "CONTEXT",
    "store": "STORE",
    "reducer": "STORE",
    "route": "ROUTE",
    "page": "PAGE",
    "pages": "PAGE",
    "component": "COMPONENT",
}


@dataclass
class ScannedFile:
    id: str
    path: str           # relative to project root
    abs_path: str
    file_type: str
    size_bytes: int
    line_count: int
    content_hash: str
    modified_at: int
    indexed_at: int = field(default_factory=lambda: int(time.time()))


def _classify_file(rel_path: str, stem: str) -> str:
    parts = rel_path.lower().replace("\\", "/").split("/")
    stem_lower = stem.lower()
    for part in parts:
        for hint, ft in _TYPE_HINTS.items():
            if hint in part:
                return ft
    # Hook by naming convention
    if stem_lower.startswith("use"):
        return "HOOK"
    return "UTIL"


def scan_project(root: str | Path) -> list[ScannedFile]:
    """Walk a project directory and return all indexable source files."""
    root = Path(root).resolve()
    results: list[ScannedFile] = []

    for dirpath, dirnames, filenames in os.walk(root):
        # Prune excluded directories in-place
        dirnames[:] = [d for d in dirnames if d not in _DEFAULT_EXCLUDE]

        for fname in filenames:
            abs_path = Path(dirpath) / fname
            if abs_path.suffix not in _DEFAULT_EXTENSIONS:
                continue

            rel_path = str(abs_path.relative_to(root))
            try:
                stat = abs_path.stat()
                content_hash = sha256_of_file(abs_path)
                line_count = abs_path.read_text(errors="replace").count("\n") + 1
                file_type = _classify_file(rel_path, abs_path.stem)
                file_id = sha1_of_string(rel_path)

                results.append(ScannedFile(
                    id=file_id,
                    path=rel_path,
                    abs_path=str(abs_path),
                    file_type=file_type,
                    size_bytes=stat.st_size,
                    line_count=line_count,
                    content_hash=content_hash,
                    modified_at=int(stat.st_mtime),
                ))
            except (OSError, UnicodeDecodeError) as exc:
                logger.warning(f"Skipping {abs_path}: {exc}")

    logger.info(f"Scanned {len(results)} source files in {root}")
    return results


def detect_changed_files(
    scanned: list[ScannedFile],
    db_hashes: dict[str, str],
) -> list[ScannedFile]:
    """Return only files whose content_hash differs from the DB record."""
    changed = []
    for sf in scanned:
        if db_hashes.get(sf.id) != sf.content_hash:
            changed.append(sf)
    return changed
