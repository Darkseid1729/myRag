# Pseudocode: Embedding Pipeline Algorithms

## onnx_encoder.py

```
CLASS ONNXEncoder:
    INIT(model_path):
        self.session = ort.InferenceSession(
            model_path,
            providers=["CPUExecutionProvider"]
        )
        self.tokenizer = load_tokenizer(model_path)
        self.max_length = 256  # Tokens per chunk

    FUNCTION encode(texts: List[str]) -> np.ndarray:
        """
        Encode a list of texts to normalized float32 embeddings.
        Returns: np.ndarray shape (N, 384)
        """

        # Tokenize
        encoded = self.tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=self.max_length,
            return_tensors="np"
        )

        # Run ONNX inference
        outputs = self.session.run(
            output_names=None,
            input_feed={
                "input_ids": encoded["input_ids"],
                "attention_mask": encoded["attention_mask"]
            }
        )

        # Token embeddings: (batch, seq_len, 384)
        token_embeddings = outputs[0]
        attention_mask = encoded["attention_mask"]

        # Mean pooling: average over non-padding tokens
        mask_expanded = expand_mask(attention_mask, token_embeddings.shape)
        sum_embeddings = np.sum(token_embeddings * mask_expanded, axis=1)
        sum_mask = np.clip(np.sum(mask_expanded, axis=1), a_min=1e-9, a_max=None)
        embeddings = sum_embeddings / sum_mask  # (batch, 384)

        # L2 normalize
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms = np.clip(norms, a_min=1e-9, a_max=None)
        embeddings = embeddings / norms  # Unit vectors

        RETURN embeddings.astype(np.float32)
```

---

## quantizer.py

```
FUNCTION quantize_to_int8(vector: np.ndarray) -> (bytes, float):
    """
    Quantize a float32 vector to int8.
    
    Formula:
        scale = max(|v|) / 127
        quantized = round(v / scale)  [clamped to [-127, 127]]
    
    Returns: (quantized_bytes, scale_factor)
    """

    abs_max = np.max(np.abs(vector))

    IF abs_max == 0:
        RETURN bytes(len(vector)), 1.0

    scale = float(abs_max) / 127.0
    quantized = np.round(vector / scale)
    quantized = np.clip(quantized, -127, 127)
    quantized = quantized.astype(np.int8)

    RETURN quantized.tobytes(), scale


FUNCTION dequantize_from_int8(blob: bytes, scale: float) -> np.ndarray:
    """
    Reconstruct approximate float32 vector from int8 bytes.
    Error is typically 0.002-0.005 per dimension.
    """
    quantized = np.frombuffer(blob, dtype=np.int8).astype(np.float32)
    RETURN quantized * scale


FUNCTION cosine_similarity_int8(
    query_vec: np.ndarray,       # float32 (384,)
    chunk_blob: bytes,
    chunk_scale: float
) -> float:
    """
    Compute cosine similarity between a float32 query and a quantized chunk.
    Both are assumed to be L2-normalized before storage.
    """
    chunk_vec = dequantize_from_int8(chunk_blob, chunk_scale)  # float32 (384,)
    # After dequantize, renormalize to unit length
    chunk_norm = np.linalg.norm(chunk_vec)
    IF chunk_norm > 0:
        chunk_vec = chunk_vec / chunk_norm

    RETURN float(np.dot(query_vec, chunk_vec))  # Dot product of unit vectors = cosine


FUNCTION batch_cosine_similarity(
    query_vec: np.ndarray,       # (384,)
    blobs_and_scales: List[(bytes, float)]
) -> np.ndarray:
    """Vectorized batch computation — much faster than one-by-one"""

    matrix = np.zeros((len(blobs_and_scales), 384), dtype=np.float32)
    FOR i, (blob, scale) IN enumerate(blobs_and_scales):
        matrix[i] = dequantize_from_int8(blob, scale)

    # Renormalize rows
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms = np.clip(norms, 1e-9, None)
    matrix = matrix / norms

    # Batch dot product
    RETURN matrix @ query_vec  # (N,)
```

---

## embedding_cache.py

```
CLASS EmbeddingLRUCache:
    """
    LRU cache for decoded float32 embeddings.
    Avoids repeated dequantize operations for frequently accessed chunks.
    """

    INIT(max_bytes=1_000_000):  # 1MB default
        self.cache = OrderedDict()  # chunk_id → np.ndarray
        self.byte_sizes = {}        # chunk_id → byte_size
        self.current_bytes = 0
        self.max_bytes = max_bytes
        self.hits = 0
        self.misses = 0
        EMBEDDING_BYTES = 384 * 4  # float32

    FUNCTION get(chunk_id: str) -> Optional[np.ndarray]:
        IF chunk_id IN self.cache:
            self.cache.move_to_end(chunk_id)  # Mark LRU
            self.hits += 1
            RETURN self.cache[chunk_id]
        self.misses += 1
        RETURN None

    FUNCTION put(chunk_id: str, embedding: np.ndarray):
        size = embedding.nbytes

        # Evict until we have space
        WHILE self.current_bytes + size > self.max_bytes AND self.cache:
            evicted_key = next(iter(self.cache))
            evicted_size = self.byte_sizes.pop(evicted_key)
            del self.cache[evicted_key]
            self.current_bytes -= evicted_size

        IF size <= self.max_bytes:
            self.cache[chunk_id] = embedding
            self.byte_sizes[chunk_id] = size
            self.current_bytes += size

    FUNCTION hit_rate() -> float:
        total = self.hits + self.misses
        RETURN self.hits / total IF total > 0 ELSE 0.0

    FUNCTION invalidate(chunk_id: str):
        IF chunk_id IN self.cache:
            size = self.byte_sizes.pop(chunk_id)
            del self.cache[chunk_id]
            self.current_bytes -= size


# Global singleton
_EMBEDDING_CACHE = EmbeddingLRUCache(max_bytes=1_000_000)  # 1MB


FUNCTION get_or_load_embedding(chunk_id: str, db) -> np.ndarray:
    """
    Get embedding from LRU cache, or load from SQLite and cache it.
    """
    cached = _EMBEDDING_CACHE.get(chunk_id)
    IF cached IS NOT None:
        RETURN cached

    # Load from DB
    row = db.execute(
        "SELECT vector, scale FROM embeddings WHERE chunk_id=?",
        [chunk_id]
    ).fetchone()

    IF row IS None:
        RAISE ValueError(f"No embedding found for chunk_id={chunk_id}")

    blob, scale = row
    embedding = dequantize_from_int8(blob, scale)

    # Renormalize (quantization may have introduced slight error)
    norm = np.linalg.norm(embedding)
    IF norm > 0:
        embedding = embedding / norm

    _EMBEDDING_CACHE.put(chunk_id, embedding)
    RETURN embedding
```

---

## semantic_retriever.py

```
ASYNC FUNCTION semantic_retrieve(
    query: str,
    candidate_ids: List[str],
    db,
    top_k: int = 20
) -> Dict[str, float]:
    """
    Compute cosine similarities between query and candidates.
    Returns {chunk_id: similarity_score} for top_k results.
    """

    # Encode query (check query embedding cache first)
    query_vec = query_embedding_cache.get(query)
    IF query_vec IS None:
        query_vec = encoder.encode([query])[0]  # (384,) float32
        query_embedding_cache.put(query, query_vec)

    # Load candidate embeddings (from LRU cache or SQLite)
    blobs_and_scales = []
    valid_ids = []

    FOR chunk_id IN candidate_ids:
        cached = _EMBEDDING_CACHE.get(chunk_id)
        IF cached IS NOT None:
            blobs_and_scales.append((None, None, cached))  # Already decoded
        ELSE:
            row = db.execute(
                "SELECT vector, scale FROM embeddings WHERE chunk_id=?",
                [chunk_id]
            ).fetchone()
            IF row:
                valid_ids.append(chunk_id)
                blobs_and_scales.append((row[0], row[1], None))

    # Batch compute similarities
    scores = {}
    FOR chunk_id, (blob, scale, cached_vec) IN zip(candidate_ids, blobs_and_scales):
        IF cached_vec IS NOT None:
            vec = cached_vec
        ELSE:
            vec = dequantize_from_int8(blob, scale)
            norm = np.linalg.norm(vec)
            IF norm > 0:
                vec = vec / norm
            _EMBEDDING_CACHE.put(chunk_id, vec)

        sim = float(np.dot(query_vec, vec))
        scores[chunk_id] = max(0.0, sim)  # Clip negatives

    # Return top-k
    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    RETURN dict(sorted_scores[:top_k])
```
