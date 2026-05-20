# 19 — PERFORMANCE STRATEGY

## 19.1 Indexing Speed Optimization

### Goal: <10 seconds for a 50-file project

**Breakdown per file** (target 200ms/file):

| Step | Target Time |
|------|------------|
| File read | 1ms |
| Tree-sitter parse | 3ms |
| Metadata extraction | 2ms |
| Chunking | 2ms |
| FTS5 insert | 5ms |
| Embedding (batch) | 10ms (amortized) |
| Graph edges insert | 2ms |
| **Total** | **~25ms/file** |

50 files × 25ms = **1.25 seconds** — well within budget.

---

### Optimization Techniques

#### 1. Batch Database Writes

```python
# SLOW: One transaction per chunk
for chunk in chunks:
    db.execute("INSERT INTO chunks VALUES (?)", chunk)
    db.commit()  # ← Disk write per commit

# FAST: Single transaction for all chunks
with db:  # Auto-commit at end
    db.executemany("INSERT INTO chunks VALUES (?)", chunk_values)
```

**Speedup**: 10–50× for insert-heavy operations.

#### 2. Parallel File Parsing

```python
# Use ProcessPoolExecutor for CPU-bound Tree-sitter parsing
with ProcessPoolExecutor(max_workers=4) as pool:
    parse_results = list(pool.map(parse_file, file_list))
```

**Speedup**: ~3× on 4-core machine.

#### 3. Embedding Batching

```python
# SLOW: Encode one chunk at a time
for chunk in chunks:
    embedding = encoder.encode([chunk.text])  # 1 ONNX forward pass

# FAST: Encode 16 chunks per ONNX forward pass
for i in range(0, len(chunks), 16):
    batch = chunks[i:i+16]
    embeddings = encoder.encode([c.text for c in batch])  # 1 ONNX forward pass
```

**Speedup**: ~12× for embedding generation.

#### 4. WAL Journal Mode

```sql
PRAGMA journal_mode=WAL;
-- WAL allows concurrent reads during writes
-- Critical for watch mode (reads while writing)
```

#### 5. Prepared Statements

```python
# Cache prepared statements for repeated queries
stmt = db.execute("SELECT ? FROM chunks WHERE id=?")  # compiled once
# Reuse stmt.execute([id]) for each chunk
```

---

## 19.2 Retrieval Latency Optimization

### Goal: <50ms end-to-end (no LLM)

**Latency budget breakdown**:

| Component | Budget |
|-----------|--------|
| Intent classification | 2ms |
| Query expansion | 0.5ms |
| Lexical search (FTS5) | 10ms |
| Semantic retrieval | 15ms |
| Graph retrieval | 10ms |
| Score fusion | 1ms |
| Context assembly | 8ms |
| JSON serialization | 3ms |
| **Total** | **~50ms** |

---

### Optimization Techniques

#### 1. Intent Classification Shortcut

```python
# Rules are O(1) — always try first
intent = classify_by_rules(query)  # 0.5ms
if intent is None:
    intent = embedding_classify(query)  # 5ms fallback
```

#### 2. Lexical-Semantic Cascade

```python
# Run semantic ONLY on top-50 lexical candidates (not full DB)
lex_candidates = lexical_search(query, top_k=50)  # 10ms
sem_scores = semantic_rescore(query, [c.id for c in lex_candidates])  # 15ms
# vs. full semantic scan: would be ~30ms
```

#### 3. SQLite Query Optimization

```sql
-- Use covering index for chunk fetch
CREATE INDEX idx_chunks_cover ON chunks(id, name, file_path, chunk_type, start_line, end_line);
-- Avoids table row fetch for metadata-only queries
```

#### 4. Async Parallel Retrieval

```python
async def retrieve_parallel(query, strategy):
    async with asyncio.TaskGroup() as tg:
        lex_task   = tg.create_task(lexical_retrieve(query))
        graph_task = tg.create_task(graph_retrieve(seeds))
    # sem_task runs sequentially after lex (needs candidates)
    sem_scores = await semantic_retrieve(query, lex_candidates)
```

**Speedup**: Lexical + Graph in parallel → saves ~10ms.

#### 5. Retrieval Result Cache

```python
def retrieve_cached(query: str, project_id: str) -> Optional[List[RankedChunk]]:
    query_hash = sha256(f"{query}:{project_id}".encode()).hexdigest()
    row = db.execute(
        "SELECT result_json FROM retrieval_cache WHERE query_hash=? AND created_at+ttl_seconds > ?",
        [query_hash, int(time.time())]
    ).fetchone()

    if row:
        return json.loads(row[0])  # <1ms cache hit!
    return None
```

Cache hit rate for repeated queries: typically 20–40% in interactive use.

---

## 19.3 Semantic Reranking Efficiency

### Without Cross-Encoder (Default)

Cosine similarity via NumPy on 50 candidates:
- 50 × 384 dot products = ~19,200 multiplications
- NumPy vectorized: ~0.1ms

```python
# Vectorized batch cosine (fastest)
query_vec = encoder.encode([query])[0]  # (384,)
candidate_matrix = load_embeddings_matrix(candidate_ids, db)  # (50, 384)
similarities = candidate_matrix @ query_vec  # (50,) — one matrix multiply
```

### With Cross-Encoder (Optional)

```
Cross-encoder reranking of top-20:
- ONNX inference: ~5ms per candidate
- 20 candidates: ~100ms
- Total: +100ms to end-to-end
```

Use only when result quality is critical and latency tolerance allows.

---

## 19.4 Caching Strategy

### Three Cache Layers

| Layer | What | Where | TTL |
|-------|------|-------|-----|
| **Query result cache** | Full ranked chunk list | SQLite | 60 min |
| **Embedding cache** | Query + chunk embeddings | RAM (LRU) | Session |
| **Graph cache** | Traversal results | RAM (LRU) | 5 min |

### Cache Key Design

```python
# Query cache key: normalize to handle similar queries
def normalize_query(q: str) -> str:
    q = q.lower().strip()
    q = re.sub(r'\s+', ' ', q)         # normalize whitespace
    q = re.sub(r'[?!.]$', '', q)       # remove trailing punctuation
    return q

cache_key = sha256(f"{normalize_query(query)}:{project_id}:{intent.value}".encode()).hexdigest()
```

---

## 19.5 Concurrency Model

### API Server: Async I/O

FastAPI + asyncio for the HTTP layer:
- All database reads: `aiosqlite` (async SQLite)
- All ONNX inference: thread pool executor (CPU-bound)
- All graph traversals: async generator pattern

```python
@app.post("/query")
async def query_endpoint(req: QueryRequest):
    # Non-blocking async execution
    result = await retrieval_pipeline.retrieve(
        query=req.query,
        project_id=req.project_id
    )
    return result
```

### ONNX Inference: Thread Pool

ONNX Runtime is not async-native but is thread-safe:

```python
# Wrap CPU-bound ONNX inference in thread pool
loop = asyncio.get_event_loop()
embedding = await loop.run_in_executor(
    executor,  # ThreadPoolExecutor(max_workers=2)
    encoder.encode,
    texts
)
```

### Database: Connection per Coroutine

```python
# Each async coroutine gets its own connection (no locking issues with WAL)
async def get_db(project_id: str) -> aiosqlite.Connection:
    db = await aiosqlite.connect(get_db_path(project_id))
    await db.execute("PRAGMA journal_mode=WAL")
    return db
```

### Concurrent Query Handling

```
Client 1: query "where is auth?"     → ONNX encode → FTS5 → graph → response
Client 2: query "routing flow"        → FTS5 → ONNX → graph → response
Client 3: index new file              → parse → embed → write → done
```

All three run concurrently via asyncio. No blocking.

---

## 19.6 Indexing Pipeline Throughput

For incremental re-indexing during watch mode:

**Single-file reindex target**: <500ms

| Step | Target |
|------|--------|
| File read | 1ms |
| Parse | 5ms |
| Chunk | 3ms |
| Delete old data | 5ms |
| FTS5 re-insert | 10ms |
| Embed (batch=1) | 30ms |
| Graph update | 20ms |
| **Total** | **~74ms** |

With 500ms debounce on file save, this feels instantaneous to the developer.

---

## 19.7 Benchmark Plan

```python
# benchmarks/bench_indexing.py

def benchmark_indexing():
    project = load_fixture("sample_50_file_project")
    start = time.perf_counter()
    pipeline.index(project)
    elapsed = time.perf_counter() - start
    print(f"Indexing 50 files: {elapsed:.2f}s (target: <10s)")

# benchmarks/bench_retrieval.py

BENCHMARK_QUERIES = [
    ("Where is authentication handled?", Intent.ARCHITECTURE),
    ("Find all uses of useTheme", Intent.SYMBOL_LOOKUP),
    ("Why does Dashboard rerender?", Intent.RERENDER_ANALYSIS),
    ("How does routing flow from App?", Intent.ROUTE_TRACING),
]

def benchmark_retrieval():
    for query, intent in BENCHMARK_QUERIES:
        start = time.perf_counter()
        results = pipeline.retrieve(query, project_id)
        elapsed = (time.perf_counter() - start) * 1000
        print(f"{intent.value}: {elapsed:.1f}ms, {len(results)} results (target: <50ms)")

# benchmarks/bench_memory.py

def benchmark_memory():
    import tracemalloc
    tracemalloc.start()
    pipeline.retrieve("where is auth?", project_id)
    current, peak = tracemalloc.get_traced_memory()
    print(f"Peak RAM during query: {peak / 1024 / 1024:.1f}MB (target: <20MB)")
```
