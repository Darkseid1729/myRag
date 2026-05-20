"""Three retrieval engines: lexical (FTS5), semantic (ONNX), graph (BFS)."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

import numpy as np

from src.storage.db_manager import DBManager
from src.embeddings.onnx_encoder import ONNXEncoder
from src.intent.intent_router import RetrievalStrategy
from src.utils import get_logger

logger = get_logger(__name__)


@dataclass
class RankedChunk:
    chunk_id: str
    file_path: str
    chunk_type: str
    name: str | None
    text: str
    start_line: int
    end_line: int
    lexical_score: float = 0.0
    semantic_score: float = 0.0
    graph_score: float = 0.0
    final_score: float = 0.0


# ---------------------------------------------------------------------------
# Lexical retriever (FTS5)
# ---------------------------------------------------------------------------

def lexical_search(db: DBManager, query: str, top_k: int = 50) -> list[RankedChunk]:
    """FTS5 BM25 search against chunk text, symbols, and summaries."""
    # Escape FTS5 special characters
    safe_query = query.replace('"', '""')
    sql = """
        SELECT c.id, c.chunk_type, c.name, c.text, c.start_line, c.end_line,
               f.path AS file_path,
               fts_chunks.rank AS bm25_score
        FROM fts_chunks
        JOIN chunks c ON fts_chunks.chunk_id = c.id
        JOIN files  f ON c.file_id = f.id
        WHERE fts_chunks MATCH ?
        ORDER BY fts_chunks.rank
        LIMIT ?
    """
    try:
        rows = db.fetchall(sql, (safe_query, top_k))
    except Exception as exc:
        logger.warning(f"FTS5 error: {exc}. Trying simpler query…")
        # Fall back: search only first token
        token = query.split()[0] if query.split() else query
        rows = db.fetchall(sql, (token, top_k))

    results = []
    for row in rows:
        # FTS5 rank is negative (lower = better); normalise to [0,1]
        raw_score = abs(float(row["bm25_score"]))
        norm_score = 1.0 / (1.0 + raw_score)
        results.append(RankedChunk(
            chunk_id=row["id"],
            file_path=row["file_path"],
            chunk_type=row["chunk_type"],
            name=row["name"],
            text=row["text"],
            start_line=row["start_line"],
            end_line=row["end_line"],
            lexical_score=norm_score,
        ))
    return results


# ---------------------------------------------------------------------------
# Semantic retriever (ONNX cosine similarity)
# ---------------------------------------------------------------------------

def semantic_search(
    db: DBManager,
    encoder: ONNXEncoder,
    query: str,
    candidate_ids: list[str],
) -> dict[str, float]:
    """Compute cosine similarity for a pre-filtered set of candidate chunks."""
    if not candidate_ids:
        return {}

    query_vec = encoder.encode([query])[0]

    placeholders = ",".join("?" * len(candidate_ids))
    rows = db.fetchall(
        f"SELECT chunk_id, vector, scale FROM embeddings WHERE chunk_id IN ({placeholders})",
        tuple(candidate_ids),
    )

    blobs = [(r["chunk_id"], bytes(r["vector"]), float(r["scale"])) for r in rows]
    scored = encoder.cosine_similarity_batch(query_vec, blobs)
    return {chunk_id: score for chunk_id, score in scored}


# ---------------------------------------------------------------------------
# Graph retriever (BFS over graph_edges)
# ---------------------------------------------------------------------------

def graph_search(
    db: DBManager,
    seed_chunk_ids: list[str],
    strategy: RetrievalStrategy,
) -> dict[str, float]:
    """
    BFS from seed nodes up to strategy.graph_depth hops.
    Keeps only active frontier in memory (bounded queue).
    """
    if not seed_chunk_ids:
        return {}

    visited: dict[str, float] = {}   # chunk_id → score
    frontier = [(cid, 1.0) for cid in seed_chunk_ids]
    edge_filter = strategy.edge_types
    reverse = strategy.reverse

    for depth in range(strategy.graph_depth):
        if not frontier:
            break
        decay = 0.5 ** depth
        next_frontier = []

        frontier_ids = [cid for cid, _ in frontier]
        placeholders = ",".join("?" * len(frontier_ids))

        if reverse:
            col_src, col_dst = "to_id", "from_id"
        else:
            col_src, col_dst = "from_id", "to_id"

        type_filter = ""
        params: list = frontier_ids[:]
        if edge_filter:
            ph = ",".join("?" * len(edge_filter))
            type_filter = f"AND edge_type IN ({ph})"
            params.extend(edge_filter)

        sql = f"""
            SELECT {col_dst} AS neighbour_id, edge_type, weight
            FROM graph_edges
            WHERE {col_src} IN ({placeholders}) {type_filter}
        """
        rows = db.fetchall(sql, tuple(params))

        for row in rows:
            nid = row["neighbour_id"]
            w = float(row["weight"]) * decay
            if nid not in visited:
                visited[nid] = w
                next_frontier.append((nid, w))
            else:
                visited[nid] = max(visited[nid], w)

        frontier = next_frontier

    return visited


# ---------------------------------------------------------------------------
# Hybrid retriever (fusion)
# ---------------------------------------------------------------------------

def hybrid_search(
    db: DBManager,
    encoder: ONNXEncoder,
    query: str,
    strategy: RetrievalStrategy,
) -> list[RankedChunk]:
    """
    Full hybrid retrieval:
    1. FTS5 lexical search → candidate pool
    2. Semantic cosine similarity over candidates
    3. BFS graph expansion from top candidates
    4. Weighted score fusion + rerank
    """
    # Step 1: Lexical candidates
    lex_results = lexical_search(db, query, top_k=50)
    lex_map = {r.chunk_id: r for r in lex_results}

    # Step 2: Semantic scores for candidates
    candidate_ids = [r.chunk_id for r in lex_results]
    sem_map = semantic_search(db, encoder, query, candidate_ids)

    # Step 3: Graph expansion from top-10 lexical hits
    graph_map: dict[str, float] = {}
    if strategy.use_graph:
        seed_ids = [r.chunk_id for r in lex_results[:10]]
        graph_map = graph_search(db, seed_ids, strategy)

    # Step 4: Collect all chunk IDs
    all_ids = set(lex_map) | set(graph_map)

    # Fetch any graph-only chunks not in lexical results
    if graph_map:
        extra_ids = [cid for cid in graph_map if cid not in lex_map]
        if extra_ids:
            ph = ",".join("?" * len(extra_ids))
            rows = db.fetchall(
                f"""SELECT c.id, c.chunk_type, c.name, c.text, c.start_line, c.end_line,
                           f.path AS file_path
                    FROM chunks c JOIN files f ON c.file_id = f.id
                    WHERE c.id IN ({ph})""",
                tuple(extra_ids),
            )
            for row in rows:
                lex_map[row["id"]] = RankedChunk(
                    chunk_id=row["id"],
                    file_path=row["file_path"],
                    chunk_type=row["chunk_type"],
                    name=row["name"],
                    text=row["text"],
                    start_line=row["start_line"],
                    end_line=row["end_line"],
                )

    # Step 5: Compute final fused scores
    wl = strategy.lexical_weight
    ws = strategy.semantic_weight
    wg = strategy.graph_weight

    final: list[RankedChunk] = []
    for cid, chunk in lex_map.items():
        chunk.lexical_score = chunk.lexical_score  # already set
        chunk.semantic_score = sem_map.get(cid, 0.0)
        chunk.graph_score = graph_map.get(cid, 0.0)
        chunk.final_score = (
            wl * chunk.lexical_score
            + ws * chunk.semantic_score
            + wg * chunk.graph_score
        )
        final.append(chunk)

    final.sort(key=lambda c: c.final_score, reverse=True)
    return final[:strategy.top_k]
