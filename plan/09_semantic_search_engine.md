# 09 — SEMANTIC SEARCH ENGINE

## 9.1 Why Not a Full Vector Database?

Full vector databases (Pinecone, Weaviate, Chroma, FAISS) are designed for:
- Millions of vectors
- Multi-tenant retrieval
- Persistent, sharded storage
- Approximate Nearest Neighbor at scale

For our use case (~200 chunks per project):
- FAISS would allocate 200 × 384 × 4 = **300KB float32** and load it ALL into RAM
- We would still need SQLite for everything else
- FAISS adds a ~10MB C++ dependency

**Alternative**: Store embeddings as SQLite BLOBs (int8 quantized). Load only candidates (post-lexical filter). Compute cosine similarity in NumPy.

Result: **~75KB** for full project embeddings vs 300KB, zero extra dependencies.

---

## 9.2 Embedding Model Selection

| Model | Size | Dim | Speed | Quality |
|-------|------|-----|-------|---------|
| `all-MiniLM-L6-v2` (ONNX) | 22MB | 384 | ~5ms | ★★★★☆ |
| `paraphrase-MiniLM-L3-v2` | 17MB | 384 | ~3ms | ★★★☆☆ |
| `all-mpnet-base-v2` (ONNX) | 420MB | 768 | ~20ms | ★★★★★ |
| `text-embedding-3-small` (OpenAI) | API | 1536 | ~100ms+network | ★★★★★ |

**Recommended**: `all-MiniLM-L6-v2` via ONNX Runtime. Best balance of size, speed, and quality.

---

## 9.3 ONNX Inference Pipeline

```python
# Pseudocode: onnx_encoder.py

class ONNXEncoder:
    def __init__(self, model_path: str):
        # Load model once — 22MB into RAM (~30MB with ONNX RT overhead)
        self.session = ort.InferenceSession(
            model_path,
            providers=['CPUExecutionProvider']
        )
        self.tokenizer = AutoTokenizer.from_pretrained(model_path)

    def encode(self, texts: List[str], batch_size: int = 16) -> np.ndarray:
        all_embeddings = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i:i+batch_size]

            # Tokenize batch
            encoded = self.tokenizer(
                batch,
                padding=True,
                truncation=True,
                max_length=256,    # Code chunks: 256 tokens sufficient
                return_tensors='np'
            )

            # ONNX inference
            outputs = self.session.run(
                None,
                {
                    'input_ids': encoded['input_ids'],
                    'attention_mask': encoded['attention_mask']
                }
            )

            # Mean pooling over token embeddings
            token_embeddings = outputs[0]  # (batch, seq_len, 384)
            attention_mask = encoded['attention_mask']
            embeddings = mean_pool(token_embeddings, attention_mask)

            # L2 normalize
            embeddings = embeddings / np.linalg.norm(embeddings, axis=1, keepdims=True)
            all_embeddings.append(embeddings)

        return np.vstack(all_embeddings)  # (N, 384) float32
```

---

## 9.4 Embedding Quantization (float32 → int8)

```python
# Pseudocode: quantizer.py

def quantize_to_int8(vector: np.ndarray) -> Tuple[bytes, float]:
    """
    Quantize float32 vector to int8.
    Returns (quantized_bytes, scale_factor)
    """
    scale = np.max(np.abs(vector)) / 127.0
    if scale == 0:
        return bytes(len(vector)), 1.0

    quantized = np.round(vector / scale).astype(np.int8)
    return quantized.tobytes(), float(scale)

def dequantize_from_int8(blob: bytes, scale: float) -> np.ndarray:
    """Reconstruct approximate float32 vector from int8 bytes"""
    quantized = np.frombuffer(blob, dtype=np.int8).astype(np.float32)
    return quantized * scale
```

**Memory savings**:
- float32: 384 dims × 4 bytes = 1,536 bytes
- int8: 384 dims × 1 byte = 384 bytes
- **Savings: 75%**

**Quality loss**: Cosine similarity error ≈ 0.01–0.03. Acceptable for ranking purposes.

---

## 9.5 Embedding Storage Schema

```sql
CREATE TABLE embeddings (
    chunk_id TEXT PRIMARY KEY,
    vector   BLOB NOT NULL,    -- 384 bytes (int8 quantized)
    scale    REAL NOT NULL,    -- dequantization scale
    model_id TEXT NOT NULL     -- "all-MiniLM-L6-v2-int8"
);
```

For 200 chunks:
- 200 × 384 bytes = **76.8KB** total embedding storage
- Fits on single SQLite page (4KB pages × 20 = 80KB)

---

## 9.6 Semantic Retrieval Algorithm

**Two-stage approach**: Filter first, then compute similarity.

### Stage 1: Candidate Filtering (Lexical Pre-filter)
```python
# Get ~50 candidates from lexical search first
lexical_candidates = lexical_retriever.search(query, top_k=50)
candidate_ids = [c.chunk_id for c in lexical_candidates]
```

### Stage 2: Semantic Re-ranking of Candidates
```python
def semantic_rerank(
    query: str,
    candidate_ids: List[str],
    db: sqlite3.Connection,
    top_k: int = 10
) -> List[SemanticResult]:

    # Encode query
    query_vec = encoder.encode([query])[0]  # (384,) float32

    # Load ONLY candidate embeddings from SQLite
    placeholders = ','.join('?' * len(candidate_ids))
    rows = db.execute(
        f"SELECT chunk_id, vector, scale FROM embeddings WHERE chunk_id IN ({placeholders})",
        candidate_ids
    ).fetchall()

    # Compute cosine similarities in batch
    results = []
    for chunk_id, blob, scale in rows:
        chunk_vec = dequantize_from_int8(blob, scale)  # (384,) float32
        similarity = np.dot(query_vec, chunk_vec)       # Already L2-normalized
        results.append(SemanticResult(chunk_id=chunk_id, score=float(similarity)))

    # Sort by score descending
    results.sort(key=lambda r: r.score, reverse=True)
    return results[:top_k]
```

**Memory**: Only `candidate_ids` (≤50) embeddings loaded into RAM. Peak: ~50 × 384B = 19.2KB.

---

## 9.7 Pure Semantic Search (No Pre-filter)

For intent types where lexical search would miss results (e.g., conceptual queries):

```python
def full_semantic_search(query: str, project_id: str, top_k: int = 10) -> List[SemanticResult]:
    query_vec = encoder.encode([query])[0]  # (384,)

    # Load ALL embeddings (streaming, not all at once in practice)
    # For 200 chunks: 200 × 384 = 76KB — acceptable to load fully
    rows = db.execute("SELECT chunk_id, vector, scale FROM embeddings").fetchall()

    similarities = []
    for chunk_id, blob, scale in rows:
        vec = dequantize_from_int8(blob, scale)
        sim = np.dot(query_vec, vec)
        similarities.append((chunk_id, sim))

    similarities.sort(key=lambda x: x[1], reverse=True)
    return [SemanticResult(chunk_id=cid, score=s) for cid, s in similarities[:top_k]]
```

For 200 chunks: total in-memory at peak = **76KB** embeddings + **384B** query vector. Trivially within budget.

---

## 9.8 Approximate Similarity Search

For projects with >500 chunks, a simple **LSH (Locality Sensitive Hashing)** bucket index can be used for O(1) approximate lookup:

```python
# Pre-compute: hash each embedding into L buckets
# At query time: only compare query against chunks in same bucket

class LSHIndex:
    def __init__(self, n_bits: int = 8, n_tables: int = 4):
        self.planes = np.random.randn(n_tables, n_bits, 384)

    def hash(self, vec: np.ndarray) -> List[int]:
        # Project onto random hyperplanes, binarize
        projections = self.planes @ vec  # (n_tables, n_bits)
        return [int(''.join(['1' if x > 0 else '0' for x in row]), 2)
                for row in projections]
```

For ≤200 chunks, LSH is not needed — full comparison costs <1ms.

---

## 9.9 Embedding Cache (LRU)

Query embeddings are cached to avoid re-encoding repeated queries:

```python
from functools import lru_cache

class EmbeddingCache:
    def __init__(self, maxsize: int = 128):
        self.cache = {}  # query_hash → embedding
        self.maxsize = maxsize
        self.access_order = []

    def get(self, query: str) -> Optional[np.ndarray]:
        key = hashlib.sha1(query.encode()).hexdigest()
        if key in self.cache:
            self.access_order.remove(key)
            self.access_order.append(key)
            return self.cache[key]
        return None

    def put(self, query: str, embedding: np.ndarray):
        key = hashlib.sha1(query.encode()).hexdigest()
        if len(self.cache) >= self.maxsize:
            oldest = self.access_order.pop(0)
            del self.cache[oldest]
        self.cache[key] = embedding
        self.access_order.append(key)
```

Cache size 128 entries × 384 × 4 bytes = **196KB** max. Acceptable.

---

## 9.10 Semantic Score Model

```python
@dataclass
class SemanticResult:
    chunk_id: str
    score: float          # Cosine similarity [0, 1] (normalized embeddings)
    embedding_model: str  # Which model generated the embedding
```

No additional normalization needed — cosine similarity of L2-normalized vectors is already in [-1, 1], effectively [0, 1] for meaningful code pairs.
