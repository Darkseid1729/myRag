# 05 — DATABASE DESIGN

## Storage Philosophy

All persistent data lives in a **single SQLite file per indexed project** at `data/projects/<project_id>.db`.

This design ensures:
- Zero external dependencies
- Portable (single file backup/share)
- SQLite FTS5 for lexical search built-in
- BLOB storage for compact embeddings
- Zero network overhead

---

## Schema 1: `files` Table

Tracks all indexed source files.

```sql
CREATE TABLE files (
    id          TEXT PRIMARY KEY,        -- SHA-1 of normalized file path
    path        TEXT NOT NULL UNIQUE,    -- relative path from project root
    file_type   TEXT NOT NULL,           -- COMPONENT|HOOK|ROUTE|PAGE|UTIL|CONTEXT|STORE
    size_bytes  INTEGER,
    line_count  INTEGER,
    content_hash TEXT NOT NULL,          -- SHA-256 for change detection
    indexed_at  INTEGER NOT NULL,        -- Unix timestamp
    modified_at INTEGER NOT NULL         -- File mtime at index time
);

CREATE INDEX idx_files_type ON files(file_type);
CREATE INDEX idx_files_hash ON files(content_hash);
```

---

## Schema 2: `chunks` Table

Core table. Stores every extracted code chunk.

```sql
CREATE TABLE chunks (
    id          TEXT PRIMARY KEY,        -- SHA-1 of (file_id + start_line)
    file_id     TEXT NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    chunk_type  TEXT NOT NULL,           -- COMPONENT|HOOK|FUNCTION|ROUTE|IMPORT_BLOCK|MISC
    name        TEXT,                    -- e.g., "LoginForm", "useAuth", "handleSubmit"
    text        TEXT NOT NULL,           -- raw source code of this chunk
    start_line  INTEGER NOT NULL,
    end_line    INTEGER NOT NULL,
    char_count  INTEGER,
    summary     TEXT,                    -- compact auto-generated description
    created_at  INTEGER NOT NULL
);

CREATE INDEX idx_chunks_file ON chunks(file_id);
CREATE INDEX idx_chunks_type ON chunks(chunk_type);
CREATE INDEX idx_chunks_name ON chunks(name);
```

---

## Schema 3: `fts_chunks` Virtual Table (FTS5)

Enables fast full-text BM25 search over chunk content.

```sql
CREATE VIRTUAL TABLE fts_chunks USING fts5(
    chunk_id UNINDEXED,     -- FK back to chunks.id
    text,                   -- searchable chunk content
    symbols,                -- space-separated identifiers extracted from chunk
    summary,                -- searchable summary
    tokenize = "porter unicode61"  -- stem + unicode normalization
);
```

**FTS5 Porter Stemmer** ensures:
- `authentication` matches `auth`, `authenticate`, `authenticated`
- `rendering` matches `render`, `renders`, `rerender`

---

## Schema 4: `symbols` Table

Symbol-level index for fast exact-name lookups.

```sql
CREATE TABLE symbols (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chunk_id    TEXT NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,           -- identifier name
    symbol_type TEXT NOT NULL,           -- COMPONENT|HOOK|FUNCTION|STATE|CONTEXT|ROUTE|API
    is_exported INTEGER DEFAULT 0,       -- 1 if exported
    is_default_export INTEGER DEFAULT 0
);

CREATE INDEX idx_symbols_name ON symbols(name);
CREATE INDEX idx_symbols_type ON symbols(symbol_type);
CREATE INDEX idx_symbols_chunk ON symbols(chunk_id);
```

---

## Schema 5: `embeddings` Table

Stores quantized int8 embedding BLOBs.

```sql
CREATE TABLE embeddings (
    chunk_id    TEXT PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
    vector      BLOB NOT NULL,   -- int8 quantized, 384 bytes
    scale       REAL NOT NULL,   -- dequantization scale factor
    model_id    TEXT NOT NULL,   -- e.g., "all-MiniLM-L6-v2-int8"
    created_at  INTEGER NOT NULL
);
```

**Memory note**: BLOBs are lazy-loaded. SQLite only reads a BLOB when explicitly queried. A full project with 200 chunks = 200 × 384 bytes = ~75KB total.

---

## Schema 6: `graph_edges` Table

Stores all dependency and relationship edges.

```sql
CREATE TABLE graph_edges (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    from_id     TEXT NOT NULL,   -- chunk_id or file_id of source
    to_id       TEXT NOT NULL,   -- chunk_id or file_id of target
    edge_type   TEXT NOT NULL,   -- See edge type enum below
    weight      REAL DEFAULT 1.0,
    metadata    TEXT             -- JSON blob for extra edge data
);

-- Edge type enum:
-- IMPORTS, CALLS, USES_HOOK, RENDERS, PROVIDES_CONTEXT,
-- CONSUMES_CONTEXT, MANAGES_STATE, DEFINES_ROUTE, USES_API

CREATE INDEX idx_edges_from ON graph_edges(from_id);
CREATE INDEX idx_edges_to ON graph_edges(to_id);
CREATE INDEX idx_edges_type ON graph_edges(edge_type);
CREATE INDEX idx_edges_from_type ON graph_edges(from_id, edge_type);
```

---

## Schema 7: `routes` Table

Dedicated table for React Router route definitions.

```sql
CREATE TABLE routes (
    id          TEXT PRIMARY KEY,
    path        TEXT NOT NULL,        -- e.g., "/dashboard", "/user/:id"
    component   TEXT NOT NULL,        -- component name rendered at this route
    chunk_id    TEXT REFERENCES chunks(id),
    is_protected INTEGER DEFAULT 0,   -- behind auth guard?
    parent_route TEXT,                -- for nested routes
    metadata    TEXT                  -- JSON: exact, sensitive, lazy
);

CREATE INDEX idx_routes_path ON routes(path);
CREATE INDEX idx_routes_component ON routes(component);
```

---

## Schema 8: `api_calls` Table

Tracks all HTTP API calls made in the codebase.

```sql
CREATE TABLE api_calls (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chunk_id    TEXT NOT NULL REFERENCES chunks(id),
    method      TEXT,            -- GET|POST|PUT|DELETE|PATCH or NULL
    endpoint    TEXT,            -- e.g., "/api/users/:id" or variable
    client_type TEXT,            -- fetch|axios|useQuery|useMutation|custom
    is_dynamic  INTEGER DEFAULT 0  -- 1 if endpoint is a template literal
);

CREATE INDEX idx_api_chunk ON api_calls(chunk_id);
CREATE INDEX idx_api_endpoint ON api_calls(endpoint);
```

---

## Schema 9: `retrieval_cache` Table

Caches recent query results for sub-millisecond repeat lookups.

```sql
CREATE TABLE retrieval_cache (
    query_hash  TEXT PRIMARY KEY,    -- SHA-256 of normalized query + intent
    result_json TEXT NOT NULL,       -- cached RankedChunk list as JSON
    created_at  INTEGER NOT NULL,
    hit_count   INTEGER DEFAULT 0,
    ttl_seconds INTEGER DEFAULT 3600
);
```

**Eviction**: Background job purges rows where `created_at + ttl_seconds < now()`.

---

## Schema 10: `summaries` Table

Stores pre-generated compact summaries for chunks and files.

```sql
CREATE TABLE summaries (
    id          TEXT PRIMARY KEY,      -- chunk_id or file_id
    subject_type TEXT NOT NULL,        -- CHUNK|FILE
    summary     TEXT NOT NULL,
    generated_by TEXT NOT NULL,        -- RULE_BASED|LLM|TEMPLATE
    token_count INTEGER,
    created_at  INTEGER NOT NULL
);
```

---

## Schema 11: `indexing_metadata` Table

Tracks overall indexing status and statistics.

```sql
CREATE TABLE indexing_metadata (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL
);

-- Example rows:
-- ('project_root', '/home/user/myapp')
-- ('indexed_at', '1716192000')
-- ('file_count', '47')
-- ('chunk_count', '213')
-- ('embedding_model', 'all-MiniLM-L6-v2-int8')
-- ('schema_version', '3')
-- ('total_index_ms', '4823')
```

---

## Indexing Strategy

| Query Pattern | Index Used |
|--------------|-----------|
| Keyword search | FTS5 MATCH on `fts_chunks` |
| Symbol lookup by name | `idx_symbols_name` on `symbols` |
| Find all chunks in file | `idx_chunks_file` on `chunks` |
| Get neighbors of node | `idx_edges_from` on `graph_edges` |
| Find all callers of X | `idx_edges_to` on `graph_edges` |
| Route lookup | `idx_routes_path` on `routes` |
| Cached query result | Primary key on `retrieval_cache` |

---

## Query Optimization

- **FTS5 MATCH** uses trigram and porter-stemmed inverted index — O(log N)
- **Graph traversal** uses prepared statements with bound parameters — no re-parsing
- **Embedding similarity** is computed in Python (numpy), not SQL — avoids SQLite's lack of vector ops
- **JOIN strategy**: Always join on indexed FK columns (chunk_id, file_id)

---

## Compression Strategy

| Data | Raw Size | Compressed | Method |
|------|----------|------------|--------|
| Embeddings | 1536 bytes (float32) | 384 bytes (int8) | Scalar quantization |
| Chunk text | Variable | ~30% reduction | SQLite page compression (zstd optional) |
| Graph edges | 100 bytes/edge | 80 bytes/edge | No JSON, typed columns |
| Summaries | 200–500 chars | ≤100 chars | Rule-based truncation |

**Optional**: Enable SQLite3 zstd compression via [sqlite-zstd](https://github.com/phiresky/sqlite-zstd) extension for additional 2–4x space reduction.
