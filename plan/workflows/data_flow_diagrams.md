# Indexing Pipeline — Data Flow

## Full Indexing Flow

```
USER: myrag index ./my-react-project
            │
            ▼
    ┌──────────────────────────────────┐
    │  IndexingPipeline.run()          │
    │  project_path: ./my-react-project│
    └────────────┬─────────────────────┘
                 │
                 ▼
    ┌────────────────────┐
    │  1. FILE SCANNER   │ ── walks directory ──►  [*.js, *.jsx, *.ts, *.tsx]
    │  file_scanner.py   │ ── filters ──────────►  exclude: node_modules/, dist/
    │                    │ ── classifies ────────►  COMPONENT | HOOK | ROUTE | UTIL
    └─────────┬──────────┘ ── hashes content ───►  SHA-256 per file
              │
              │  List[FileInfo]  (50 items)
              │
              ▼
    ┌────────────────────────┐
    │  2. CHANGE DETECTOR    │ ── compares vs SQLite ──►  {new: 5, modified: 2, deleted: 1}
    │  change_detector.py    │ ── deleted: remove from DB
    └─────────┬──────────────┘ ── new+modified: pass forward
              │
              │  List[FileInfo]  (7 changed files)
              │
              ▼
    ┌────────────────────────┐
    │  3. PARALLEL PARSING   │ ── ProcessPoolExecutor(max_workers=4)
    │  (tree_sitter_parser)  │
    │                        │  File A ──► parse ──► ParseResult A
    │                        │  File B ──► parse ──► ParseResult B
    │                        │  File C ──► parse ──► ParseResult C  (parallel)
    │                        │  File D ──► parse ──► ParseResult D
    └─────────┬──────────────┘
              │
              │  List[ParseResult]
              │
              ▼
    ┌────────────────────────┐
    │  4. METADATA EXTRACTOR │ ── component_extractor.py
    │                        │ ── hook_extractor.py
    │                        │ ── state_extractor.py
    │                        │ ── context_extractor.py
    │                        │ ── api_call_extractor.py
    │                        │ ── import_extractor.py
    └─────────┬──────────────┘
              │
              │  Rich metadata per file
              │
              ▼
    ┌────────────────────────┐
    │  5. CHUNKER            │ ── component_chunker.py  → COMPONENT chunks
    │  chunk_strategy.py     │ ── hook_chunker.py       → HOOK chunks
    │                        │ ── function_chunker.py   → FUNCTION chunks
    │                        │ ── route_chunker.py      → ROUTE_BLOCK chunks
    │                        │ ── fallback: sliding window (MISC)
    └─────────┬──────────────┘
              │
              │  List[Chunk]  (~200 chunks for 50 files)
              │
              ▼ ─────────────────────────────────────────────
              │
        ┌─────┴──────┬──────────────┬─────────────────┐
        │            │              │                 │
        ▼            ▼              ▼                 ▼
┌────────────┐ ┌────────────┐ ┌──────────────┐ ┌──────────────┐
│ 6. LEXICAL │ │ 7. EMBEDS  │ │  8. GRAPH    │ │  9. SYMBOLS  │
│  INDEXER   │ │  INDEXER   │ │   INDEXER    │ │   INDEXER    │
│            │ │            │ │              │ │              │
│ FTS5 INSERT│ │ONNX encode │ │ Import edges │ │ Symbol table │
│ Normalized │ │ → int8 q.  │ │ Call edges   │ │ population   │
│ camelCase  │ │ → BLOB     │ │ Hook edges   │ │              │
│ split text │ │            │ │ Route edges  │ │              │
└─────┬──────┘ └─────┬──────┘ └──────┬───────┘ └──────┬───────┘
      │              │               │                 │
      └──────────────┴───────────────┴─────────────────┘
                                     │
                                     ▼
                          ┌──────────────────────┐
                          │    SQLite Database   │
                          │    project.db        │
                          │                      │
                          │  ├── files           │
                          │  ├── chunks          │
                          │  ├── fts_chunks (V)  │
                          │  ├── embeddings      │
                          │  ├── graph_edges     │
                          │  ├── symbols         │
                          │  ├── routes          │
                          │  └── api_calls       │
                          └──────────────────────┘
                                     │
                                     ▼
                     IndexResponse {
                         project_id: "abc123",
                         file_count: 50,
                         chunk_count: 213,
                         duration_ms: 4823
                     }
```

---

## Retrieval Pipeline Flow

```
USER: "Where is authentication handled?"
            │
            ▼
    POST /query  {project_id: "abc123", query: "..."}
            │
            ▼
    ┌────────────────────────┐
    │   INTENT ROUTER        │ ── Rule matching: ARCHITECTURE (0.84 confidence)
    │   intent_router.py     │ ── Query expansion: + "auth login token JWT session"
    └─────────┬──────────────┘ ── Strategy: lex=0.2, sem=0.3, graph=0.5
              │
              │  RoutingDecision
              │
              ▼  ──────────────────────────────────────
              │
        ┌─────┴───────────────┬──────────────────────┐
        │ (parallel)          │                      │
        ▼                     ▼                      ▼
┌────────────────┐   ┌────────────────┐   ┌────────────────┐
│ LEXICAL        │   │ SEMANTIC       │   │ GRAPH          │
│ RETRIEVER      │   │ RETRIEVER      │   │ RETRIEVER      │
│                │   │                │   │                │
│ FTS5 MATCH     │   │ ONNX encode    │   │ BFS from seeds │
│ 'auth* OR      │   │ query → vec    │   │ depth=3        │
│  login OR ...' │   │                │   │ all edge types │
│                │   │ Compare vs     │   │                │
│ Top-50 results │   │ lex candidates │   │ Proximity      │
│ BM25 scored    │   │ Cosine sim     │   │ scores         │
└───────┬────────┘   └───────┬────────┘   └───────┬────────┘
        │                    │                    │
        │ {c_id: lex_score}  │ {c_id: sem_score}  │ {c_id: graph_score}
        │                    │                    │
        └────────────────────┴────────────────────┘
                             │
                             ▼
                   ┌────────────────────┐
                   │  SCORE FUSION      │
                   │                   │
                   │  final = 0.2*L    │
                   │        + 0.3*S    │
                   │        + 0.5*G    │
                   │                   │
                   │  Sort by final    │
                   │  Deduplicate      │
                   └─────────┬──────────┘
                             │
                             │ Top-10 RankedChunks
                             │
                             ▼
                   ┌────────────────────┐
                   │  CONTEXT BUILDER   │
                   │                   │
                   │  Rule summaries   │
                   │  Dep. summary     │
                   │  Token budget     │
                   │  Evidence pack    │
                   └─────────┬──────────┘
                             │
                             │ EvidencePack
                             │
                             ▼
                   ┌────────────────────┐
                   │  LLM LAYER (opt)   │ ── Ollama / llama.cpp / OpenAI
                   │                   │ ── Retrieval-first prompt
                   │  OR               │ ── Streaming tokens
                   │                   │
                   │  RAW RETRIEVAL    │ ── Direct chunk return
                   └─────────┬──────────┘
                             │
                             ▼
                   QueryResponse {
                       answer: "Authentication is handled...",
                       retrieved_chunks: [...],
                       latency_ms: 34
                   }
```
