# 03 — COMPLETE PROJECT STRUCTURE

## Full Folder & File Tree

```
myrag/
│
├── README.md
├── pyproject.toml              # Python project config (Poetry or setuptools)
├── package.json                # Node.js deps for parser bridge
├── .env.example                # Environment variable template
├── .gitignore
│
├── config/
│   ├── default.yaml            # Default system configuration
│   ├── memory_profiles.yaml    # RAM budget profiles (low/medium/high)
│   └── llm_providers.yaml      # LLM backend configs (ollama, llamacpp, openai)
│
├── src/
│   ├── __init__.py
│   │
│   ├── api/                    # HTTP API Layer
│   │   ├── __init__.py
│   │   ├── server.py           # FastAPI app, CORS, middleware
│   │   ├── routes/
│   │   │   ├── index_routes.py      # POST /index, GET /status
│   │   │   ├── query_routes.py      # POST /query
│   │   │   └── graph_routes.py      # GET /graph, GET /deps
│   │   ├── models/
│   │   │   ├── request_models.py    # Pydantic request schemas
│   │   │   └── response_models.py   # Pydantic response schemas
│   │   └── middleware/
│   │       ├── error_handler.py
│   │       └── rate_limiter.py
│   │
│   ├── scanner/                # File Scanner Module
│   │   ├── __init__.py
│   │   ├── file_scanner.py     # Walks project dir, filters JS/JSX/TS/TSX
│   │   ├── file_classifier.py  # Detects: component / hook / util / route / config
│   │   └── change_detector.py  # Incremental: detects modified files via mtime/hash
│   │
│   ├── parser/                 # AST Parser Module
│   │   ├── __init__.py
│   │   ├── tree_sitter_parser.py    # Tree-sitter JS/TSX parsing
│   │   ├── babel_bridge.py          # Node.js Babel parser bridge (subprocess)
│   │   ├── node_extractor.py        # Extracts nodes from AST
│   │   └── jsx_handler.py           # JSX-specific extraction (component tree)
│   │
│   ├── extractor/              # Metadata Extractor Module
│   │   ├── __init__.py
│   │   ├── component_extractor.py   # React component detection
│   │   ├── hook_extractor.py        # Custom hook detection (use* pattern)
│   │   ├── route_extractor.py       # React Router route detection
│   │   ├── import_extractor.py      # Import/export mapping
│   │   ├── state_extractor.py       # useState, useReducer, Redux, Zustand
│   │   ├── context_extractor.py     # createContext, Provider, useContext
│   │   ├── api_call_extractor.py    # fetch(), axios, useQuery, useMutation
│   │   ├── event_handler_extractor.py  # onClick, onChange, onSubmit handlers
│   │   └── function_extractor.py    # General function definitions
│   │
│   ├── chunker/                # Chunking Module
│   │   ├── __init__.py
│   │   ├── chunk_strategy.py   # Strategy selector based on file type
│   │   ├── component_chunker.py  # Component-level splitting
│   │   ├── function_chunker.py   # Function-level splitting
│   │   ├── hook_chunker.py       # Hook-level splitting
│   │   ├── route_chunker.py      # Route-level splitting
│   │   ├── sliding_chunker.py    # Fallback: sliding window for non-parseable
│   │   └── chunk_models.py       # Chunk dataclass definition
│   │
│   ├── indexer/                # Index Building Module
│   │   ├── __init__.py
│   │   ├── lexical_indexer.py   # FTS5 population
│   │   ├── embedding_indexer.py # ONNX encode + quantize + store
│   │   ├── graph_indexer.py     # Graph edge construction + storage
│   │   ├── symbol_indexer.py    # Symbol table population
│   │   └── indexing_pipeline.py # Orchestrates all indexers
│   │
│   ├── embeddings/             # Embedding Module
│   │   ├── __init__.py
│   │   ├── onnx_encoder.py      # ONNX Runtime inference wrapper
│   │   ├── quantizer.py         # float32 → int8 quantization
│   │   ├── embedding_cache.py   # LRU cache for hot embeddings
│   │   └── model_loader.py      # Download + cache ONNX model locally
│   │
│   ├── graph/                  # Graph Engine Module
│   │   ├── __init__.py
│   │   ├── graph_builder.py     # Constructs edges from extracted metadata
│   │   ├── graph_store.py       # SQLite-backed adjacency storage
│   │   ├── graph_traversal.py   # BFS/DFS traversal algorithms
│   │   ├── impact_analyzer.py   # "What does changing X affect?"
│   │   ├── dependency_tracer.py # "What does X depend on?"
│   │   └── graph_models.py      # Edge/Node dataclasses
│   │
│   ├── retriever/              # Retrieval Module
│   │   ├── __init__.py
│   │   ├── lexical_retriever.py     # FTS5 BM25 search
│   │   ├── semantic_retriever.py    # Cosine similarity over embeddings
│   │   ├── graph_retriever.py       # Graph-aware chunk retrieval
│   │   ├── hybrid_retriever.py      # Score fusion + reranking
│   │   └── reranker.py              # Cross-encoder reranking (optional)
│   │
│   ├── intent/                 # Intent Router Module
│   │   ├── __init__.py
│   │   ├── intent_classifier.py  # Rule-based + optional embedding classifier
│   │   ├── intent_models.py      # Intent enum and metadata
│   │   ├── query_expander.py     # Expand query with synonyms/related terms
│   │   └── strategy_selector.py  # Maps intent → retrieval weights
│   │
│   ├── context/                # Context Builder Module
│   │   ├── __init__.py
│   │   ├── evidence_builder.py   # Assembles evidence pack
│   │   ├── chunk_summarizer.py   # Compact per-chunk summaries
│   │   ├── dependency_summarizer.py  # Structural relationship summaries
│   │   └── token_budget.py       # Manages max context token count
│   │
│   ├── llm/                    # LLM Integration Module
│   │   ├── __init__.py
│   │   ├── base_llm.py          # Abstract LLM interface
│   │   ├── ollama_client.py     # Ollama HTTP client
│   │   ├── llamacpp_client.py   # llama.cpp subprocess wrapper
│   │   ├── openai_client.py     # OpenAI API client
│   │   ├── prompt_builder.py    # Assembles final LLM prompt
│   │   └── response_parser.py   # Parses LLM markdown output
│   │
│   ├── storage/                # Storage Module
│   │   ├── __init__.py
│   │   ├── db_manager.py        # SQLite connection pool + migration runner
│   │   ├── migrations/
│   │   │   ├── 001_initial_schema.sql
│   │   │   ├── 002_add_summaries.sql
│   │   │   └── 003_add_cache.sql
│   │   ├── project_registry.py  # Maps project_id ↔ project_path ↔ db file
│   │   └── cache_store.py       # SQLite retrieval result cache
│   │
│   └── utils/
│       ├── __init__.py
│       ├── logger.py
│       ├── timer.py              # Performance timing decorator
│       ├── hash_utils.py         # File hash for change detection
│       ├── text_utils.py         # Token counting, text normalization
│       └── memory_monitor.py     # RAM usage tracker
│
├── parser_bridge/               # Node.js Parser Bridge (subprocess)
│   ├── package.json
│   ├── index.js                 # Entry point: stdin JSON → stdout JSON
│   ├── parsers/
│   │   ├── babel_parser.js      # Babel AST parsing
│   │   └── tsx_parser.js        # TypeScript + JSX parsing
│   └── extractors/
│       ├── component_extractor.js
│       ├── hook_extractor.js
│       └── import_extractor.js
│
├── models/                      # Local ONNX model storage
│   └── all-MiniLM-L6-v2/
│       ├── model.onnx
│       ├── tokenizer.json
│       └── vocab.txt
│
├── data/                        # Project index databases
│   └── projects/
│       └── <project_id>.db      # Per-project SQLite database
│
├── ui/                          # Optional lightweight web UI
│   ├── index.html
│   ├── app.js
│   └── style.css
│
├── plugins/                     # Plugin system
│   ├── __init__.py
│   ├── plugin_base.py           # Abstract Plugin class
│   ├── vscode_plugin/           # VSCode extension scaffold
│   │   ├── package.json
│   │   └── extension.js
│   └── typescript_plugin/       # TypeScript type extraction
│       ├── __init__.py
│       └── ts_extractor.py
│
├── tests/
│   ├── unit/
│   │   ├── test_parser.py
│   │   ├── test_chunker.py
│   │   ├── test_lexical.py
│   │   ├── test_semantic.py
│   │   ├── test_graph.py
│   │   ├── test_intent.py
│   │   └── test_hybrid.py
│   ├── integration/
│   │   ├── test_full_pipeline.py
│   │   └── test_api.py
│   ├── fixtures/
│   │   ├── sample_react_project/  # Minimal 10-file React project for tests
│   │   └── expected_outputs/
│   └── conftest.py
│
└── benchmarks/
    ├── bench_indexing.py         # Measure indexing speed + RAM
    ├── bench_retrieval.py        # Measure retrieval latency
    ├── bench_memory.py           # Measure peak RAM per subsystem
    └── results/
        └── README.md
```

---

## File Count Summary

| Directory | Approximate File Count |
|-----------|----------------------|
| `src/api/` | 8 files |
| `src/scanner/` | 4 files |
| `src/parser/` | 5 files |
| `src/extractor/` | 9 files |
| `src/chunker/` | 7 files |
| `src/indexer/` | 6 files |
| `src/embeddings/` | 5 files |
| `src/graph/` | 7 files |
| `src/retriever/` | 6 files |
| `src/intent/` | 5 files |
| `src/context/` | 5 files |
| `src/llm/` | 7 files |
| `src/storage/` | 6 files |
| `src/utils/` | 6 files |
| `parser_bridge/` | 6 files |
| `plugins/` | 5 files |
| `tests/` | 12 files |
| `benchmarks/` | 5 files |
| **Total** | **~119 files** |
