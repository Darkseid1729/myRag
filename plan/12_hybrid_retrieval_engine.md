# 12 — HYBRID RETRIEVAL ENGINE

## 12.1 Architecture Overview

The hybrid retriever orchestrates all three retrieval signals and fuses them into a single ranked list.

```
Query + Intent + Strategy
        │
        ├──► [Lexical Retriever]   → {chunk_id: lex_score}
        ├──► [Semantic Retriever]  → {chunk_id: sem_score}
        └──► [Graph Retriever]     → {chunk_id: graph_score}
                    │
                    ▼
              [Score Fusion]
                    │
                    ▼
              [Deduplication]
                    │
                    ▼
              [Reranker] (optional)
                    │
                    ▼
              Top-K RankedChunks
```

All three retrievers run in **parallel** (asyncio or thread pool) to minimize latency.

---

## 12.2 Lexical Scoring

```python
def lexical_retrieve(query: str, project_id: str, top_k: int = 50) -> Dict[str, float]:
    """Returns {chunk_id: normalized_score}"""
    fts_query = build_fts_query(query)

    rows = db.execute("""
        SELECT chunk_id,
               bm25(fts_chunks, 0, 2.0, 1.5) as raw_score
        FROM fts_chunks
        WHERE fts_chunks MATCH ?
        ORDER BY raw_score
        LIMIT ?
    """, [fts_query, top_k]).fetchall()

    # BM25 returns negative values — negate and normalize
    raw = [(cid, -score) for cid, score in rows]  # Now positive = better
    max_score = max(s for _, s in raw) if raw else 1.0

    return {cid: s / max_score for cid, s in raw}
```

---

## 12.3 Semantic Scoring

```python
async def semantic_retrieve(query: str, candidate_ids: List[str], top_k: int = 30) -> Dict[str, float]:
    """Returns {chunk_id: cosine_similarity_score}"""

    query_vec = encoder.encode([query])[0]  # (384,) float32

    # Load only candidate embeddings
    if candidate_ids:
        rows = db.execute(
            f"SELECT chunk_id, vector, scale FROM embeddings WHERE chunk_id IN ({placeholders})",
            candidate_ids
        ).fetchall()
    else:
        rows = db.execute("SELECT chunk_id, vector, scale FROM embeddings").fetchall()

    scores = {}
    for chunk_id, blob, scale in rows:
        vec = dequantize(blob, scale)
        similarity = float(np.dot(query_vec, vec))  # Cosine (already L2-normalized)
        scores[chunk_id] = max(0.0, similarity)     # Clip negative similarities

    return scores
```

---

## 12.4 Graph Scoring

```python
def graph_retrieve(seed_chunk_ids: List[str], strategy: RetrievalStrategy, db) -> Dict[str, float]:
    """Returns {chunk_id: proximity_score} for graph-connected chunks"""

    if not strategy.use_graph or not seed_chunk_ids:
        return {}

    scores = {}
    distance_map = {0: 1.0, 1: 0.7, 2: 0.4, 3: 0.2, 4: 0.1}

    for seed_id in seed_chunk_ids:
        neighbors = bfs(
            start_id=seed_id,
            edge_types=strategy.edge_types,
            max_depth=strategy.graph_depth,
            reverse=strategy.reverse,
            db=db
        )

        for node in neighbors:
            score = distance_map.get(node.depth, 0.0)
            # Take max score if node reachable from multiple seeds
            scores[node.node_id] = max(scores.get(node.node_id, 0.0), score)

    return scores
```

---

## 12.5 Score Fusion (Weighted Sum)

```python
def fuse_scores(
    lex_scores: Dict[str, float],
    sem_scores: Dict[str, float],
    graph_scores: Dict[str, float],
    strategy: RetrievalStrategy
) -> Dict[str, float]:
    """Compute weighted sum across all signals"""

    # Union of all candidate chunk_ids
    all_ids = set(lex_scores) | set(sem_scores) | set(graph_scores)

    fused = {}
    for chunk_id in all_ids:
        l = lex_scores.get(chunk_id, 0.0)
        s = sem_scores.get(chunk_id, 0.0)
        g = graph_scores.get(chunk_id, 0.0)

        score = (
            strategy.lexical_weight  * l +
            strategy.semantic_weight * s +
            strategy.graph_weight    * g
        )
        fused[chunk_id] = score

    return fused
```

### Weight Configurations per Intent

| Intent | Lexical | Semantic | Graph |
|--------|---------|----------|-------|
| SYMBOL_LOOKUP | 0.7 | 0.2 | 0.1 |
| ARCHITECTURE | 0.2 | 0.3 | 0.5 |
| MODIFICATION | 0.3 | 0.5 | 0.2 |
| DEBUGGING | 0.4 | 0.4 | 0.2 |
| RERENDER | 0.3 | 0.4 | 0.3 |
| ROUTE_TRACING | 0.2 | 0.2 | 0.6 |
| IMPACT | 0.2 | 0.2 | 0.6 |

---

## 12.6 Ranking Formula

Full scoring formula:

```
final_score(chunk) =
    w_lex  × normalize(bm25_score)
  + w_sem  × cosine_similarity
  + w_graph × proximity_score
  + bonus_freshness × recency_factor     (optional: recently modified files)
  + bonus_type × chunk_type_affinity     (e.g., prefer COMPONENT chunks for component queries)
```

### Chunk Type Affinity Bonuses

```python
TYPE_AFFINITY = {
    Intent.SYMBOL_LOOKUP: {
        ChunkType.FUNCTION: 0.1,
        ChunkType.COMPONENT: 0.1,
        ChunkType.HOOK: 0.1,
    },
    Intent.ROUTE_TRACING: {
        ChunkType.ROUTE_BLOCK: 0.2,
    },
    Intent.RERENDER_ANALYSIS: {
        ChunkType.COMPONENT: 0.15,
        ChunkType.STATE_BLOCK: 0.15,
    },
}
```

---

## 12.7 Candidate Filtering Strategy

Before computing expensive semantic scores, apply lightweight filters:

```python
def pre_filter(
    all_chunks: List[Chunk],
    query_tokens: Set[str],
    intent: Intent
) -> List[Chunk]:
    """Remove chunks that are clearly irrelevant"""

    filtered = []
    for chunk in all_chunks:

        # Skip test files unless query mentions "test"
        if 'test' in chunk.file_path and 'test' not in query_tokens:
            continue

        # Skip config files unless relevant intent
        if chunk.chunk_type == ChunkType.CONFIG and intent != Intent.MODIFICATION_GUIDANCE:
            continue

        # Skip import-only blocks for architecture queries (too noisy)
        if chunk.chunk_type == ChunkType.IMPORT_BLOCK and intent == Intent.ARCHITECTURE:
            continue

        filtered.append(chunk)

    return filtered
```

---

## 12.8 Reranker (Optional)

For higher quality results at the cost of ~10ms extra latency:

```python
class CrossEncoderReranker:
    """
    Optional: Use a tiny cross-encoder to rerank top-K results.
    Only applied to top-20 candidates from fusion.
    """
    def __init__(self, model_path: str):
        self.session = ort.InferenceSession(model_path)

    def rerank(self, query: str, candidates: List[RankedChunk]) -> List[RankedChunk]:
        pairs = [(query, c.chunk.text[:512]) for c in candidates[:20]]
        scores = self.session.run(None, self._encode_pairs(pairs))[0]
        for i, c in enumerate(candidates[:20]):
            c.rerank_score = float(scores[i])
        return sorted(candidates[:20], key=lambda c: c.rerank_score, reverse=True)
```

Cross-encoder model: `ms-marco-MiniLM-L-2-v2` ONNX (~15MB). Only loaded if explicitly enabled.

---

## 12.9 Full Retrieval Pseudocode

```python
async def retrieve(query: str, project_id: str, config: Config) -> List[RankedChunk]:

    # Step 1: Route intent
    routing = intent_router.route(query)
    strategy = routing.strategy
    expanded_query = routing.expanded_query

    # Step 2: Parallel retrieval
    async with asyncio.TaskGroup() as tg:
        lex_task  = tg.create_task(lexical_retrieve(expanded_query, project_id, top_k=50))
        # Semantic uses lexical candidates as pre-filter
        sem_task  = tg.create_task(semantic_retrieve(expanded_query, list(lex_scores.keys()), top_k=30))
        graph_task = tg.create_task(graph_retrieve(list(lex_scores.keys())[:10], strategy))

    lex_scores   = await lex_task
    sem_scores   = await sem_task
    graph_scores = await graph_task

    # Step 3: Fuse scores
    fused = fuse_scores(lex_scores, sem_scores, graph_scores, strategy)

    # Step 4: Sort and get top-K
    sorted_ids = sorted(fused, key=fused.get, reverse=True)[:strategy.top_k]

    # Step 5: Fetch chunk data
    chunks = fetch_chunks_by_ids(sorted_ids, db)

    # Step 6: Assemble RankedChunk objects
    ranked = [
        RankedChunk(
            chunk=chunk,
            lex_score=lex_scores.get(chunk.id, 0.0),
            sem_score=sem_scores.get(chunk.id, 0.0),
            graph_score=graph_scores.get(chunk.id, 0.0),
            final_score=fused[chunk.id]
        )
        for chunk in chunks
    ]

    # Step 7: Optional reranking
    if config.enable_reranker:
        ranked = reranker.rerank(query, ranked)

    return ranked
```

---

## 12.10 Evidence Aggregation

After ranking, evidence from multiple chunks is aggregated to avoid redundancy:

```python
def aggregate_evidence(ranked: List[RankedChunk]) -> List[RankedChunk]:
    """Remove near-duplicate chunks (same file, overlapping line ranges)"""
    seen_ranges = {}  # file_path → list of (start, end) ranges
    deduplicated = []

    for rc in ranked:
        key = rc.chunk.file_path
        if key not in seen_ranges:
            seen_ranges[key] = []

        overlap = any(
            range_overlap((rc.chunk.start_line, rc.chunk.end_line), existing)
            for existing in seen_ranges[key]
        )

        if not overlap:
            seen_ranges[key].append((rc.chunk.start_line, rc.chunk.end_line))
            deduplicated.append(rc)

    return deduplicated
```
