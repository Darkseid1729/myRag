# Memory Architecture Workflow

## How 20MB is Maintained Per Project

```
═══════════════════════════════════════════════════════════════════
                     MEMORY LIFECYCLE DIAGRAM
═══════════════════════════════════════════════════════════════════

                        STARTUP
                           │
                           ▼
            ┌──────────────────────────┐
            │  ONNX Model Loaded       │ ← 30MB (shared singleton)
            │  all-MiniLM-L6-v2        │   loaded ONCE, shared across
            │  (one time, global)      │   ALL project queries
            └──────────────────────────┘
                           │
                           ▼
            ┌──────────────────────────┐
            │  FastAPI Server Ready    │ ← ~4MB Python runtime
            │  Listening on :8420      │
            └──────────────────────────┘

═══════════════════════════════════════════════════════════════════

                  INDEXING A PROJECT (one-time)
                           │
                           ▼
                    ┌─────────────┐
                    │ Read file   │ ← ~100KB (one file at a time)
                    └──────┬──────┘ (freed after parse)
                           │
                           ▼
                    ┌─────────────┐
                    │ Tree-sitter │ ← ~500KB AST (C memory)
                    │ parse       │   freed IMMEDIATELY after extraction
                    └──────┬──────┘
                           │
                           ▼
                    ┌─────────────┐
                    │ Extracted   │ ← ~3KB metadata dict
                    │ metadata    │   held briefly, then written to DB
                    └──────┬──────┘
                           │
                           ▼
                    ┌─────────────┐
                    │ Chunks      │ ← ~30KB per file (20 chunks × 1.5KB)
                    │ created     │   written to SQLite then freed
                    └──────┬──────┘
                           │
                           ▼
                    ┌─────────────┐
                    │ ONNX embed  │ ← ~1MB per batch (16 chunks)
                    │ batch=16    │   freed after writing BLOBs
                    └──────┬──────┘
                           │
                           ▼
                    ┌─────────────────────────────────┐
                    │         SQLite DB               │
                    │         project.db              │
                    │                                 │
                    │  ├── files       (tiny)         │
                    │  ├── chunks      (text BLOBs)   │
                    │  ├── fts_chunks  (inverted idx) │
                    │  ├── embeddings  (int8 BLOBs)   │ ← 76KB total
                    │  ├── graph_edges (rows)         │ ← 60KB total
                    │  └── symbols     (rows)         │
                    └─────────────────────────────────┘

═══════════════════════════════════════════════════════════════════

                    QUERY EXECUTION (per request)
                           │
    ┌──────────────────────┼──────────────────────┐
    │                      │                      │
    ▼                      ▼                      ▼
LEXICAL                SEMANTIC               GRAPH
  │                      │                      │
  │ FTS5 query           │ ONNX encode           │ BFS query
  │ ~500KB peak          │ ~100KB peak           │ ~100KB peak
  │ Result: 50 IDs       │ Load 50 blobs         │ frontier ~4KB
  │ ~50KB                │ = 50×384B = 19KB      │
  │                      │ Compute dots          │
  │                      │ ~50KB working         │
  │                      │                      │
  └──────────────────────┴──────────────────────┘
                          │
                          ▼
                   Score Fusion
                   ~50KB working set
                          │
                          ▼
                   Fetch top-10 chunk texts
                   ~500KB peak
                          │
                          ▼
                   Context Assembly
                   ~300KB evidence pack
                          │
                          ▼
                   JSON Serialization
                   ~200KB response
                          │
                          ▼
                   Return → buffers freed
                   ~0MB

    Total peak during query: ~1.5MB (well under 20MB target)

═══════════════════════════════════════════════════════════════════

                    LRU CACHE STEADY STATE
                    (after several queries)

    Embedding LRU Cache (max 1MB):
    ┌─────────────────────────────────────┐
    │ useAuth.js          → [384 floats] │ ← hot chunks stay in RAM
    │ AuthContext.jsx      → [384 floats] │
    │ LoginForm.jsx        → [384 floats] │
    │ Dashboard.jsx        → [384 floats] │
    │ ... (up to 1MB / 1.5KB = ~682 vecs)│
    └─────────────────────────────────────┘
    
    Query cache (SQLite, not RAM):
    ┌─────────────────────────────────────┐
    │ "where is auth?" → [cached result] │
    │ "how does routing work?" → [...]   │
    └─────────────────────────────────────┘

═══════════════════════════════════════════════════════════════════

                    PER-PROJECT RAM BUDGET SUMMARY

    ┌────────────────────────────────────────────────────────────┐
    │  Component              Budget    Notes                    │
    │  ─────────────────────────────────────────────────────     │
    │  SQLite page cache      4.0MB    Shared pool               │
    │  Embedding LRU cache    1.0MB    Hot embeddings only       │
    │  Query working memory   1.5MB    Peak, freed per query     │
    │  Graph working memory   0.5MB    BFS frontier only         │
    │  Intent router          0.1MB    Compiled patterns         │
    │  API buffers            1.0MB    Request/response          │
    │  Python overhead        4.0MB    Interpreter + modules     │
    │  OS overhead            3.0MB    Process metadata          │
    │  ─────────────────────────────────────────────────────     │
    │  TOTAL                 15.1MB    Target: ≤20MB ✓          │
    └────────────────────────────────────────────────────────────┘

    (+30MB for shared ONNX model, amortized across all projects)
```
