-- Migration 002: Add summaries and caching enhancements

-- Add pre-computed FTS token column to chunks for CamelCase-split symbols
ALTER TABLE chunks ADD COLUMN fts_tokens TEXT;

-- Add semantic category labels for better intent routing
ALTER TABLE chunks ADD COLUMN semantic_tags TEXT;  -- JSON array: ["auth", "routing", "state"]

-- Add coverage metadata
ALTER TABLE files ADD COLUMN has_test_file INTEGER DEFAULT 0;
ALTER TABLE files ADD COLUMN test_file_path TEXT;

-- Improve retrieval cache with intent-aware keys
ALTER TABLE retrieval_cache ADD COLUMN intent TEXT;
ALTER TABLE retrieval_cache ADD COLUMN project_id TEXT;

-- Create cache index for faster lookups
CREATE INDEX IF NOT EXISTS idx_cache_project ON retrieval_cache(project_id);
CREATE INDEX IF NOT EXISTS idx_cache_ttl ON retrieval_cache(created_at, ttl_seconds);

-- Add hook usage tracking table
CREATE TABLE IF NOT EXISTS hook_usages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    chunk_id   TEXT NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
    hook_name  TEXT NOT NULL,    -- e.g., "useState", "useAuth", "useEffect"
    is_builtin INTEGER DEFAULT 0 -- 1 for React builtins, 0 for custom hooks
);
CREATE INDEX IF NOT EXISTS idx_hook_chunk ON hook_usages(chunk_id);
CREATE INDEX IF NOT EXISTS idx_hook_name  ON hook_usages(hook_name);

-- Add context usage tracking
CREATE TABLE IF NOT EXISTS context_usages (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    chunk_id     TEXT NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
    context_name TEXT NOT NULL,   -- e.g., "AuthContext", "ThemeContext"
    usage_type   TEXT NOT NULL    -- PROVIDES | CONSUMES | CREATES
);
CREATE INDEX IF NOT EXISTS idx_ctx_chunk ON context_usages(chunk_id);
CREATE INDEX IF NOT EXISTS idx_ctx_name  ON context_usages(context_name);

UPDATE indexing_metadata SET value='2' WHERE key='schema_version';
