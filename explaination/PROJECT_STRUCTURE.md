# Project Structure

Annotated file tree for MyRAG.

```
myrag/
│
├── src/                            Python source package
│   ├── __init__.py                 Package version (1.0.0)
│   ├── config.py                   Config loader (YAML + .env merge)
│   ├── utils.py                    Logging, hashing, timing, memory utils
│   ├── cli.py                      Click CLI entry point (myrag command)
│   ├── watcher.py                  Watchdog-based file system watcher
│   │
│   ├── api/                        FastAPI REST server
│   │   ├── __init__.py
│   │   └── server.py               All HTTP routes (/health /index /query /ask …)
│   │
│   ├── scanner/                    File discovery
│   │   ├── __init__.py
│   │   └── file_scanner.py         scan_project(), detect_changed_files()
│   │
│   ├── parser/                     AST parsing
│   │   ├── __init__.py
│   │   └── tree_sitter_parser.py   parse_file() → ParsedChunk[] (tree-sitter or regex)
│   │
│   ├── chunker/                    Token-budget chunking
│   │   ├── __init__.py
│   │   └── chunker.py              chunk_all() with overlap-aware split
│   │
│   ├── extractor/                  API call extraction
│   │   ├── __init__.py
│   │   └── api_extractor.py        extract_api_calls() (fetch/axios/useQuery)
│   │
│   ├── indexer/                    Orchestration
│   │   ├── __init__.py
│   │   └── indexing_pipeline.py    index_project() — main entry point
│   │
│   ├── embeddings/                 ONNX encoder
│   │   ├── __init__.py
│   │   └── onnx_encoder.py         ONNXEncoder, int8 quantize/dequantize, LRU cache
│   │
│   ├── storage/                    SQLite management
│   │   ├── __init__.py
│   │   ├── db_manager.py           DBManager — schema, CRUD, FTS5, cache
│   │   └── project_registry.py     ProjectRegistry — maps root paths to DB files
│   │
│   ├── graph/                      Dependency graph
│   │   ├── __init__.py
│   │   └── graph_builder.py        extract_graph_edges() — IMPORTS/USES_HOOK/RENDERS/…
│   │
│   ├── intent/                     Query understanding
│   │   ├── __init__.py
│   │   └── intent_router.py        IntentRouter, Intent enum, RetrievalStrategy
│   │
│   ├── retriever/                  Search engines
│   │   ├── __init__.py
│   │   ├── hybrid_retriever.py     hybrid_search(), lexical/semantic/graph search
│   │   └── reranker.py             CrossEncoder singleton + maybe_rerank()
│   │
│   ├── context/                    Prompt building
│   │   ├── __init__.py
│   │   └── builder.py              build_context() — token-budgeted evidence pack
│   │
│   ├── llm/                        LLM provider integrations
│   │   ├── __init__.py
│   │   ├── manager.py              generate() — routes to configured provider
│   │   └── providers.py            ollama_generate, llamacpp_generate, openai_generate
│   │
│   ├── plugins/                    Plugin system
│   │   ├── __init__.py
│   │   ├── manager.py              PluginManager — on_chunk/on_results/on_prompt hooks
│   │   └── typescript_plugin.py    Example TypeScript plugin
│   │
│   └── web/                        Browser UI
│       └── ui.html                 Full dark-mode single-page app
│
├── config/
│   └── default.yaml                All configuration defaults (overridden by .env)
│
├── tests/
│   ├── conftest.py                 Shared fixtures (temp dirs, DBManager)
│   ├── unit/
│   │   ├── __init__.py
│   │   ├── test_chunker.py         Chunker unit tests
│   │   ├── test_context_builder.py Context builder tests
│   │   ├── test_db.py              DB schema + CRUD tests
│   │   ├── test_intent.py          Intent router unit tests
│   │   ├── test_parser.py          Tree-sitter parser tests
│   │   ├── test_scanner.py         File scanner tests
│   │   └── test_api_extractor.py   API extractor tests
│   └── integration/
│       ├── __init__.py
│       └── test_full_pipeline.py   End-to-end: scan → index → query → verify
│
├── benchmarks/
│   └── run_bench.py                Timing + memory benchmark runner
│
├── scripts/
│   └── debug_route.py              Debug helper for route graph inspection
│
├── vscode-extension/               VSCode extension
│   ├── src/
│   │   └── extension.ts            Full extension (search panel, index, status bar)
│   ├── package.json                Extension manifest (commands, keybindings, config)
│   └── tsconfig.json               TypeScript compiler config
│
├── plan/                           Architecture design documents
│   ├── 00_MASTER_PLAN.md
│   ├── 01_system_overview.md
│   ├── ...
│   └── 20_final_recommendations.md
│
├── .env.example                    Template for environment variables
├── .gitignore
├── pyproject.toml                  Package metadata + dependencies
├── pytest.ini                      Test configuration
├── PROJECT_STATUS.md               Implementation status tracker
│
├── README.md                       Quick start + overview
├── ARCHITECTURE.md                 Module design and data flow
├── SETUP.md                        Installation guide
├── CONTRIBUTING.md                 How to contribute
├── INDEXING_PIPELINE.md            Indexing pipeline deep-dive
├── RETRIEVAL_SYSTEM.md             Retrieval system deep-dive
├── MEMORY_OPTIMIZATION.md          RAM budget and strategies
├── API_REFERENCE.md                HTTP API reference
└── PROJECT_STRUCTURE.md            This file
```

---

## Key Data Flows

### Index Request (`myrag index /path`)
```
cli.py:cmd_index
  └─ index_project(root, db, encoder)       [indexer/indexing_pipeline.py]
       ├─ scan_project(root)                [scanner/file_scanner.py]
       ├─ parse_file(abs_path)              [parser/tree_sitter_parser.py]
       ├─ chunk_all(parsed)                 [chunker/chunker.py]
       ├─ _store_chunk(db, chunk, encoder)  [indexing_pipeline.py]
       │   └─ encoder.encode_and_quantize() [embeddings/onnx_encoder.py]
       ├─ _store_api_calls(db, chunk_id)    [extractor/api_extractor.py]
       └─ extract_graph_edges(db, ...)      [graph/graph_builder.py]
```

### Query Request (`myrag search /path "query"`)
```
cli.py:cmd_search
  └─ hybrid_search(db, encoder, query, strategy)  [retriever/hybrid_retriever.py]
       ├─ IntentRouter.route(query)               [intent/intent_router.py]
       ├─ lexical_search(db, query)               [retriever/hybrid_retriever.py]
       ├─ semantic_search(db, encoder, query)      [retriever/hybrid_retriever.py]
       ├─ graph_search(db, seeds, strategy)        [retriever/hybrid_retriever.py]
       └─ score_fusion + optional reranker         [retriever/reranker.py]
```

### Ask Request (`myrag answer /path "question"`)
```
  └─ hybrid_search(...)
       └─ build_context(query, chunks)   [context/builder.py]
            └─ llm_generate(prompt)      [llm/manager.py]
                 └─ ollama/llamacpp/openai_generate() [llm/providers.py]
```

---

## Naming Conventions

| Entity | Convention | Example |
|--------|-----------|---------|
| Modules | `snake_case` | `tree_sitter_parser.py` |
| Classes | `PascalCase` | `DBManager`, `ONNXEncoder` |
| Functions | `snake_case` | `parse_file()`, `hybrid_search()` |
| Constants | `UPPER_SNAKE` | `_SCHEMA_SQL`, `_MAX_CHUNK_TOKENS` |
| Chunk IDs | SHA1 hex | `sha1_of_string(f"{file_id}:{line}:{name}")` |
| File IDs | SHA1 hex | `sha1_of_string(relative_path)` |
| DB names | `{project_id}.db` | `a3f1b2c4.db` |
