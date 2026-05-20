"""Maps project paths to per-project SQLite databases."""

from __future__ import annotations

import json
import time
from pathlib import Path

from src.utils import sha1_of_string, get_logger
from src.storage.db_manager import DBManager
from src.config import get_config

logger = get_logger(__name__)


class ProjectRegistry:
    """Manages the mapping of project_root -> SQLite database file."""

    def __init__(self) -> None:
        cfg = get_config()
        self._data_dir = Path(cfg["_data_dir"]) / "projects"
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._registry_file = Path(cfg["_data_dir"]) / "registry.json"
        self._registry: dict[str, str] = self._load()

    # ------------------------------------------------------------------
    # Registry persistence
    # ------------------------------------------------------------------

    def _load(self) -> dict[str, str]:
        if self._registry_file.exists():
            with open(self._registry_file) as f:
                return json.load(f)
        return {}

    def _save(self) -> None:
        with open(self._registry_file, "w") as f:
            json.dump(self._registry, f, indent=2)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_or_create(self, project_root: str) -> DBManager:
        """Return the DBManager for the project, creating it if necessary."""
        project_id = sha1_of_string(str(Path(project_root).resolve()))
        db_path = self._data_dir / f"{project_id}.db"

        if project_id not in self._registry:
            self._registry[project_id] = str(db_path)
            self._save()
            logger.info(f"Registered new project: {project_root} → {db_path}")

        cfg = get_config()
        db = DBManager(db_path, page_cache_kb=cfg["memory"]["sqlite_page_cache_kb"])
        db.connect()

        # Store project root if first time
        if not db.get_meta("project_root"):
            db.set_meta("project_root", str(Path(project_root).resolve()))
            db.set_meta("created_at", str(int(time.time())))
            db.commit()

        return db

    def list_projects(self) -> list[dict]:
        projects = []
        for pid, db_path in self._registry.items():
            p = Path(db_path)
            projects.append({
                "project_id": pid,
                "db_path": db_path,
                "exists": p.exists(),
                "size_bytes": p.stat().st_size if p.exists() else 0,
            })
        return projects

    def delete_project(self, project_root: str) -> bool:
        project_id = sha1_of_string(str(Path(project_root).resolve()))
        if project_id in self._registry:
            db_path = Path(self._registry.pop(project_id))
            if db_path.exists():
                db_path.unlink()
            self._save()
            return True
        return False
