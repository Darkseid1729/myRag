# Project Status

All phases from the 18_mvp_roadmap are now complete.

## ✅ Completed / Implemented

### Core Infrastructure
- File scanning and classification for JS/TS/JSX/TSX with excluded dirs (config-driven)
- Incremental indexing based on SHA256 content hashes
- Tree-sitter parsing with regex fallback
- Overlap-aware chunker (`src/chunker/chunker.py`) with `overlap_tokens` support
- SQLite schema: FTS5, embeddings, symbols, graph_edges, routes, api_calls, cache
- DBManager with proper FTS5 cleanup, UNIQUE index on graph_edges, FK enforcement

### Embeddings
- ONNX embedding encoder with int8 scalar quantisation
- Thread-safe LRU vector cache (configurable byte cap)
- Batch cosine similarity with dequantisation-on-demand

### Retrieval
- Lexical: FTS5 BM25 with score normalisation to [0,1]
- Semantic: ONNX cosine with FTS pre-filtering + full-scan fallback
- Graph: weighted BFS with exponential decay and frontier cap
- Hybrid score fusion (intent-determined weights)
- Optional cross-encoder reranker (singleton cached, not per-query)
- Retrieval cache with TTL and hit counting

### Graph
- Proper graph builder module (`src/graph/graph_builder.py`)
- Edge types: IMPORTS, USES_HOOK, RENDERS, DEFINES_ROUTE, CONSUMES_CONTEXT, MANAGES_STATE
- Idempotent edge insertion (INSERT OR IGNORE + UNIQUE INDEX)
- Route table population

### API Extraction
- API call extractor (`src/extractor/api_extractor.py`)
- Supports: fetch, axios, useQuery, useMutation, RTK createApi
- Populates `api_calls` table

### Intent Router
- 7 intent types with rule-based regex matching
- Embedding-based fallback for generic queries
- Query expansion dictionary
- Per-intent retrieval strategies with weights and graph config

### API Server (FastAPI)
- /health, /stats, /index, /query, /ask, /projects, /project (DELETE), /project/meta, /graph
- Streaming fix (DB closed before streaming begins)
- Global exception handler
- Pydantic validators on request models

### CLI
- All commands: index, search, ask, answer, serve, list, watch, graph
- File watcher with per-file debounce and concurrency lock

### Web UI
- Full premium dark-mode single-page app
- Real-time search with intent badge, confidence bar
- Score display (final/lexical/semantic/graph per result)
- Syntax-highlighted code blocks
- Project list, query history (localStorage), loading states, error display
- Tabs: Search | Ask LLM

### VSCode Extension
- Search panel (WebviewPanel) with syntax-highlighted results
- Index command with progress notification and incremental/force mode
- Status bar showing server health
- Query-selection command (right-click selected code)
- Auto-index on save option
- File navigation from search results
- Keyboard shortcuts: Ctrl+Shift+M (search), Ctrl+Shift+Q (query selection)

### Configuration
- All env vars handled: APP_HOST, APP_PORT, LLM_PROVIDER, SQLITE_PAGE_CACHE_KB, VECTOR_LRU_CACHE_KB, LOG_LEVEL, EMBEDDING_MODEL, MODELS_DIR, DATA_DIR
- Validated defaults for all keys
- `get_log_level()` helper

### Utilities
- Singleton logging initialisation (no duplicate handlers)
- `split_camel_case()` for FTS5 symbol expansion
- `log_memory()` and `current_rss_mb()` memory monitors

### Tests
- 7 unit test files (chunker, parser, context builder, DB, intent, scanner, API extractor)
- 1 integration test file (full pipeline: scan → index → query → verify)
- All tests use mocked ONNX encoder (no network downloads in CI)

### Documentation
- README.md (complete with quick start, CLI reference, API summary)
- ARCHITECTURE.md (module map, data flows, design tradeoffs)
- SETUP.md (step-by-step, all platforms, troubleshooting)
- CONTRIBUTING.md (code standards, test patterns, PR process)
- INDEXING_PIPELINE.md (full stage diagram, config reference)
- RETRIEVAL_SYSTEM.md (intent taxonomy, BFS algorithm, score fusion)
- MEMORY_OPTIMIZATION.md (RAM budget, strategies, tuning guide)
- API_REFERENCE.md (all endpoints with request/response examples)
- PROJECT_STRUCTURE.md (annotated file tree, data flows, naming conventions)

## Known Limitations

- Graph edges are heuristic (regex-based) and may miss dynamic import() patterns
- Cross-encoder reranker requires ~67 MB extra RAM when enabled
- VSCode extension requires compilation (`tsc`) before use
- ONNX model first-download is 22 MB (requires internet on first run)
