# API Reference

Base URL: `http://127.0.0.1:8000` (configurable via `APP_HOST` and `APP_PORT`)

All request and response bodies are JSON unless noted.

---

## `GET /health`

Check if the server is running.

**Response `200`:**
```json
{
  "status": "ok",
  "version": "1.0.0"
}
```

---

## `GET /stats`

Get real-time server statistics.

**Response `200`:**
```json
{
  "rss_mb": 18.4,
  "projects": 2,
  "version": "1.0.0"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `rss_mb` | float | Current process RSS memory in megabytes |
| `projects` | int | Number of currently indexed projects |
| `version` | string | Server version |

---

## `GET /`

Serves the Web UI (HTML page).

**Response `200`:** `text/html`

---

## `POST /index`

Index or re-index a project.

**Request body:**
```json
{
  "project_root": "D:\\path\\to\\react-project",
  "force_reindex": false
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `project_root` | string | ✓ | Absolute path to the project directory |
| `force_reindex` | bool | — | If `true`, re-indexes all files even if unchanged (default: `false`) |

**Response `200`:**
```json
{
  "status": "indexed",
  "project_id": "a3f1b2c4d5...",
  "stats": {
    "files_scanned": 47,
    "files_indexed": 12,
    "chunks_indexed": 84,
    "elapsed_ms": 2341
  }
}
```

| Field | Description |
|-------|-------------|
| `project_id` | SHA1 hash of the absolute project path |
| `stats.files_scanned` | Total source files found |
| `stats.files_indexed` | Files actually re-indexed (changed or new) |
| `stats.chunks_indexed` | Code chunks stored this run |
| `stats.elapsed_ms` | Total indexing time in milliseconds |

**Errors:**
- `422` — `project_root` does not exist on disk
- `500` — Internal indexing error (check server logs)

---

## `POST /query`

Hybrid search: lexical + semantic + graph retrieval.

**Request body:**
```json
{
  "project_root": "D:\\path\\to\\react-project",
  "query": "where is useAuth defined?",
  "top_k": 5
}
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `project_root` | string | ✓ | — | Absolute project path |
| `query` | string | ✓ | — | Natural language or keyword query (1–1000 chars) |
| `top_k` | int | — | 10 | Number of results to return (1–50) |

**Response `200`:**
```json
{
  "query": "where is useAuth defined?",
  "intent": "symbol_lookup",
  "confidence": 0.921,
  "results": [
    {
      "chunk_id": "a1b2c3d4...",
      "file_path": "src/hooks/useAuth.ts",
      "chunk_type": "HOOK",
      "name": "useAuth",
      "start_line": 3,
      "end_line": 22,
      "text": "export const useAuth = () => {\n  ...\n};",
      "final_score": 0.847,
      "lexical_score": 0.912,
      "semantic_score": 0.784,
      "graph_score": 0.500
    }
  ],
  "elapsed_ms": 23
}
```

| Field | Description |
|-------|-------------|
| `intent` | Detected intent (see [RETRIEVAL_SYSTEM.md](RETRIEVAL_SYSTEM.md)) |
| `confidence` | Intent classification confidence 0–1 |
| `results[].chunk_type` | `COMPONENT`, `HOOK`, `FUNCTION`, `IMPORT_BLOCK`, `MISC` |
| `results[].final_score` | Fused score (0–1, higher is more relevant) |
| `results[].lexical_score` | FTS5 BM25 contribution (0–1) |
| `results[].semantic_score` | Cosine similarity contribution (0–1) |
| `results[].graph_score` | Graph BFS contribution (0–1) |

---

## `POST /ask`

Search + optional LLM answer generation.

**Request body:**
```json
{
  "project_root": "D:\\path\\to\\react-project",
  "query": "how does authentication work?",
  "top_k": 5,
  "stream": false
}
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `project_root` | string | ✓ | — | Absolute project path |
| `query` | string | ✓ | — | Question for the LLM |
| `top_k` | int | — | 10 | Number of context chunks |
| `stream` | bool | — | false | If `true`, returns a streaming text/plain response |

**Response `200` (non-streaming):**
```json
{
  "query": "how does authentication work?",
  "answer": "Authentication in this project uses the useAuth hook defined in src/hooks/useAuth.ts...",
  "results": [ ... ]
}
```

**Response `200` (streaming, `stream: true`):**
```
Content-Type: text/plain

Authentication in this codebase works through...
```
Tokens are streamed as plain text. Each chunk of text is sent immediately as the LLM generates it.

**Errors:**
- `400` — LLM provider is set to `none`. Set `LLM_PROVIDER` in `.env`
- `500` — LLM connection failed or request error

---

## `GET /projects`

List all indexed projects.

**Response `200`:**
```json
[
  {
    "project_id": "a3f1b2...",
    "db_path": "D:\\myrag\\data\\a3f1b2.db",
    "size_bytes": 1048576
  }
]
```

---

## `DELETE /project`

Remove a project from the registry and delete its database.

**Query params:** `?project_root=D:\path\to\project`

**Response `200`:**
```json
{
  "status": "deleted",
  "project_root": "D:\\path\\to\\project"
}
```

**Errors:**
- `404` — Project not found in registry

---

## `GET /project/meta`

Get indexing metadata for a project.

**Query params:** `?project_root=D:\path\to\project`

**Response `200`:**
```json
{
  "project_root": "D:\\path\\to\\react-project",
  "indexed_at": "1716197234",
  "file_count": "47",
  "chunk_count": "312",
  "total_index_ms": "4821",
  "db_file_count": "47",
  "db_chunk_count": "312",
  "db_edge_count": "128"
}
```

---

## `GET /graph`

Get graph nodes and edges for visualisation.

**Query params:** `?project_root=D:\path\to\project&depth=2`

**Response `200`:**
```json
{
  "nodes": [
    {"id": "a1b2...", "label": "useAuth", "type": "HOOK"},
    {"id": "c3d4...", "label": "LoginForm", "type": "COMPONENT"}
  ],
  "edges": [
    {"from_id": "c3d4...", "to_id": "a1b2...", "edge_type": "USES_HOOK", "weight": 0.9}
  ],
  "total_edges": 128
}
```

**Note:** Returns at most 1,000 edges to keep response size bounded.

---

## `GET /docs`

Auto-generated Swagger UI (provided by FastAPI). Available at `http://localhost:8000/docs`.

---

## Error Format

All errors return:
```json
{
  "detail": "Human-readable error message"
}
```

---

## Rate Limits

There are no built-in rate limits. The server is intended for local use only (single developer). Do not expose it to the internet without adding authentication middleware.
