"""SQLite database manager with strict memory controls and migration runner."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

from src.utils import get_logger

logger = get_logger(__name__)

# SQL for all 11 tables --------------------------------------------------

_SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA temp_store=MEMORY;

CREATE TABLE IF NOT EXISTS files (
    id           TEXT PRIMARY KEY,
    path         TEXT NOT NULL UNIQUE,
    file_type    TEXT NOT NULL,
    size_bytes   INTEGER,
    line_count   INTEGER,
    content_hash TEXT NOT NULL,
    indexed_at   INTEGER NOT NULL,
    modified_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_files_type ON files(file_type);
CREATE INDEX IF NOT EXISTS idx_files_hash ON files(content_hash);

CREATE TABLE IF NOT EXISTS chunks (
    id          TEXT PRIMARY KEY,
    file_id     TEXT NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    chunk_type  TEXT NOT NULL,
    name        TEXT,
    text        TEXT NOT NULL,
    start_line  INTEGER NOT NULL,
    end_line    INTEGER NOT NULL,
    char_count  INTEGER,
    summary     TEXT,
    created_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunks_file ON chunks(file_id);
CREATE INDEX IF NOT EXISTS idx_chunks_type ON chunks(chunk_type);
CREATE INDEX IF NOT EXISTS idx_chunks_name ON chunks(name);

CREATE VIRTUAL TABLE IF NOT EXISTS fts_chunks USING fts5(
    chunk_id UNINDEXED,
    text,
    symbols,
    summary,
    tokenize = "porter unicode61"
);

CREATE TABLE IF NOT EXISTS symbols (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    chunk_id           TEXT NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
    name               TEXT NOT NULL,
    symbol_type        TEXT NOT NULL,
    is_exported        INTEGER DEFAULT 0,
    is_default_export  INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_symbols_name  ON symbols(name);
CREATE INDEX IF NOT EXISTS idx_symbols_type  ON symbols(symbol_type);
CREATE INDEX IF NOT EXISTS idx_symbols_chunk ON symbols(chunk_id);

CREATE TABLE IF NOT EXISTS embeddings (
    chunk_id   TEXT PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
    vector     BLOB NOT NULL,
    scale      REAL NOT NULL,
    model_id   TEXT NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS graph_edges (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    from_id   TEXT NOT NULL,
    to_id     TEXT NOT NULL,
    edge_type TEXT NOT NULL,
    weight    REAL DEFAULT 1.0,
    metadata  TEXT
);
CREATE INDEX IF NOT EXISTS idx_edges_from      ON graph_edges(from_id);
CREATE INDEX IF NOT EXISTS idx_edges_to        ON graph_edges(to_id);
CREATE INDEX IF NOT EXISTS idx_edges_type      ON graph_edges(edge_type);
CREATE INDEX IF NOT EXISTS idx_edges_from_type ON graph_edges(from_id, edge_type);

CREATE TABLE IF NOT EXISTS routes (
    id           TEXT PRIMARY KEY,
    path         TEXT NOT NULL,
    component    TEXT NOT NULL,
    chunk_id     TEXT REFERENCES chunks(id),
    is_protected INTEGER DEFAULT 0,
    parent_route TEXT,
    metadata     TEXT
);
CREATE INDEX IF NOT EXISTS idx_routes_path      ON routes(path);
CREATE INDEX IF NOT EXISTS idx_routes_component ON routes(component);

CREATE TABLE IF NOT EXISTS api_calls (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chunk_id    TEXT NOT NULL REFERENCES chunks(id),
    method      TEXT,
    endpoint    TEXT,
    client_type TEXT,
    is_dynamic  INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_api_chunk    ON api_calls(chunk_id);
CREATE INDEX IF NOT EXISTS idx_api_endpoint ON api_calls(endpoint);

CREATE TABLE IF NOT EXISTS retrieval_cache (
    query_hash  TEXT PRIMARY KEY,
    result_json TEXT NOT NULL,
    created_at  INTEGER NOT NULL,
    hit_count   INTEGER DEFAULT 0,
    ttl_seconds INTEGER DEFAULT 3600
);

CREATE TABLE IF NOT EXISTS summaries (
    id           TEXT PRIMARY KEY,
    subject_type TEXT NOT NULL,
    summary      TEXT NOT NULL,
    generated_by TEXT NOT NULL,
    token_count  INTEGER,
    created_at   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS indexing_metadata (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class DBManager:
    """Manages a single SQLite database for one indexed project."""

    def __init__(self, db_path: Path, page_cache_kb: int = 4096) -> None:
        self.db_path = db_path
        self.page_cache_kb = page_cache_kb
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> None:
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row

        # Strict memory cap on SQLite page cache
        pages = (self.page_cache_kb * 1024) // 4096
        self._conn.execute(f"PRAGMA cache_size = -{self.page_cache_kb};")
        self._conn.execute("PRAGMA foreign_keys = ON;")
        self._init_schema()
        logger.debug(f"DB connected: {self.db_path}  (cache={self.page_cache_kb}KB)")

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "DBManager":
        self.connect()
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Schema initialisation
    # ------------------------------------------------------------------

    def _init_schema(self) -> None:
        assert self._conn
        self._conn.executescript(_SCHEMA_SQL)
        self._conn.commit()

    # ------------------------------------------------------------------
    # CRUD helpers
    # ------------------------------------------------------------------

    @property
    def conn(self) -> sqlite3.Connection:
        if not self._conn:
            raise RuntimeError("DBManager not connected. Call connect() first.")
        return self._conn

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        return self.conn.execute(sql, params)

    def executemany(self, sql: str, data: list[tuple]) -> None:
        self.conn.executemany(sql, data)

    def commit(self) -> None:
        self.conn.commit()

    def fetchone(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        return self.conn.execute(sql, params).fetchone()

    def fetchall(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        return self.conn.execute(sql, params).fetchall()

    # ------------------------------------------------------------------
    # Project metadata helpers
    # ------------------------------------------------------------------

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO indexing_metadata(key, value) VALUES (?, ?)",
            (key, value),
        )

    def get_meta(self, key: str) -> str | None:
        row = self.fetchone("SELECT value FROM indexing_metadata WHERE key=?", (key,))
        return row["value"] if row else None

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    def evict_expired_cache(self) -> int:
        now = int(time.time())
        cur = self.conn.execute(
            "DELETE FROM retrieval_cache WHERE created_at + ttl_seconds < ?", (now,)
        )
        self.conn.commit()
        return cur.rowcount
