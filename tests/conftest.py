"""Pytest fixtures for MyRAG."""

import os
import tempfile
from pathlib import Path

import pytest
from src.config import get_config
from src.storage.db_manager import DBManager


@pytest.fixture(autouse=True)
def mock_env(monkeypatch):
    """Ensure tests run with an isolated environment."""
    monkeypatch.setenv("APP_HOST", "127.0.0.1")
    monkeypatch.setenv("APP_PORT", "8000")
    # Reset config cache
    get_config.cache_clear()


@pytest.fixture
def temp_project_dir():
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


@pytest.fixture
def temp_db(temp_project_dir):
    db_path = temp_project_dir / "test.db"
    db = DBManager(db_path, page_cache_kb=512)
    db.connect()
    yield db
    db.close()
