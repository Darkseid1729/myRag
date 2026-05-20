-- SQLite Schema: Initial (Migration 001)
-- All tables for the RAG code intelligence system

PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
PRAGMA cache_size=-4096;   -- 4MB page cache
PRAGMA temp_store=MEMORY;
PRAGMA synchronous=NORMAL;

-- ============================================================
-- FILES TABLE
-- ============================================================
CREATE TABLE IF NOT EXISTS files (
    id           TEXT PRIMARY KEY,
    path         TEXT NOT NULL UNIQUE,
    file_type    TEXT NOT NULL DEFAULT 'UNKNOWN',
    size_bytes   INTEGER,
    line_count   INTEGER,
    content_hash TEXT NOT NULL,
    indexed_at   INTEGER NOT NULL,
    modified_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_files_type ON files(file_type);
CREATE INDEX IF NOT EXISTS idx_files_hash ON files(content_hash);

-- ============================================================
-- CHUNKS TABLE
-- ============================================================
CREATE TABLE IF NOT EXISTS chunks (
    id          TEXT PRIMARY KEY,
    file_id     TEXT NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    chunk_type  TEXT NOT NULL DEFAULT 'MISC',
    name        TEXT,
    text        TEXT NOT NULL,
    start_line  INTEGER NOT NULL,
    end_line    INTEGER NOT NULL,
    char_count  INTEGER,
    has_state   INTEGER DEFAULT 0,
    has_jsx     INTEGER DEFAULT 0,
    has_api     INTEGER DEFAULT 0,
    has_context INTEGER DEFAULT 0,
    metadata    TEXT,   -- JSON blob for extra metadata
    summary     TEXT,
    created_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunks_file   ON chunks(file_id);
CREATE INDEX IF NOT EXISTS idx_chunks_type   ON chunks(chunk_type);
CREATE INDEX IF NOT EXISTS idx_chunks_name   ON chunks(name);
CREATE INDEX IF NOT EXISTS idx_chunks_cover  ON chunks(id, name, file_id, chunk_type, start_line, end_line);

-- ============================================================
-- FTS5 VIRTUAL TABLE (Lexical Index)
-- ============================================================
CREATE VIRTUAL TABLE IF NOT EXISTS fts_chunks USING fts5(
    chunk_id UNINDEXED,
    text,
    symbols,
    summary,
    tokenize = "porter unicode61"
);

-- ============================================================
-- SYMBOLS TABLE
-- ============================================================
CREATE TABLE IF NOT EXISTS symbols (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    chunk_id            TEXT NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
    name                TEXT NOT NULL,
    symbol_type         TEXT NOT NULL,
    is_exported         INTEGER DEFAULT 0,
    is_default_export   INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_symbols_name  ON symbols(name);
CREATE INDEX IF NOT EXISTS idx_symbols_type  ON symbols(symbol_type);
CREATE INDEX IF NOT EXISTS idx_symbols_chunk ON symbols(chunk_id);

-- ============================================================
-- EMBEDDINGS TABLE
-- ============================================================
CREATE TABLE IF NOT EXISTS embeddings (
    chunk_id   TEXT PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
    vector     BLOB NOT NULL,
    scale      REAL NOT NULL,
    model_id   TEXT NOT NULL,
    created_at INTEGER NOT NULL
);

-- ============================================================
-- GRAPH EDGES TABLE
-- ============================================================
CREATE TABLE IF NOT EXISTS graph_edges (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    from_id   TEXT NOT NULL,
    to_id     TEXT NOT NULL,
    edge_type INTEGER NOT NULL,  -- Edge type enum (1-9)
    weight    REAL DEFAULT 1.0,
    metadata  TEXT               -- Optional JSON
);
CREATE INDEX IF NOT EXISTS idx_edges_from      ON graph_edges(from_id, edge_type);
CREATE INDEX IF NOT EXISTS idx_edges_to        ON graph_edges(to_id, edge_type);
CREATE INDEX IF NOT EXISTS idx_edges_from_type ON graph_edges(from_id, edge_type);

-- Edge type reference (stored as INTEGER for efficiency):
-- 1 = IMPORTS
-- 2 = CALLS
-- 3 = USES_HOOK
-- 4 = RENDERS
-- 5 = PROVIDES_CONTEXT
-- 6 = CONSUMES_CONTEXT
-- 7 = MANAGES_STATE
-- 8 = DEFINES_ROUTE
-- 9 = USES_API

-- ============================================================
-- ROUTES TABLE
-- ============================================================
CREATE TABLE IF NOT EXISTS routes (
    id           TEXT PRIMARY KEY,
    path         TEXT NOT NULL,
    component    TEXT NOT NULL,
    chunk_id     TEXT REFERENCES chunks(id),
    is_protected INTEGER DEFAULT 0,
    parent_route TEXT,
    is_lazy      INTEGER DEFAULT 0,
    metadata     TEXT
);
CREATE INDEX IF NOT EXISTS idx_routes_path      ON routes(path);
CREATE INDEX IF NOT EXISTS idx_routes_component ON routes(component);

-- ============================================================
-- API CALLS TABLE
-- ============================================================
CREATE TABLE IF NOT EXISTS api_calls (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chunk_id    TEXT NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
    method      TEXT,
    endpoint    TEXT,
    client_type TEXT,
    is_dynamic  INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_api_chunk    ON api_calls(chunk_id);
CREATE INDEX IF NOT EXISTS idx_api_endpoint ON api_calls(endpoint);

-- ============================================================
-- RETRIEVAL CACHE TABLE
-- ============================================================
CREATE TABLE IF NOT EXISTS retrieval_cache (
    query_hash  TEXT PRIMARY KEY,
    result_json TEXT NOT NULL,
    created_at  INTEGER NOT NULL,
    hit_count   INTEGER DEFAULT 0,
    ttl_seconds INTEGER DEFAULT 3600
);

-- ============================================================
-- SUMMARIES TABLE
-- ============================================================
CREATE TABLE IF NOT EXISTS summaries (
    id           TEXT PRIMARY KEY,
    subject_type TEXT NOT NULL,
    summary      TEXT NOT NULL,
    generated_by TEXT NOT NULL DEFAULT 'RULE_BASED',
    token_count  INTEGER,
    created_at   INTEGER NOT NULL
);

-- ============================================================
-- INDEXING METADATA TABLE
-- ============================================================
CREATE TABLE IF NOT EXISTS indexing_metadata (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

INSERT OR REPLACE INTO indexing_metadata VALUES('schema_version', '1');
INSERT OR REPLACE INTO indexing_metadata VALUES('indexed_at', CAST(strftime('%s', 'now') AS TEXT));
