# API Reference

## Base URL
```
http://localhost:8420
```

All responses are JSON. All request bodies are JSON.

---

## POST /index

Triggers indexing of a project.

### Request Body
```json
{
  "project_path": "/path/to/my-react-app",
  "project_id": "my-app-v1",          // optional, auto-generated if omitted
  "force_reindex": false,              // optional, default false
  "include_patterns": ["**/*.jsx"],   // optional, overrides config
  "exclude_patterns": ["**/*.test.*"] // optional, appends to config
}
```

### Response (200 OK)
```json
{
  "project_id": "my-app-v1",
  "file_count": 47,
  "chunk_count": 213,
  "embedding_count": 213,
  "edge_count": 748,
  "duration_ms": 4823,
  "status": "COMPLETE"
}
```

### Response (202 Accepted — Async)
```json
{
  "project_id": "my-app-v1",
  "status": "IN_PROGRESS",
  "check_status_url": "/status/my-app-v1"
}
```

### Error Responses
```json
// 400: Invalid path
{
  "error": "PROJECT_NOT_FOUND",
  "message": "Directory does not exist: /path/to/my-react-app"
}

// 409: Already indexing
{
  "error": "INDEXING_IN_PROGRESS",
  "message": "Project my-app-v1 is currently being indexed"
}
```

---

## GET /status/{project_id}

Get indexing status and project stats.

### Response (200 OK — Indexed)
```json
{
  "project_id": "my-app-v1",
  "indexed": true,
  "status": "COMPLETE",
  "file_count": 47,
  "chunk_count": 213,
  "last_indexed": "2026-05-20T10:00:00Z",
  "db_size_mb": 4.2,
  "embedding_model": "all-MiniLM-L6-v2-int8"
}
```

### Response (200 OK — Not indexed)
```json
{
  "project_id": "unknown-project",
  "indexed": false,
  "status": "NOT_INDEXED"
}
```

---

## POST /query

Main retrieval endpoint.

### Request Body
```json
{
  "project_id": "my-app-v1",
  "query": "Where is authentication handled?",
  "max_results": 10,               // optional, default 10
  "enable_llm": true,              // optional, default true if LLM configured
  "llm_backend": "ollama",         // optional, overrides config
  "stream": false,                 // optional, default false
  "intent_override": null          // optional: force a specific intent
}
```

### Response (200 OK — No LLM)
```json
{
  "query": "Where is authentication handled?",
  "intent": "ARCHITECTURE",
  "answer": null,
  "retrieved_chunks": [
    {
      "rank": 1,
      "file": "src/context/AuthContext.jsx",
      "name": "AuthContext",
      "chunk_type": "CONTEXT_DEF",
      "lines": "1-65",
      "summary": "Defines authentication context and AuthProvider component",
      "relevance": 0.937,
      "scores": {
        "lexical": 0.88,
        "semantic": 0.87,
        "graph": 1.0
      },
      "code": "import React, { createContext, useState... }"
    },
    {
      "rank": 2,
      "file": "src/hooks/useAuth.js",
      "name": "useAuth",
      "chunk_type": "HOOK",
      "lines": "1-85",
      "summary": "Custom hook exposing auth state and actions",
      "relevance": 0.713
    }
  ],
  "relationships": "AuthContext provides to LoginForm, Dashboard, PrivateRoute.",
  "confidence": 0.88,
  "latency_ms": 34,
  "from_cache": false
}
```

### Response (200 OK — With LLM)
```json
{
  "query": "Where is authentication handled?",
  "intent": "ARCHITECTURE",
  "answer": "Authentication is handled across 4 files:\n\n1. **AuthContext.jsx** (lines 1-65)...",
  "retrieved_chunks": [...],
  "relationships": "...",
  "confidence": 0.88,
  "latency_ms": 523,
  "from_cache": false
}
```

### Streaming Response (stream: true)
```
Content-Type: text/event-stream

data: {"type": "chunk_retrieved", "rank": 1, "name": "AuthContext"}
data: {"type": "chunk_retrieved", "rank": 2, "name": "useAuth"}
data: {"type": "llm_token", "token": "Authentication"}
data: {"type": "llm_token", "token": " is"}
data: {"type": "llm_token", "token": " handled"}
...
data: {"type": "done", "latency_ms": 523}
```

---

## GET /graph

Explore the code graph from a node.

### Request Parameters
```
GET /graph?project_id=my-app-v1&node_id=<chunk_id>&direction=outgoing&depth=2&edge_types=IMPORTS,CALLS
```

### Response
```json
{
  "root": {
    "node_id": "abc123def456",
    "name": "LoginForm",
    "file": "src/components/LoginForm.jsx",
    "chunk_type": "COMPONENT"
  },
  "edges": [
    {
      "from_id": "abc123def456",
      "to_id": "def789ghi012",
      "edge_type": "USES_HOOK",
      "to_name": "useAuth",
      "to_file": "src/hooks/useAuth.js",
      "depth": 1
    }
  ],
  "node_count": 7,
  "edge_count": 9
}
```

---

## GET /deps/{chunk_id}

Get dependency report for a chunk.

### Response
```json
{
  "chunk_id": "abc123def456",
  "chunk_name": "LoginForm",
  "dependencies": {
    "imports": ["useAuth", "FormInput", "Button"],
    "hooks_used": ["useAuth", "useNavigate", "useState"],
    "contexts_consumed": ["AuthContext"],
    "api_calls": ["POST /api/auth/login"]
  },
  "dependents": {
    "files_importing_this": ["src/App.jsx", "src/pages/LoginPage.jsx"],
    "components_using_this": ["LoginPage"]
  }
}
```

---

## POST /reindex/{project_id}

Incrementally reindex changed files only.

### Response
```json
{
  "project_id": "my-app-v1",
  "new_files": 2,
  "modified_files": 3,
  "deleted_files": 1,
  "new_chunks": 15,
  "duration_ms": 1243,
  "status": "COMPLETE"
}
```

---

## GET /list/projects

List all indexed projects.

### Response
```json
{
  "projects": [
    {
      "project_id": "my-app-v1",
      "path": "/home/user/my-react-app",
      "file_count": 47,
      "chunk_count": 213,
      "last_indexed": "2026-05-20T10:00:00Z",
      "db_size_mb": 4.2
    }
  ]
}
```

---

## DELETE /project/{project_id}

Remove a project's index.

### Response
```json
{
  "project_id": "my-app-v1",
  "deleted": true,
  "message": "Index and database removed"
}
```

---

## Error Format

All errors follow this format:
```json
{
  "error": "ERROR_CODE",
  "message": "Human-readable description",
  "detail": {}   // Optional extra context
}
```

### Error Codes

| Code | HTTP Status | Meaning |
|------|-------------|---------|
| `PROJECT_NOT_FOUND` | 400 | project_id doesn't exist |
| `INVALID_PATH` | 400 | project_path is invalid |
| `INDEXING_IN_PROGRESS` | 409 | Can't query while indexing |
| `NOT_INDEXED` | 409 | Project hasn't been indexed yet |
| `LLM_UNAVAILABLE` | 503 | Configured LLM backend not reachable |
| `INTERNAL_ERROR` | 500 | Unexpected server error |
