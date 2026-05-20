-- Migration 003: Add performance and extensibility features

-- Add incremental indexing support
CREATE TABLE IF NOT EXISTS file_watch_state (
    file_id      TEXT PRIMARY KEY REFERENCES files(id) ON DELETE CASCADE,
    last_hash    TEXT NOT NULL,
    last_indexed INTEGER NOT NULL,
    watch_status TEXT DEFAULT 'WATCHING'  -- WATCHING | PAUSED | IGNORED
);

-- Add LSH index for approximate nearest neighbor (large projects)
CREATE TABLE IF NOT EXISTS lsh_index (
    chunk_id   TEXT NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
    table_idx  INTEGER NOT NULL,   -- Which LSH table (0-3)
    bucket_id  INTEGER NOT NULL    -- Hash bucket number
);
CREATE INDEX IF NOT EXISTS idx_lsh_bucket ON lsh_index(table_idx, bucket_id);

-- Add plugin metadata tracking
CREATE TABLE IF NOT EXISTS plugin_data (
    plugin_name TEXT NOT NULL,
    chunk_id    TEXT REFERENCES chunks(id) ON DELETE CASCADE,
    key         TEXT NOT NULL,
    value       TEXT NOT NULL,
    PRIMARY KEY (plugin_name, chunk_id, key)
);

-- Add LLM-generated summaries tracking
CREATE TABLE IF NOT EXISTS llm_summaries (
    chunk_id     TEXT PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
    summary      TEXT NOT NULL,
    model_used   TEXT NOT NULL,
    generated_at INTEGER NOT NULL,
    token_cost   INTEGER          -- For cost tracking
);

-- Add query analytics (opt-in)
CREATE TABLE IF NOT EXISTS query_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    query       TEXT NOT NULL,
    intent      TEXT,
    result_count INTEGER,
    latency_ms  INTEGER,
    had_llm     INTEGER DEFAULT 0,
    created_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_querylog_time ON query_log(created_at);

UPDATE indexing_metadata SET value='3' WHERE key='schema_version';
