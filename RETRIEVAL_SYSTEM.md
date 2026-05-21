# Retrieval System

## Overview

The retrieval system combines three independent search engines — lexical (FTS5), semantic (ONNX), and structural (graph BFS) — whose scores are fused with intent-determined weights.

---

## Intent Router

**File:** `src/intent/intent_router.py`

The intent router is the entry point for every query. It classifies the query into one of 7 intent types and selects a matching retrieval strategy.

### Intent Taxonomy

| Intent | Example Query | Strategy Focus |
|--------|--------------|----------------|
| `symbol_lookup` | "Where is `useAuth` defined?" | Lexical-heavy, shallow graph |
| `architecture` | "How does authentication work?" | Semantic + deep graph |
| `modification_guidance` | "Where should I add dark mode?" | Semantic-heavy, medium graph |
| `debugging` | "Why is login broken?" | Balanced lexical/semantic/graph |
| `rerender_analysis` | "Why does Dashboard rerender?" | Graph-heavy, state/hook edges |
| `route_tracing` | "Which files affect /dashboard?" | Graph-dominant, route edges |
| `impact_analysis` | "What breaks if I change useAuth?" | Reverse BFS traversal |

### Rule-Based Classification

```python
# Pattern example for SYMBOL_LOOKUP:
r"\bwhere is\b"
r"\bfind\b.{0,30}\b(function|component|hook)\b"
r"\bwhere (is|are|does)\b.{0,30}\bdefined\b"

# Match counting:
for intent, patterns in rules:
    match_count = sum(1 for p in patterns if p.search(query))
winner = argmax(match_count)
```

### Embedding Fallback

When no rules match (generic query), the router computes cosine similarity between the query embedding and per-intent exemplar embeddings:

```python
EXEMPLARS = {
    Intent.SYMBOL_LOOKUP: ["where is the login function", "find the useAuth hook"],
    Intent.ARCHITECTURE: ["how does authentication work", "explain routing flow"],
    ...
}
# Best exemplar match → intent
```

### Query Expansion

The expanded query adds synonyms for common shorthand terms:

| Token | Expansions |
|-------|-----------|
| `auth` | authentication, login, token, JWT, session |
| `theme` | dark mode, light mode, colors, palette, useTheme |
| `state` | useState, useReducer, store, Redux, Zustand, atoms |
| `fetch` | API, axios, useQuery, REST, HTTP, endpoint |

The expanded query is used for FTS5 and embedding search. The original query is shown to the user.

### Retrieval Strategies

```python
# Per-intent weight tuples: (lexical, semantic, graph, depth)
SYMBOL_LOOKUP:         (0.7, 0.2, 0.1, depth=1)
ARCHITECTURE:          (0.2, 0.3, 0.5, depth=3)
MODIFICATION_GUIDANCE: (0.3, 0.5, 0.2, depth=2)
DEBUGGING:             (0.4, 0.4, 0.2, depth=2)
RERENDER_ANALYSIS:     (0.3, 0.4, 0.3, depth=2, edges=[MANAGES_STATE, USES_HOOK, RENDERS])
ROUTE_TRACING:         (0.2, 0.2, 0.6, depth=4, edges=[DEFINES_ROUTE, RENDERS, IMPORTS])
IMPACT_ANALYSIS:       (0.2, 0.2, 0.6, depth=3, reverse=True)
```

---

## Lexical Search (FTS5 BM25)

**Function:** `lexical_search(db, query, top_k)`

### How FTS5 Works

SQLite's FTS5 extension builds an inverted index over the `text`, `symbols`, and `summary` columns of `fts_chunks`. The `porter` tokenizer applies stemming so that `login`, `logging`, `logged` all match.

```sql
SELECT c.id, ..., fts_chunks.rank AS bm25_score
FROM fts_chunks
JOIN chunks c ON fts_chunks.chunk_id = c.id
WHERE fts_chunks MATCH ?
ORDER BY fts_chunks.rank
```

FTS5 `rank` is a negative float (BM25 score). Lower = more relevant.

### Score Normalisation

```python
# Transform negative BM25 rank to [0, 1] score
raw = abs(row["bm25_score"])   # e.g., 3.14
norm_score = 1.0 / (1.0 + raw)  # 0.241 (less relevant)
# Perfect match: rank ≈ 0 → score ≈ 1.0
```

### Query Sanitisation

```python
safe = query.replace('"', '""')  # escape FTS5 phrase operator
         .replace("/", " ")       # prevent path confusion
         .replace("\\", " ")
```

### Fallback on Error

If the full FTS5 query fails (e.g., malformed query), the system retries with only the first token of the query.

---

## Semantic Search (ONNX Cosine)

**Function:** `semantic_search(db, encoder, query, candidate_ids)`

### Embedding the Query

```python
query_vec = encoder.encode([query])[0]  # float32[384], L2-normalised
```

The encoder uses `all-MiniLM-L6-v2` (ONNX format, ~22 MB). Tokenisation uses the model's `tokenizer.json` directly (no transformers library needed).

### Candidate Retrieval

In normal operation, semantic search runs **only over the FTS5 candidates** (up to 50 chunks), not over all embeddings. This is the key to keeping semantic search fast:

1. FTS5 provides a pre-filtered candidate pool (fast).
2. ONNX encoder computes cosine similarity only over candidates (bounded).

### Full Scan Fallback

If FTS5 returns 0 results (e.g., query has no keyword overlap with any chunk), semantic search falls back to querying all embeddings (up to 500 chunks). This is slower but ensures results are always returned.

### Score Normalisation

ONNX encoder produces L2-normalised vectors, so cosine similarity is in `[-1, 1]`. We shift to `[0, 1]`:

```python
normalised_score = (cosine + 1.0) / 2.0
```

### LRU Cache

Dequantized vectors are cached in a thread-safe LRU cache (configurable byte cap, default 1 MB). This prevents repeated int8→float32 conversion for frequently accessed chunks.

---

## Graph Search (BFS)

**Function:** `graph_search(db, seed_chunk_ids, strategy)`

### Algorithm

```
visited = {}
frontier = [(seed_id, score=1.0) for each seed]

for depth in range(strategy.graph_depth):
    decay = 0.5 ^ depth

    fetch all neighbours of frontier via:
        SELECT to_id, weight FROM graph_edges
        WHERE from_id IN (frontier_ids)
        [AND edge_type IN (strategy.edge_types)]

    for each (neighbour, weight):
        score = weight * decay
        if neighbour not in visited:
            visited[neighbour] = score
        else:
            visited[neighbour] = max(visited[neighbour], score)

    frontier = new_neighbours

return visited  # dict: chunk_id → graph_score ∈ (0, 1]
```

### Decay Schedule

| Depth | Decay | Max Score |
|-------|-------|-----------|
| 0 (seeds) | 1.0 | 1.0 |
| 1 hop | 0.5 | 0.5 |
| 2 hops | 0.25 | 0.25 |
| 3 hops | 0.125 | 0.125 |
| 4 hops | 0.0625 | 0.0625 |

### Reverse Traversal

For `IMPACT_ANALYSIS` intent, `strategy.reverse=True` flips the edge direction:
```sql
-- Normal: follow outgoing edges
WHERE from_id IN (frontier)

-- Reverse: follow incoming edges
WHERE to_id IN (frontier)
```

This finds everything that **depends on** the seed chunks (callers, importers, renderers).

### Frontier Bound

The BFS frontier is capped at `memory.graph_bfs_frontier` (default 512 nodes) to prevent runaway expansion on densely connected graphs.

---

## Score Fusion

```python
final_score = (
    w_l * chunk.lexical_score
  + w_s * chunk.semantic_score
  + w_g * chunk.graph_score
)
```

Where `w_l + w_s + w_g` varies by intent (see the strategy table above).

### Example: Route Tracing

```
Intent: ROUTE_TRACING
w_l=0.2, w_s=0.2, w_g=0.6

chunk with lexical=0.8, semantic=0.3, graph=1.0:
  final = 0.2*0.8 + 0.2*0.3 + 0.6*1.0
        = 0.16 + 0.06 + 0.60
        = 0.82
```

A chunk directly connected in the route graph scores 0.82 even with moderate keyword relevance.

---

## Optional Reranker

**File:** `src/retriever/reranker.py`

Enable in `config/default.yaml`:
```yaml
retrieval:
  use_reranker: true
  reranker_model: "cross-encoder/ms-marco-MiniLM-L-6-v2"
  reranker_top_k: 10
```

### How It Works

The cross-encoder takes `(query, passage)` pairs and scores their relevance jointly (not independently like bi-encoders). This is more accurate but slower:

```python
model = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
scores = model.predict([(query, chunk.text) for chunk in chunks])
```

### Singleton Cache

The `CrossEncoder` model is loaded once per process and cached in a module-level dict. It is **not** reloaded per query.

### RAM Cost

The cross-encoder model is ~67 MB. Combined with the ONNX encoder, total model RAM reaches ~90 MB — exceeding the 20 MB per-project target. **Only enable if you have RAM to spare.**

---

## Retrieval Cache

All query responses are cached in the `retrieval_cache` table:

```sql
CREATE TABLE retrieval_cache (
    query_hash  TEXT PRIMARY KEY,  -- SHA256 of (project_root + query + top_k)
    result_json TEXT NOT NULL,
    created_at  INTEGER NOT NULL,
    hit_count   INTEGER DEFAULT 0,
    ttl_seconds INTEGER DEFAULT 3600
);
```

- Cache is checked **before** any search work.
- Cache is invalidated (all rows deleted) on every re-index run.
- Expired entries are deleted lazily by `db.evict_expired_cache()`.
- TTL is configurable: `retrieval.cache_ttl_seconds` (default: 3600 = 1 hour).
