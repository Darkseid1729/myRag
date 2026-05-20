"""File watcher: auto-reindex on source file changes."""

from __future__ import annotations

import time
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from src.storage.project_registry import ProjectRegistry
from src.embeddings.onnx_encoder import ONNXEncoder
from src.indexer.indexing_pipeline import index_project
from src.utils import get_logger

logger = get_logger(__name__)

_DEBOUNCE_SECONDS = 3.0
_EXTENSIONS = {".js", ".jsx", ".ts", ".tsx"}


class _ChangeHandler(FileSystemEventHandler):
    def __init__(self, project_root: str, registry: ProjectRegistry, encoder: ONNXEncoder) -> None:
        self._root = project_root
        self._registry = registry
        self._encoder = encoder
        self._last_event: float = 0.0

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        path = Path(str(event.src_path))
        if path.suffix not in _EXTENSIONS:
            return
        now = time.monotonic()
        if now - self._last_event < _DEBOUNCE_SECONDS:
            return
        self._last_event = now
        logger.info(f"Change detected: {path.name}. Re-indexing…")
        db = self._registry.get_or_create(self._root)
        try:
            index_project(self._root, db, self._encoder)
        finally:
            db.close()


def watch(project_root: str) -> None:
    """Block and watch the project directory for changes, re-indexing on edits."""
    registry = ProjectRegistry()
    encoder = ONNXEncoder()
    handler = _ChangeHandler(project_root, registry, encoder)
    observer = Observer()
    observer.schedule(handler, str(Path(project_root).resolve()), recursive=True)
    observer.start()
    logger.info(f"Watching {project_root}…  (Ctrl+C to stop)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
