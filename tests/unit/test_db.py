"""Tests for the DB manager schema initialisation."""

import tempfile
from pathlib import Path
from src.storage.db_manager import DBManager


def _make_db() -> DBManager:
    tmp = tempfile.mkdtemp()
    db = DBManager(Path(tmp) / "test.db", page_cache_kb=512)
    db.connect()
    return db


def test_schema_created():
    db = _make_db()
    tables = {
        row[0]
        for row in db.fetchall("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert "files" in tables
    assert "chunks" in tables
    assert "embeddings" in tables
    assert "graph_edges" in tables
    db.close()


def test_metadata_round_trip():
    db = _make_db()
    db.set_meta("test_key", "hello")
    db.commit()
    assert db.get_meta("test_key") == "hello"
    db.close()


def test_file_insert():
    db = _make_db()
    import time
    now = int(time.time())
    db.execute(
        "INSERT INTO files VALUES (?,?,?,?,?,?,?,?)",
        ("abc", "src/App.tsx", "COMPONENT", 100, 10, "hash123", now, now),
    )
    db.commit()
    row = db.fetchone("SELECT * FROM files WHERE id='abc'")
    assert row["path"] == "src/App.tsx"
    db.close()
