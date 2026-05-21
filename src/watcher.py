"""File watcher: auto-reindex on source file changes.

Uses watchdog for cross-platform file system events.

Debouncing:
- A per-file debounce dict prevents repeated re-index on rapid file saves
  (e.g., auto-formatters that write multiple times in quick succession).
- A threading.Lock guards against concurrent re-indexing of the same project.

The watcher is meant to be run in the foreground (blocks until Ctrl+C).
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from src.storage.project_registry import ProjectRegistry
from src.embeddings.onnx_encoder import ONNXEncoder
from src.indexer.indexing_pipeline import index_project
from src.config import get_config
from src.utils import get_logger

logger = get_logger(__name__)

_DEBOUNCE_SECONDS = 3.0


def _get_extensions() -> frozenset[str]:
    cfg = get_config()
    exts = cfg["indexer"].get("file_extensions", [".js", ".jsx", ".ts", ".tsx"])
    return frozenset(exts)


class _ChangeHandler(FileSystemEventHandler):
    def __init__(
        self,
        project_root: str,
        registry: ProjectRegistry,
        encoder: ONNXEncoder,
    ) -> None:
        self._root = project_root
        self._registry = registry
        self._encoder = encoder
        self._extensions = _get_extensions()
        self._lock = threading.Lock()
        # Map file_path → last event time for per-file debouncing
        self._last_event: dict[str, float] = {}

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return

        path = Path(str(event.src_path))
        if path.suffix not in self._extensions:
            return

        path_str = str(path)
        now = time.monotonic()
        last = self._last_event.get(path_str, 0.0)
        if now - last < _DEBOUNCE_SECONDS:
            return
        self._last_event[path_str] = now

        logger.info(f"Change detected: {path.name} — re-indexing…")
        self._reindex()

    def _reindex(self) -> None:
        """Re-index the project; non-blocking if already in progress."""
        if not self._lock.acquire(blocking=False):
            logger.debug("Re-index already in progress; skipping.")
            return
        try:
            db = self._registry.get_or_create(self._root)
            try:
                index_project(self._root, db, self._encoder)
            finally:
                db.close()
        except Exception as exc:
            logger.error(f"Re-index failed: {exc}", exc_info=True)
        finally:
            self._lock.release()


def watch(project_root: str) -> None:
    """Block and watch the project directory for changes, re-indexing on edits.

    Args:
        project_root: Absolute path to the project to watch.
    """
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
        pass
    finally:
        observer.stop()
        observer.join()
        logger.info("Watcher stopped.")
