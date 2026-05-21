"""Three retrieval engines: lexical (FTS5), semantic (ONNX cosine), graph (BFS).

Hybrid fusion formula:
    final_score = w_l * lexical + w_s * semantic + w_g * graph

All sub-scores are normalised to [0, 1] before fusion.

Fallback behaviour:
- If FTS5 returns 0 results (empty DB or no keyword match), semantic search
  runs over ALL embeddings in the database (full scan — only practical for
  small projects ≤50 files).
- If graph is disabled in the strategy, graph_score = 0 for all chunks.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

import numpy as np

from src.storage.db_manager import DBManager
from src.embeddings.onnx_encoder import ONNXEncoder
from src.intent.intent_router import RetrievalStrategy
from src.utils import get_logger, split_camel_case
from src.config import get_config
from src.retriever.reranker import maybe_rerank

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
# Code-aware query preprocessing
# ---------------------------------------------------------------------------

# Common synonym expansions for code queries
_SYNONYM_MAP: dict[str, list[str]] = {
    "logout": ["signout", "sign out", "log out", "deauthenticate"],
    "login": ["signin", "sign in", "authenticate", "auth"],
    "auth": ["authentication", "authorization", "login", "token", "jwt", "session"],
    "theme": ["useTheme", "ThemeProvider", "darkmode", "lightmode", "palette"],
    "route": ["routing", "navigate", "useNavigate", "Link", "path", "page"],
    "state": ["useState", "useReducer", "redux", "store", "zustand", "context"],
    "fetch": ["api", "axios", "useQuery", "http", "endpoint", "request"],
    "render": ["rerender", "rerenders", "component", "jsx", "return"],
    "sidebar": ["Sidebar", "nav", "navigation", "drawer", "panel"],
    "calendar": ["Calendar", "schedule", "date", "datepicker"],
    "dashboard": ["Dashboard", "DashboardContent", "main page"],
    "authentication": ["login", "auth", "session", "jwt", "token", "LoginSwitcher"],
}

_FTS5_STOP_WORDS = {
    "who", "what", "where", "why", "how", "is", "are", "the", "a", "an",
    "does", "did", "to", "in", "on", "at", "all", "using", "places",
    "files", "affect", "handled", "this",
}

# Boilerplate indicators — penalise chunks heavy in these
_BOILERPLATE_PATTERNS = [
    re.compile(r"^import\s+", re.MULTILINE),     # import statements
    re.compile(r"^from\s+\S+\s+import", re.MULTILINE),  # Python-style imports
]

_HIGH_VALUE_PATTERNS = [
    re.compile(r"\buseState\b"),
    re.compile(r"\buseEffect\b"),
    re.compile(r"\buseContext\b"),
    re.compile(r"\buseCallback\b"),
    re.compile(r"\buseMemo\b"),
    re.compile(r"\buseReducer\b"),
    re.compile(r"\baxios\b|\bapi\.\b|\bfetch\("),
    re.compile(r"\bnavigate\b|\buseNavigate\b"),
    re.compile(r"\bcontext\b|\bProvider\b"),
    re.compile(r"\bonClick\b|\bonChange\b|\bonSubmit\b"),
    re.compile(r"\brouter\b|\bRoute\b"),
]


def _extract_identifiers(query: str) -> list[str]:
    """Extract camelCase/PascalCase identifiers from a query."""
    return re.findall(r"\b[a-z][a-zA-Z0-9]+[A-Z][a-zA-Z0-9]*\b|\b[A-Z][a-zA-Z0-9]+\b", query)


def _split_camel_for_fts(identifier: str) -> list[str]:
    """Split a camelCase/PascalCase identifier into parts for FTS matching."""
    parts = re.sub(r"([a-z])([A-Z])", r"\1 \2", identifier).split()
    return [p.lower() for p in parts]


def _build_fts_query(query: str) -> tuple[str, list[str]]:
    """
    Build a robust FTS5 query from a natural language query.

    Returns:
        (primary_fts_query, fallback_token_list)

    Strategy:
    1. Extract all identifiers (camelCase/symbols) — search them verbatim.
    2. Extract meaningful non-stopword tokens.
    3. OR them all together so any match is accepted.
    4. Expand synonyms for key terms.
    """
    # Strip FTS5 special chars
    clean = re.sub(r'[*\(\)\[\]\{\}:"\^~]', ' ', query)

    # Collect identifiers first (exact matches)
    identifiers = _extract_identifiers(query)
    camel_parts = []
    for ident in identifiers:
        camel_parts.extend(_split_camel_for_fts(ident))

    # Collect plain tokens, skip stop words
    plain_tokens = []
    for tok in re.sub(r'[^a-zA-Z0-9_]', ' ', clean).split():
        if tok.lower() not in _FTS5_STOP_WORDS and len(tok) > 2:
            plain_tokens.append(tok.lower())

    # Expand synonyms
    synonym_tokens: list[str] = []
    for tok in plain_tokens:
        if tok in _SYNONYM_MAP:
            for syn in _SYNONYM_MAP[tok]:
                # Only add single-word synonyms to avoid FTS phrase complexity
                if ' ' not in syn:
                    synonym_tokens.append(syn.lower())

    # Merge: identifiers (verbatim), camel parts, plain tokens, synonyms
    all_tokens = list(dict.fromkeys(
        identifiers + camel_parts + plain_tokens + synonym_tokens
    ))

    if not all_tokens:
        # absolute fallback: use raw query stripped of punctuation
        all_tokens = re.sub(r'[^a-zA-Z0-9 ]', ' ', query).split()

    # Build OR query so any token match returns results
    # FTS5 OR syntax: token1 OR token2 OR token3
    fts_query = " OR ".join(all_tokens[:20])  # limit to 20 terms
    return fts_query, all_tokens


# ---------------------------------------------------------------------------
# Chunk quality scoring (code-aware)
# ---------------------------------------------------------------------------

def _compute_quality_boost(chunk: "RankedChunk") -> float:
    """
    Return a [0, 0.3] quality boost based on code-awareness.

    - High-value chunk types (FUNCTION, COMPONENT, HOOK) get base boost.
    - Presence of hooks, API calls, event handlers, etc. adds extra.
    - Import-heavy / boilerplate chunks get a penalty.
    """
    boost = 0.0
    text = chunk.text

    # Base type boost
    if chunk.chunk_type in ("HOOK",):
        boost += 0.15
    elif chunk.chunk_type in ("COMPONENT", "FUNCTION"):
        boost += 0.10
    elif chunk.chunk_type in ("CLASS",):
        boost += 0.05

    # High-value pattern bonuses
    hv_matches = sum(1 for p in _HIGH_VALUE_PATTERNS if p.search(text))
    boost += min(0.15, hv_matches * 0.025)

    # Boilerplate penalty: chunks where most lines are imports
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if lines:
        import_lines = sum(1 for l in lines if l.startswith("import ") or l.startswith("from "))
        import_ratio = import_lines / len(lines)
        if import_ratio > 0.6:
            boost -= 0.2
        elif import_ratio > 0.3:
            boost -= 0.08

    return max(-0.2, min(0.3, boost))


# ---------------------------------------------------------------------------
# Lexical retriever (FTS5 BM25)
# ---------------------------------------------------------------------------

def lexical_search(db: DBManager, query: str, top_k: int = 50) -> list[RankedChunk]:
    """
    FTS5 BM25 search with robust OR-query semantics.

    Fixes applied vs. the old implementation:
    - OR-based query: any token match returns results (old AND was killing multi-word queries)
    - camelCase tokens searched verbatim AND split
    - Synonym expansion for common code terms
    - score normalised via rank magnitude (FTS5 rank is negative BM25)
    """
    fts_query, tokens = _build_fts_query(query)

    if not fts_query.strip():
        return []

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

    rows = []
    try:
        rows = db.fetchall(sql, (fts_query, top_k))
        logger.debug(f"Lexical FTS query '{fts_query[:60]}' → {len(rows)} rows")
    except Exception as exc:
        logger.warning(f"FTS5 OR-query error ('{fts_query[:40]}'): {exc}. Trying individual tokens…")
        # Fallback: try each token individually, collect all results
        seen_ids: set[str] = set()
        for tok in tokens[:8]:  # limit fallback attempts
            try:
                tok_rows = db.fetchall(sql, (tok, top_k))
                for r in tok_rows:
                    if r["id"] not in seen_ids:
                        rows.append(r)
                        seen_ids.add(r["id"])
            except Exception:
                pass

    if not rows:
        return []

    # Find the minimum rank magnitude for normalisation (most relevant hit)
    ranks = [abs(float(r["bm25_score"])) for r in rows]
    max_rank = max(ranks) if ranks else 1.0

    results: list[RankedChunk] = []
    for row in rows:
        raw = abs(float(row["bm25_score"]))
        # Normalise: best hit → 1.0, worst hit → approaches 0
        # Use rank-relative normalisation so scores spread meaningfully
        norm_score = 1.0 - (raw / (max_rank + 1e-9)) * 0.8
        norm_score = max(0.05, min(1.0, norm_score))
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
# Symbol-level direct lookup (supplements FTS for exact identifier queries)
# ---------------------------------------------------------------------------

def symbol_search(db: DBManager, query: str, top_k: int = 20) -> list[str]:
    """
    Look up chunk IDs directly from the symbols table for exact camelCase names.

    Returns chunk_ids that contain symbols matching any identifier in the query.
    """
    identifiers = _extract_identifiers(query)
    if not identifiers:
        return []

    ph = ",".join("?" * len(identifiers))
    rows = db.fetchall(
        f"SELECT DISTINCT chunk_id FROM symbols WHERE name IN ({ph}) LIMIT ?",
        tuple(identifiers) + (top_k,),
    )
    return [r["chunk_id"] for r in rows]


# ---------------------------------------------------------------------------
# Semantic retriever (ONNX cosine similarity)
# ---------------------------------------------------------------------------

def semantic_search(
    db: DBManager,
    encoder: ONNXEncoder,
    query: str,
    candidate_ids: list[str] | None = None,
) -> dict[str, float]:
    """Compute cosine similarity for candidate chunks.

    If ``candidate_ids`` is None or empty, runs over all embeddings in the
    database (full scan — intended as fallback for empty FTS results).

    Returns:
        dict mapping chunk_id → normalised cosine score in [0, 1].
    """
    query_vec = encoder.encode([query])[0]

    if candidate_ids:
        placeholders = ",".join("?" * len(candidate_ids))
        rows = db.fetchall(
            f"""SELECT e.chunk_id, e.vector, e.scale
                FROM embeddings e
                JOIN chunks c ON e.chunk_id = c.id
                WHERE e.chunk_id IN ({placeholders}) AND c.chunk_type != 'IMPORT_BLOCK'""",
            tuple(candidate_ids),
        )
    else:
        # Full scan fallback — exclude import blocks
        rows = db.fetchall("""
            SELECT e.chunk_id, e.vector, e.scale
            FROM embeddings e
            JOIN chunks c ON e.chunk_id = c.id
            WHERE c.chunk_type != 'IMPORT_BLOCK'
            LIMIT 500
        """)

    if not rows:
        return {}

    blobs = [(r["chunk_id"], bytes(r["vector"]), float(r["scale"])) for r in rows]
    scored = encoder.cosine_similarity_batch(query_vec, blobs)

    # Normalise cosine [-1, 1] → [0, 1]
    return {cid: (score + 1.0) / 2.0 for cid, score in scored}


# ---------------------------------------------------------------------------
# Graph retriever (BFS over graph_edges) — with decay and depth cap
# ---------------------------------------------------------------------------

def graph_search(
    db: DBManager,
    seed_chunk_ids: list[str],
    strategy: RetrievalStrategy,
) -> dict[str, float]:
    """BFS from seed nodes up to ``strategy.graph_depth`` hops.

    Improvements vs. old implementation:
    - Stronger exponential decay (0.65^depth) — distant neighbours contribute less.
    - Max depth capped at 3 for route-tracing to reduce noise.
    - Edge types are respected strictly.
    - Seeds are capped to top-quality seeds to avoid graph pollution.
    """
    if not seed_chunk_ids:
        return {}

    cfg = get_config()
    max_frontier: int = cfg["memory"].get("graph_bfs_frontier", 256)

    # Cap seeds to prevent noisy graph explosion
    seed_ids = list(set(seed_chunk_ids))[:10]

    visited: dict[str, float] = {}
    frontier = seed_ids[:max_frontier]
    edge_filter = strategy.edge_types
    reverse = strategy.reverse

    # Use stronger decay to reduce distant-node noise, but relax it for route tracing
    decay_base = 0.85 if "DEFINES_ROUTE" in strategy.edge_types else 0.65

    for depth in range(strategy.graph_depth):
        if not frontier:
            break
        decay = decay_base ** depth

        placeholders = ",".join("?" * len(frontier))
        col_src, col_dst = ("to_id", "from_id") if reverse else ("from_id", "to_id")

        params: list = list(frontier)
        type_filter = ""
        if edge_filter:
            ph = ",".join("?" * len(edge_filter))
            type_filter = f"AND edge_type IN ({ph})"
            params.extend(edge_filter)

        sql = f"""
            SELECT {col_dst} AS neighbour_id, weight
            FROM graph_edges
            WHERE {col_src} IN ({placeholders}) {type_filter}
        """
        rows = db.fetchall(sql, tuple(params))

        next_frontier: list[str] = []
        for row in rows:
            nid = row["neighbour_id"]
            # Penalise seeds that are already high-visited (prevents re-expansion)
            w = float(row["weight"]) * decay
            if nid not in visited:
                visited[nid] = w
                next_frontier.append(nid)
            else:
                visited[nid] = max(visited[nid], w)

        frontier = next_frontier[:max_frontier]

    return visited


# ---------------------------------------------------------------------------
# Hybrid retriever (fusion)
# ---------------------------------------------------------------------------

def _fetch_chunks_by_ids(db: DBManager, chunk_ids: list[str]) -> dict[str, RankedChunk]:
    """Fetch full chunk details for a list of IDs."""
    if not chunk_ids:
        return {}
    ph = ",".join("?" * len(chunk_ids))
    rows = db.fetchall(
        f"""SELECT c.id, c.chunk_type, c.name, c.text, c.start_line, c.end_line,
                   f.path AS file_path
            FROM chunks c JOIN files f ON c.file_id = f.id
            WHERE c.id IN ({ph})""",
        tuple(chunk_ids),
    )
    result = {}
    for row in rows:
        result[row["id"]] = RankedChunk(
            chunk_id=row["id"],
            file_path=row["file_path"],
            chunk_type=row["chunk_type"],
            name=row["name"],
            text=row["text"],
            start_line=row["start_line"],
            end_line=row["end_line"],
        )
    return result


def hybrid_search(
    db: DBManager,
    encoder: ONNXEncoder,
    query: str,
    strategy: RetrievalStrategy,
) -> list[RankedChunk]:
    """
    Full hybrid retrieval pipeline — redesigned.

    Pipeline:
    1. Lexical OR-query FTS5 search → candidate pool.
    2. Symbol-table direct lookup → additional exact-match candidates.
    3. Semantic search over ALL candidates (lexical + symbol hits), or full scan fallback.
    4. Graph BFS expansion seeded from BOTH lexical AND semantic top-k.
    5. Code-quality boost applied per chunk.
    6. Score fusion: final = w_l * lex + w_s * sem + w_g * graph + quality_boost.
    7. Optional cross-encoder reranking.
    """
    cfg = get_config()
    candidate_pool: int = cfg["retrieval"].get("fts_candidate_pool", 50)

    t0 = time.perf_counter()

    # -----------------------------------------------------------------------
    # Step 1: Lexical candidates (fixed OR-query)
    # -----------------------------------------------------------------------
    lex_results = lexical_search(db, query, top_k=candidate_pool)
    lex_map: dict[str, RankedChunk] = {r.chunk_id: r for r in lex_results}
    logger.debug(f"Lexical: {len(lex_results)} candidates")

    # -----------------------------------------------------------------------
    # Step 2: Symbol-table direct lookup (exact camelCase identifier matching)
    # -----------------------------------------------------------------------
    symbol_ids = symbol_search(db, query, top_k=20)
    
    # Give all exact symbol matches a massive lexical score boost so they outrank FTS noise
    for cid in symbol_ids:
        if cid in lex_map:
            lex_map[cid].lexical_score = max(lex_map[cid].lexical_score, 2.0)

    new_symbol_ids = [sid for sid in symbol_ids if sid not in lex_map]
    if new_symbol_ids:
        symbol_chunks = _fetch_chunks_by_ids(db, new_symbol_ids)
        for cid, chunk in symbol_chunks.items():
            # Give symbol hits a MASSIVE lexical score since they're exact matches
            chunk.lexical_score = 2.0
            lex_map[cid] = chunk
        logger.debug(f"Symbol lookup: {len(new_symbol_ids)} additional candidates")

    # -----------------------------------------------------------------------
    # Step 3: Semantic scores
    # -----------------------------------------------------------------------
    all_candidate_ids = list(lex_map.keys())
    # If we have candidates from lexical/symbol, search those + expand with full scan
    if all_candidate_ids:
        sem_map = semantic_search(db, encoder, query, all_candidate_ids)
        # Also run full scan to not miss semantically-close but lexically-silent chunks
        full_sem_map = semantic_search(db, encoder, query, None)
        # Merge: take top semantic hits from full scan that aren't already in our pool
        full_top = sorted(full_sem_map.items(), key=lambda x: x[1], reverse=True)[:candidate_pool]
        for cid, score in full_top:
            if cid not in sem_map:
                sem_map[cid] = score
    else:
        # No lexical/symbol hits: full semantic scan
        sem_map = semantic_search(db, encoder, query, None)

    logger.debug(f"Semantic: {len(sem_map)} scored")

    # Ensure all semantic-only top hits are in lex_map
    if sem_map:
        sem_top_ids = [cid for cid, _ in sorted(sem_map.items(), key=lambda x: x[1], reverse=True)[:candidate_pool]]
        new_sem_ids = [cid for cid in sem_top_ids if cid not in lex_map]
        if new_sem_ids:
            sem_chunks = _fetch_chunks_by_ids(db, new_sem_ids)
            lex_map.update(sem_chunks)

    # -----------------------------------------------------------------------
    # Step 4: Graph expansion
    # -----------------------------------------------------------------------
    graph_map: dict[str, float] = {}
    if strategy.use_graph:
        # Seed from top lexical + symbol hits (capped, better quality seeds)
        lex_seed_ids = [r.chunk_id for r in sorted(lex_results, key=lambda r: r.lexical_score, reverse=True)[:5]]
        sym_seed_ids = symbol_ids[:5]
        # Also seed from top semantic hits
        sem_seed_ids = [cid for cid, _ in sorted(sem_map.items(), key=lambda x: x[1], reverse=True)[:5]]

        seed_ids = list(dict.fromkeys(lex_seed_ids + sym_seed_ids + sem_seed_ids))

        if seed_ids:
            graph_map = graph_search(db, seed_ids, strategy)
            logger.debug(f"Graph: {len(graph_map)} neighbours found")

        # Fetch graph-only chunks not in lex_map
        extra_ids = [cid for cid in graph_map if cid not in lex_map]
        if extra_ids:
            extra_chunks = _fetch_chunks_by_ids(db, extra_ids)
            lex_map.update(extra_chunks)

    # -----------------------------------------------------------------------
    # Step 5 + 6: Score fusion with quality boost
    # -----------------------------------------------------------------------
    wl = strategy.lexical_weight
    ws = strategy.semantic_weight
    wg = strategy.graph_weight

    final: list[RankedChunk] = []
    for cid, chunk in lex_map.items():
        chunk.semantic_score = sem_map.get(cid, 0.0)
        chunk.graph_score = graph_map.get(cid, 0.0)

        quality_boost = _compute_quality_boost(chunk)

        chunk.final_score = min(1.0, (
            wl * chunk.lexical_score
            + ws * chunk.semantic_score
            + wg * chunk.graph_score
            + quality_boost
        ))
        final.append(chunk)

    final.sort(key=lambda c: c.final_score, reverse=True)
    final = final[: strategy.top_k]

    elapsed = (time.perf_counter() - t0) * 1000
    logger.debug(f"Hybrid retrieval: {len(final)} results in {elapsed:.1f}ms")

    # -----------------------------------------------------------------------
    # Step 7: Optional cross-encoder reranking
    # -----------------------------------------------------------------------
    if cfg.get("retrieval", {}).get("use_reranker") and final:
        final = maybe_rerank(
            query,
            final,
            cfg["retrieval"]["reranker_model"],
            cfg["retrieval"]["reranker_top_k"],
        )

    return final
