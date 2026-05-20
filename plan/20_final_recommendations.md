# 20 — FINAL ENGINEERING RECOMMENDATIONS

## 20.1 Best Tech Stack Recommendation

### Primary Stack

```
Language:       Python 3.11+
                ├── Async I/O: asyncio + aiosqlite
                ├── Type safety: Pydantic v2
                └── Package management: uv (fast) or Poetry

Parser:         tree-sitter 0.20+
                ├── grammar: tree-sitter-javascript
                └── grammar: tree-sitter-typescript

Lexical Index:  SQLite 3.38+ with FTS5
                ├── Tokenizer: porter unicode61
                └── Page cache: 4MB

Embeddings:     ONNX Runtime 1.17+
                └── Model: all-MiniLM-L6-v2 (ONNX export)

Storage:        SQLite 3.38+ (single .db file per project)
                ├── WAL journal mode
                ├── int8 BLOB embeddings
                └── FTS5 virtual table

API:            FastAPI 0.110+
                └── Uvicorn (ASGI server)

Optional LLM:   Ollama (deepseek-coder:1.3b or 6.7b-q4)
                llama.cpp (via subprocess)
                OpenAI API (gpt-4o-mini)

Parser Bridge:  Node.js 18+ (fallback only, via subprocess)
                └── @babel/parser 7+
```

---

## 20.2 Safest Architecture Choice

The safest architecture is the one chosen: **Monolithic Python backend + SQLite storage**.

**Why it's safe**:
1. **Zero infrastructure**: No Docker, no Redis, no external DBs, no network deps
2. **Single file storage**: Everything in one `.db` file per project — easy to backup, debug, delete
3. **Testable in isolation**: Every module can be unit tested without mocks
4. **No version compatibility hell**: SQLite is stable, Tree-sitter has excellent Python bindings
5. **Fallback paths at every layer**: Babel fallback if Tree-sitter fails; retrieval-only if LLM unavailable

**Avoid**:
- Microservices architecture (overkill, adds latency + complexity)
- Redis/Memcached (memory cost, external process)
- Chroma/FAISS/Weaviate (external vector DBs, too heavy)
- Full transformer models (BERT, RoBERTa) for embeddings

---

## 20.3 Most Memory-Efficient Design

| Decision | Memory Impact |
|----------|--------------|
| int8 quantized embeddings | −75% vs float32 |
| Lazy loading of BLOBs | Only candidates in RAM (not full index) |
| SQLite page cache limit (4MB) | Bounded buffer pool |
| Discard AST immediately after parsing | −100% AST memory |
| Singleton ONNX model | Shared across all projects |
| BFS frontier-only graph traversal | ~4KB vs full in-memory graph |
| LRU cache for embeddings (1MB cap) | Bounded cache growth |
| Chunk text truncated at 4096 chars | Bounded text storage |

**Memory champion features**:
1. **No in-memory full graph**: SQLite adjacency list + on-demand traversal
2. **No full embedding matrix in RAM**: Load only candidates (50 × 384B = 19KB)
3. **No AST storage**: Tree-sitter AST freed immediately after extraction

---

## 20.4 Recommended Parser

**Primary**: `tree-sitter` with JavaScript + TypeScript grammars

**Reasons**:
- Handles incomplete/malformed code gracefully (error recovery built-in)
- Single-pass extraction in C (fast + low memory)
- Actively maintained, React-specific node types supported
- Works offline, zero network calls
- Consistent parse tree across JS dialects

**Fallback**: `@babel/parser` (via Node.js subprocess)

**Reasons**:
- Handles complex JSX/TSX that confuses Tree-sitter
- Babel is the industry standard React parser
- Subprocess isolation = crash in parser doesn't crash Python server

**Do NOT use**:
- Regex-only parsing (too fragile)
- Acorn (less feature-rich than Babel for modern JSX)
- esprima (stale, doesn't support modern syntax)

---

## 20.5 Recommended Embedding Model

**Primary**: `all-MiniLM-L6-v2` (ONNX)
- Source: `sentence-transformers/all-MiniLM-L6-v2`
- Size: 22MB ONNX, ~30MB loaded
- Dimensions: 384
- Speed: ~5ms per batch of 16 on CPU
- Quality: 87.5 on STSB benchmark — excellent for semantic similarity

**Alternative (smaller)**: `paraphrase-MiniLM-L3-v2`
- Size: 17MB
- Speed: ~3ms/batch
- Quality: ~5% lower
- Use when RAM is extremely constrained

**Alternative (better quality)**: `all-mpnet-base-v2`
- Size: 420MB (too large for this system's spirit, but good for accuracy-first mode)
- Only consider if users have >4GB RAM and prioritize accuracy over size

**Do NOT use**:
- OpenAI `text-embedding-ada-002` as primary (requires network, costs money)
- `bert-base-uncased` (400MB, overkill)
- Any model >100MB ONNX without explicit user opt-in

---

## 20.6 Recommended Storage Format

**Primary**: SQLite 3.38+ with FTS5

**Schema decisions**:
1. One `.db` file per indexed project (not one global DB)
2. Embeddings stored as int8 BLOBs in `embeddings` table
3. Graph stored as edge rows in `graph_edges` table (not adjacency lists in RAM)
4. FTS5 virtual table for lexical index (not Whoosh, not Elasticsearch)
5. WAL journal mode (concurrent read + write)

**Why not**:
- JSON files: No indexing, no BM25, slow for large projects
- Parquet/Arrow: Read-only, no FTS5, overkill
- LevelDB/RocksDB: No SQL, harder to query, external dependency
- PostgreSQL: External process, heavy, not portable

**Optional enhancement**: `sqlite-zstd` extension for 2–4× additional compression of BLOBs and text. Install: `pip install sqlite-zstd`.

---

## 20.7 Recommended Retrieval Strategy

**For this system, the final recommended strategy is**:

```
Hybrid Retrieval with Intent-Adaptive Weights
─────────────────────────────────────────────

Default weights (when intent is uncertain):
  Lexical:  0.35
  Semantic: 0.40
  Graph:    0.25

Symbol lookup:
  Lexical:  0.70  ← Heavy lexical: exact identifier match
  Semantic: 0.20
  Graph:    0.10

Architecture/understanding:
  Lexical:  0.20
  Semantic: 0.30
  Graph:    0.50  ← Heavy graph: structural relationships

Route tracing / impact:
  Lexical:  0.20
  Semantic: 0.20
  Graph:    0.60  ← Graph-dominant: structural traversal

Debugging:
  Lexical:  0.40
  Semantic: 0.40  ← Balanced: need both exact + conceptual
  Graph:    0.20
```

**Reranking**: Disable by default (adds 100ms). Enable via config for users who prioritize accuracy.

---

## 20.8 Final Summary Table

| Category | Recommendation | Alternative |
|----------|---------------|-----------|
| Language | Python 3.11+ | — |
| Parser | tree-sitter + Babel fallback | Babel-only |
| Embedding model | all-MiniLM-L6-v2 ONNX | paraphrase-MiniLM-L3 |
| Quantization | int8 scalar | float16 |
| Storage | SQLite + FTS5 | — |
| Graph | SQLite adjacency | — |
| API | FastAPI + uvicorn | Flask |
| Local LLM | Ollama | llama.cpp |
| Cloud LLM | OpenAI gpt-4o-mini | Anthropic Claude |
| Plugin system | Hook-based Python ABC | — |
| Retrieval | Hybrid (lex+sem+graph) | Semantic-only |
| Intent | Rule-based + embedding fallback | Rules-only |

---

## 20.9 Production Checklist

Before shipping to users:

- [ ] All extractors tested with edge-case React patterns (memo, forwardRef, HOCs)
- [ ] RAM benchmark passes on real 50-file project: <20MB
- [ ] E2E latency benchmark: <50ms per query
- [ ] FTS5 query never returns 0 results (fallback prefix matching)
- [ ] Incremental reindex tested with file add/delete/modify
- [ ] ONNX model download with retry + integrity check
- [ ] SQLite WAL mode verified (no corruption on process kill)
- [ ] Graceful degradation: works without ONNX (lexical-only mode)
- [ ] Graceful degradation: works without LLM (retrieval-only mode)
- [ ] API error handling: 400 for bad project_id, 503 for indexing in progress
- [ ] Security: project path validation (no path traversal attacks)
- [ ] Documentation: README, API docs, config reference
