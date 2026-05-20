# 15 — MEMORY OPTIMIZATION PLAN

## 15.1 RAM Budget Allocation (20MB Target)

```
Total RAM Budget: 20MB per indexed project
═══════════════════════════════════════════════════════

ONNX Embedding Model (shared, not per-project):
├── all-MiniLM-L6-v2 ONNX runtime:     ~30MB  ← EXCEPTION: shared singleton
└── (amortized across N projects)

Per-Project RAM Budget:
├── SQLite page cache:                   4.0MB
│     PRAGMA cache_size=-4096
│     Shared page pool across all queries
│
├── Embedding working set:               3.0MB
│     Max 200 chunks × 384 bytes = 76KB stored
│     LRU cache for recently accessed:  ~1MB
│     Query encoding buffer:            ~100KB
│     Batch decode buffer (16 chunks):  ~50KB
│
├── Graph traversal working set:         1.0MB
│     Active BFS frontier:              ~4KB
│     Graph edge cache (recent):        ~500KB
│     Traversal result buffer:          ~100KB
│
├── Lexical search working set:          1.0MB
│     FTS5 query buffer:                ~50KB
│     Result set (50 rows):             ~200KB
│     Snippet generation buffer:        ~100KB
│
├── Intent router:                       0.5MB
│     Compiled regex patterns:          ~50KB
│     Exemplar embeddings:              ~8KB
│     Strategy configs:                 ~1KB
│
├── Context builder:                     1.5MB
│     Retrieved chunk texts (top-10):   ~500KB
│     Summary buffers:                  ~200KB
│     Evidence pack assembly:           ~500KB
│
├── API request/response:                2.0MB
│     Request parsing:                  ~100KB
│     JSON response serialization:      ~500KB
│     Async task buffers:               ~1MB
│
├── Python runtime overhead:             4.0MB
│     Interpreter base:                 ~3MB
│     Imported modules:                 ~1MB
│
└── OS/misc overhead:                    3.0MB
                                      ───────
TOTAL (per project):                   ~20MB ✓
(Plus 30MB shared ONNX model)
```

---

## 15.2 Lazy Loading Strategy

**Principle**: Load data only when the current query needs it.

### Embeddings: Lazy BLOB Loading

```python
# WRONG: Load all embeddings at startup
embeddings = db.execute("SELECT * FROM embeddings").fetchall()  # 76KB always in RAM

# RIGHT: Load only what each query needs
def get_embeddings_for_candidates(candidate_ids: List[str]) -> Dict[str, np.ndarray]:
    placeholders = ','.join('?' * len(candidate_ids))
    rows = db.execute(
        f"SELECT chunk_id, vector, scale FROM embeddings WHERE chunk_id IN ({placeholders})",
        candidate_ids
    ).fetchall()
    return {cid: dequantize(blob, scale) for cid, blob, scale in rows}
```

### Graph: Lazy Edge Loading

```python
# WRONG: Build full adjacency list in RAM
graph = build_full_graph(db)  # All edges in RAM

# RIGHT: Query edges on demand during traversal
def get_neighbors(node_id: str, edge_types: List[str]) -> List[str]:
    return db.execute(
        "SELECT to_id FROM graph_edges WHERE from_id=? AND edge_type IN (...)",
        [node_id] + edge_types
    ).fetchall()
```

### Chunks: Lazy Text Loading

Chunk metadata (id, type, name, lines) is always loaded. Full text is loaded on demand:

```python
# Phase 1: Get ranked chunk IDs (no text loaded)
ranked_ids = hybrid_retriever.retrieve_ids(query)  # Returns only IDs + scores

# Phase 2: Load texts only for top-K selected chunks
top_ids = ranked_ids[:10]
chunk_texts = db.execute(
    f"SELECT id, text FROM chunks WHERE id IN ({placeholders})", top_ids
).fetchall()
```

---

## 15.3 Embedding Compression Details

### Quantization Error Analysis

```
Original float32 vector: [-0.234, 0.567, -0.891, ...]
Scale: max(abs(v)) / 127 = 0.891 / 127 ≈ 0.00702

Quantized int8: [-33, 81, -127, ...]
Dequantized: [-0.232, 0.568, -0.891, ...]

Error: |original - dequantized| ≈ 0.002–0.005 per dimension
Cosine similarity error: ≈ 0.01–0.03 (negligible for ranking)
```

### Storage Comparison

| Format | Size per Vector | 200 Chunks Total |
|--------|----------------|-----------------|
| float32 | 1,536 bytes | 300KB |
| float16 | 768 bytes | 150KB |
| int8 | 384 bytes | 75KB ✓ |
| binary | 48 bytes | 9.4KB (too lossy) |

**Chosen**: int8 — 4× compression with minimal quality loss.

---

## 15.4 Graph Compression

Store edges in typed integer columns instead of JSON strings:

```sql
-- WASTEFUL approach:
graph_edges(from_id TEXT, to_id TEXT, metadata TEXT)
-- where metadata = '{"edge_type": "IMPORTS", "weight": 1.0}'
-- Per edge: 32 + 32 + 40 = 104 bytes

-- EFFICIENT approach:
graph_edges(from_id TEXT, to_id TEXT, edge_type INTEGER, weight REAL)
-- edge_type is enum stored as INTEGER (1-9)
-- Per edge: 32 + 32 + 4 + 8 = 76 bytes
-- Plus: indexed, faster query execution
```

---

## 15.5 Cache Eviction Strategy

### Embedding LRU Cache

```python
class EmbeddingLRUCache:
    def __init__(self, max_bytes: int = 1_000_000):  # 1MB max
        self.cache: OrderedDict[str, np.ndarray] = OrderedDict()
        self.current_bytes = 0
        self.max_bytes = max_bytes
        self.EMBEDDING_SIZE = 384 * 4  # float32 after dequantize

    def get(self, chunk_id: str) -> Optional[np.ndarray]:
        if chunk_id in self.cache:
            self.cache.move_to_end(chunk_id)  # Mark as recently used
            return self.cache[chunk_id]
        return None

    def put(self, chunk_id: str, embedding: np.ndarray):
        while self.current_bytes + self.EMBEDDING_SIZE > self.max_bytes:
            # Evict least recently used
            oldest_key, oldest_val = self.cache.popitem(last=False)
            self.current_bytes -= self.EMBEDDING_SIZE

        self.cache[chunk_id] = embedding
        self.current_bytes += self.EMBEDDING_SIZE
```

### Query Result Cache (SQLite-backed)

```sql
-- Evict stale cache entries
DELETE FROM retrieval_cache
WHERE created_at + ttl_seconds < strftime('%s', 'now');
```

Run eviction on each query (amortized cost).

---

## 15.6 Chunk Storage Optimization

| Technique | Applied To | Savings |
|-----------|-----------|---------|
| Truncate text at 4096 chars in `chunks.text` | All chunks | Variable |
| Strip comments before indexing in `fts_chunks` | FTS text | 20% |
| Only store normalized text in FTS (not original) | FTS table | 30% |
| Summary: max 200 chars | `summaries` table | 80% vs raw |
| Symbols: only top-20 per chunk | `symbols` table | Bounded |

---

## 15.7 Indexing Tradeoffs

| Trade-off | Choice | Rationale |
|-----------|--------|-----------|
| Persist full AST? | No | ASTs are 100–500KB each, 50 files = 5–25MB |
| Store full chunk text? | Yes, with limit | Needed for display and summarization |
| Pre-compute all embeddings? | Yes | One-time cost at index, zero cost at query |
| Index test files? | Optional | Adds noise, disable by default |
| Index `node_modules`? | Never | Infinite blackhole |
| Store raw import paths? | Resolved paths | Avoids resolution at query time |

---

## 15.8 Estimated Memory per Subsystem (Query Time)

```
Subsystem                    Peak RAM    Duration
─────────────────────────────────────────────────
Intent classification        60KB        <1ms
Query embedding (ONNX)       100KB       5ms
Lexical search (FTS5)        500KB       10ms
Candidate embedding load     200KB       5ms
Cosine similarity compute    100KB       3ms
Graph traversal              100KB       10ms
Score fusion                 50KB        1ms
Context assembly             500KB       5ms
JSON serialization           200KB       2ms
─────────────────────────────────────────────────
Peak simultaneous:           ~1.5MB      (overlapping buffers freed)
Sustained during response:   ~500KB
```

---

## 15.9 ONNX Model Memory (Shared Singleton)

The ONNX model is the largest consumer (~30MB), but it's:
1. Loaded **once** at server startup
2. **Shared** across all projects and queries
3. **Not counted** in per-project RAM budget
4. Fully offloaded to CPU ops (no GPU memory needed)

```python
# Singleton pattern in model_loader.py
_ENCODER_INSTANCE: Optional[ONNXEncoder] = None

def get_encoder() -> ONNXEncoder:
    global _ENCODER_INSTANCE
    if _ENCODER_INSTANCE is None:
        _ENCODER_INSTANCE = ONNXEncoder(MODEL_PATH)
    return _ENCODER_INSTANCE
```
