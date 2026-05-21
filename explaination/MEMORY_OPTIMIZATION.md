# Memory Optimization Guide

## Target

**≤ 20 MB RSS per indexed project** on a CPU-only machine.

---

## RAM Budget

| Subsystem | Budget | Actual (typical 50-file project) |
|-----------|--------|----------------------------------|
| SQLite page cache | 4 MB | ~2–4 MB |
| ONNX model (shared across projects) | 10 MB | ~22 MB¹ |
| Embedding LRU cache | 1 MB | ≤1 MB |
| Graph BFS working set | 0.5 MB | ≤0.5 MB |
| Active query buffers | 1 MB | ≤1 MB |
| Python + FastAPI overhead | 10 MB | ~10–15 MB |
| **Total per-project overhead** | **~7 MB** | **~5–7 MB** |

¹ The ONNX model is loaded once and shared across all projects in the same process. Its 22 MB RAM cost is amortised if multiple projects are served simultaneously.

---

## Strategy 1: int8 Embedding Quantization

**Location:** `src/embeddings/onnx_encoder.py`

### Problem
float32 embeddings of dimension 384:
```
384 × 4 bytes = 1,536 bytes per chunk
```
For 300 chunks × 50 files = 15,000 chunks:
```
15,000 × 1,536 = 23 MB just for embeddings
```

### Solution: Scalar Quantization

```python
# Encoding
scale = float(np.max(np.abs(vec)))
quantized = np.round(vec / scale * 127).astype(np.int8)
# Store: 384 bytes (int8) + 8 bytes (scale float64)

# Decoding (on demand)
dequantized = quantized.astype(np.float32) / 127.0 * scale
```

**Storage cost:** 384 + 8 = 392 bytes (vs 1,536 bytes float32)
**Compression ratio:** 3.9× smaller
**Cosine similarity error:** < 1% at 384 dimensions

### LRU Cache

Dequantization is CPU-intensive (dtype conversion + multiply). We cache recently used float32 vectors:

```python
class VectorLRUCache:
    max_bytes: int = 1_048_576  # 1 MB default
    _cache: OrderedDict[str, np.ndarray]
    _lock: threading.Lock

    def get_or_decode(chunk_id, blob, scale) -> np.ndarray:
        if chunk_id in cache:
            return cache[chunk_id]  # ~0 μs
        vec = decode(blob, scale)   # ~5 μs
        evict_if_needed()
        cache[chunk_id] = vec
        return vec
```

Configurable via `VECTOR_LRU_CACHE_KB` env var. Set to 0 to disable.

---

## Strategy 2: SQLite Page Cache Tuning

**Location:** `src/storage/db_manager.py`

### Configuration

```python
conn.execute(f"PRAGMA cache_size = -{page_cache_kb};")
```

Negative values set the cache in **kilobytes** (not pages).

| Setting | RAM Use | Query Speed |
|---------|---------|-------------|
| -512 (512 KB) | 0.5 MB | Slow (many disk reads) |
| **-4096 (4 MB)** | **4 MB** | **Good (default)** |
| -16384 (16 MB) | 16 MB | Excellent |

### Other PRAGMA Settings

```sql
PRAGMA journal_mode=WAL;       -- Concurrent reads + writes
PRAGMA synchronous=NORMAL;     -- Balanced safety vs. speed
PRAGMA temp_store=MEMORY;      -- Temp tables in RAM (not disk)
PRAGMA foreign_keys=ON;        -- Enforce FK constraints
```

WAL mode allows concurrent reads while a write transaction is open — critical for the web server serving multiple simultaneous queries.

---

## Strategy 3: On-Demand Semantic Search

### Problem

Running semantic search over all 15,000 embeddings takes ~75 ms (dot product batches on CPU).

### Solution: FTS5 Pre-filtering

```
lexical_search(query) → top-50 candidates (2 ms via FTS5 index)
semantic_search(query, candidate_ids=top50) → cosine over 50 vectors (0.5 ms)
```

Semantic search runs over **at most 50 vectors** (configurable via `fts_candidate_pool`), not over all embeddings.

**Full scan only when:** FTS5 returns 0 results (fallback mode, capped at 500 vectors).

---

## Strategy 4: Lazy Model Loading

**Location:** `src/embeddings/onnx_encoder.py`

The ONNX model is **not** loaded on import. It loads on first call to `encode()`:

```python
class ONNXEncoder:
    _session: ort.InferenceSession | None = None  # None until first use

    @property
    def session(self):
        if not self._session:
            self._session = ort.InferenceSession(model_path)
        return self._session
```

For the CLI `myrag list` command, no model is ever loaded. For `myrag index`, the model loads once and stays warm for all subsequent queries in the same process.

---

## Strategy 5: BFS Frontier Cap

**Location:** `src/retriever/hybrid_retriever.py`

```python
max_frontier = cfg["memory"]["graph_bfs_frontier"]  # default: 512

# BFS frontier is capped at each depth level:
frontier = next_frontier[:max_frontier]
```

Without this cap, a densely connected project (e.g., every component imports a shared util) could expand the BFS frontier to thousands of nodes per depth level, consuming megabytes of working memory.

With cap=512 and depth=4: maximum 512 × 4 = 2,048 DB reads, bounded memory.

---

## Strategy 6: Single Commit Per Index Run

Committing each chunk to SQLite separately is ~100× slower than a single commit at the end:

```python
# Bad (1 commit per chunk):
for chunk in chunks:
    db.execute(INSERT_CHUNK, ...)
    db.commit()  # ← expensive fsync per chunk

# Good (1 commit for the entire file):
for chunk in chunks:
    db.execute(INSERT_CHUNK, ...)
db.commit()  # ← single fsync at end
```

This is implemented in `indexing_pipeline.py` where `db.commit()` is called once at the very end after all chunks and edges are written.

---

## Strategy 7: Chunk-Level Granularity

We never store entire file contents. Only extracted code chunks (functions, components, hooks, import blocks) are stored. This means:

- A 200-line component file → 3–5 chunks (each 20–80 lines)
- A 500-line utils file → 8–15 chunks
- Total text stored is ~30–50% of the original source size

---

## Measuring Memory Usage

```bash
# Real-time RAM during indexing
myrag index /path/to/project

# The bench runner reports RSS at each stage
python benchmarks/run_bench.py /path/to/project "useAuth"
```

Or via the API:
```bash
curl http://localhost:8000/stats
# → {"rss_mb": 18.4, "projects": 1, "version": "1.0.0"}
```

---

## Tuning for Tight Memory Environments

If you need to run under 15 MB:

```env
# .env
SQLITE_PAGE_CACHE_KB=1024       # Reduce to 1 MB
VECTOR_LRU_CACHE_KB=256         # Reduce to 256 KB
```

```yaml
# config/default.yaml
memory:
  graph_bfs_frontier: 128       # Smaller BFS frontier
retrieval:
  fts_candidate_pool: 20        # Fewer candidates for semantic search
indexer:
  max_chunk_tokens: 150         # Smaller chunks = smaller embeddings in cache
```

```env
LLM_PROVIDER=none               # Skip LLM (no prompt buffer)
```

---

## When to Expect Higher RAM

| Situation | Extra RAM | Cause |
|-----------|-----------|-------|
| First index (large project >100 files) | +5 MB | Python object allocation during scan |
| Cross-encoder reranker enabled | +67 MB | CrossEncoder model weight |
| Graph BFS on a highly connected repo | +2 MB | Large frontier dict |
| Many simultaneous API requests | +2 MB per req | Per-request stack frames |
