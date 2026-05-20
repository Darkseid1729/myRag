# 18 — MVP ROADMAP

## Phase Overview

```
Phase 1 (Week 1-2):   Core Foundation — Parse + Index + Lexical Search
Phase 2 (Week 3-4):   Semantic Layer — Embeddings + Hybrid Retrieval
Phase 3 (Week 5-6):   Intelligence Layer — Graph + Intent + Context
Phase 4 (Week 7-8):   Polish + LLM + Extensibility
```

---

## Phase 1: Core Foundation

**Goal**: Get a working indexer and lexical search in 2 weeks.

### Features

- [x] File Scanner (JS/JSX/TS/TSX discovery)
- [x] File Classifier (component/hook/route/util)
- [x] Tree-sitter AST Parser (single-pass, no storage)
- [x] Metadata Extractor (components, hooks, functions, imports)
- [x] Basic Chunker (function + component level)
- [x] SQLite DB Setup (schema migration system)
- [x] FTS5 Lexical Indexer
- [x] Basic Lexical Search (BM25, no reranking)
- [x] FastAPI server (POST /index, POST /query)
- [x] CLI: `myrag index` and `myrag ask`

### Deliverable

```
myrag index ./my-project
myrag ask "where is handleLogin defined?"
→ Returns: 3 relevant chunks with file + line numbers
```

### Implementation Priority

| Task | Priority | Complexity |
|------|----------|-----------|
| SQLite schema + migrations | P0 | Low |
| Tree-sitter parser | P0 | Medium |
| FTS5 indexer | P0 | Low |
| FastAPI server skeleton | P0 | Low |
| File scanner | P1 | Low |
| Chunker (basic) | P1 | Medium |
| CLI interface | P1 | Low |

### Risks

- Tree-sitter JSX grammar edge cases (nested JSX expressions)
- CamelCase tokenization must be done BEFORE FTS5 insertion (FTS5 doesn't expose hooks)

### Testing Strategy

- Unit test each extractor with fixture files
- Integration test: index a real 10-file React project, verify all chunks created
- Benchmark: indexing speed should be <5 seconds for 50 files

---

## Phase 2: Semantic Layer

**Goal**: Add ONNX embedding + hybrid retrieval. 2 weeks.

### Features

- [x] ONNX model loader + singleton
- [x] int8 quantizer (float32 → int8)
- [x] Embedding indexer (batch encode + store as BLOBs)
- [x] Semantic retriever (cosine similarity over candidates)
- [x] Embedding LRU cache
- [x] Score fusion (lexical + semantic)
- [x] Improved chunking (semantic boundaries via AST ranges)
- [x] Normalized BM25 scoring

### Deliverable

```
myrag ask "how does authentication work?"
→ Returns: top-5 semantically relevant chunks (not just keyword matches)
→ "Where should I add dark mode?" → finds ThemeContext without exact keyword
```

### Implementation Priority

| Task | Priority | Complexity |
|------|----------|-----------|
| ONNX model download + caching | P0 | Low |
| Batch embedding generation | P0 | Medium |
| int8 quantization | P0 | Low |
| Cosine similarity retrieval | P0 | Low |
| Score fusion | P0 | Medium |
| Embedding LRU cache | P1 | Low |
| Benchmark embedding speed | P1 | Low |

### Risks

- ONNX model first-download UX (22MB, needs progress indicator)
- Quantization introduces small errors — verify retrieval quality doesn't degrade

### Testing Strategy

- Test with 20 hand-crafted queries, measure precision@5
- Semantic search should outperform lexical for conceptual queries
- A/B test: pure lexical vs hybrid on same query set

---

## Phase 3: Intelligence Layer

**Goal**: Add graph engine, intent routing, and context builder. 2 weeks.

### Features

- [x] Graph builder (import + call + hook + render + context edges)
- [x] Graph traversal (BFS/DFS with depth control)
- [x] Graph-aware scoring (proximity-based)
- [x] Impact analyzer + dependency tracer
- [x] Intent router (rule-based + embedding fallback)
- [x] Query expander
- [x] Strategy selector (per-intent retrieval weights)
- [x] Context builder with token budget
- [x] Rule-based chunk summarizer
- [x] Dependency summary generator

### Deliverable

```
myrag ask "why does Dashboard rerender?"
→ Returns: state dependency graph + component + hook + useEffect chunks
→ System identifies useState dependencies without exact keyword match

myrag ask "which files affect the /dashboard route?"
→ Returns: full route tree via graph traversal
```

### Implementation Priority

| Task | Priority | Complexity |
|------|----------|-----------|
| Graph builder (import edges) | P0 | Medium |
| Graph traversal (BFS) | P0 | Medium |
| Intent classifier (rules) | P0 | Low |
| Strategy selector | P0 | Low |
| Context builder | P0 | Medium |
| Hook/render/state edges | P1 | High |
| Embedding intent fallback | P1 | Low |
| Impact analyzer | P2 | Medium |

### Risks

- Graph edges can be noisy (dynamic imports, re-exports)
- Intent classification ambiguity for compound queries
- Graph scoring can amplify errors from earlier retrieval stages

### Testing Strategy

- Test route tracing with a known project structure, verify all files found
- Test impact analysis: change useAuth, verify 8+ affected components found
- Measure E2E latency: target <50ms without LLM

---

## Phase 4: Polish, LLM, Extensibility

**Goal**: Production-ready release with LLM integration and plugins. 2 weeks.

### Features

- [x] Ollama integration
- [x] llama.cpp integration
- [x] OpenAI API integration
- [x] Prompt builder (evidence pack → LLM prompt)
- [x] Streaming responses
- [x] Plugin system (hook-based)
- [x] TypeScript plugin
- [x] Incremental indexing (change detection)
- [x] Live file watching (watchdog)
- [x] Web UI (minimal HTML interface)
- [x] VSCode extension scaffold
- [x] CLI `myrag watch`, `myrag graph`, `myrag list`
- [x] Retrieval result cache (SQLite-backed)
- [x] Cross-encoder reranker (optional)
- [x] Performance benchmarks
- [x] Full README + documentation

### Deliverable

```
Full working system:
- myrag index ./project  (completes in <10 seconds)
- myrag ask "..."        (<50ms retrieval, ~500ms with Ollama)
- myrag watch ./project  (auto-reindexes on file save)
- Web UI at localhost:8420
- VSCode extension installable
```

### Implementation Priority

| Task | Priority | Complexity |
|------|----------|-----------|
| Ollama client | P0 | Low |
| Prompt builder | P0 | Medium |
| Incremental indexing | P0 | Medium |
| Result cache | P1 | Low |
| Plugin system | P1 | Medium |
| Web UI | P1 | Medium |
| llama.cpp client | P2 | Medium |
| Cross-encoder reranker | P2 | High |
| VSCode extension | P2 | High |
| Live file watching | P2 | Medium |

### Risks

- LLM response quality varies dramatically by model
- VSCode extension API changes between versions
- Cross-encoder may exceed RAM budget if loaded alongside ONNX encoder

---

## Overall Risk Matrix

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|-----------|
| Tree-sitter fails on complex JSX | Medium | High | Babel fallback |
| ONNX model quality insufficient | Low | High | Allow model swap via config |
| >20MB RAM per project | Medium | High | Lazy loading + benchmarks |
| Graph edges too noisy | Medium | Medium | Weight filtering, manual edge review |
| Indexing too slow for large projects | Low | Medium | Async pipeline, progress reporting |
| LLM generates wrong answers | High | Low | Retrieval-only mode always available |

---

## Success Metrics

| Metric | Target |
|--------|--------|
| Indexing time (50 files) | <10 seconds |
| Retrieval latency (no LLM) | <50ms |
| Retrieval latency (with Ollama) | <800ms |
| Peak RAM (per project) | <20MB |
| Precision@5 on test queries | >80% |
| Symbol lookup accuracy | >95% |
| Route tracing completeness | >90% |
