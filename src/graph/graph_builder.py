"""Graph builder: extracts and stores dependency edges between code chunks.

This module centralises all graph edge extraction logic that was previously
scattered inside ``indexing_pipeline.py`` as regex hacks.

Edge types stored:
- IMPORTS    — file imports another file (static import statement)
- USES_HOOK  — component/function calls a custom hook
- RENDERS    — component renders another component (JSX)
- DEFINES_ROUTE — component defines a <Route> that maps to another component
- CONSUMES_CONTEXT — component uses a React context
- MANAGES_STATE   — component or hook manages state (useState/useReducer)

Design:
- All edge extraction is idempotent (uses INSERT OR IGNORE)
- Duplicate edges (same from→to→type) are deduplicated in the DB via unique index
- Weights are used by the BFS retriever to rank relevance
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.storage.db_manager import DBManager
from src.utils import sha1_of_string, get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Regex patterns — compiled once at module load
# ---------------------------------------------------------------------------

_IMPORT_FROM_RE = re.compile(r"""from\s+['"]([^'"]+)['"]""")
_HOOK_CALL_RE = re.compile(r"\b(use[A-Z]\w+)\b")
_JSX_TAG_RE = re.compile(r"<([A-Z][A-Za-z0-9_]*)\b")
_ROUTE_RE = re.compile(
    r"<Route[^>]*path=['\"]([^'\"]+)['\"][^>]*element=\{\s*<\s*([A-Z][A-Za-z0-9_]*)"
)
_USE_CONTEXT_RE = re.compile(r"useContext\((\w+)\)")
_USE_STATE_RE = re.compile(r"\b(useState|useReducer)\b")


@dataclass
class GraphEdge:
    from_id: str
    to_id: str
    edge_type: str
    weight: float = 1.0


# ---------------------------------------------------------------------------
# Symbol resolution
# ---------------------------------------------------------------------------

def _resolve_symbol(db: DBManager, name: str, symbol_type: str) -> str | None:
    """Look up a symbol name in the symbols table and return its chunk_id."""
    row = db.fetchone(
        "SELECT chunk_id FROM symbols WHERE name=? AND symbol_type=? LIMIT 1",
        (name, symbol_type),
    )
    return row["chunk_id"] if row else None


def _resolve_any_symbol(db: DBManager, name: str) -> str | None:
    """Look up a symbol by name in any symbol type."""
    row = db.fetchone(
        "SELECT chunk_id FROM symbols WHERE name=? LIMIT 1",
        (name,),
    )
    return row["chunk_id"] if row else None


# ---------------------------------------------------------------------------
# Edge insertion helper
# ---------------------------------------------------------------------------

def _insert_edge(
    db: DBManager,
    from_id: str,
    to_id: str,
    edge_type: str,
    weight: float = 1.0,
) -> None:
    """Insert a graph edge, silently ignoring duplicates."""
    if from_id == to_id:
        return  # No self-loops
    try:
        db.execute(
            """INSERT OR IGNORE INTO graph_edges (from_id, to_id, edge_type, weight)
               VALUES (?,?,?,?)""",
            (from_id, to_id, edge_type, weight),
        )
    except Exception as exc:
        logger.debug(f"Edge insert failed ({from_id}→{to_id} {edge_type}): {exc}")


# ---------------------------------------------------------------------------
# Route extraction
# ---------------------------------------------------------------------------

def _resolve_component(db: DBManager, name: str) -> str | None:
    """Resolve a component/function name to its chunk_id.

    Priority:
    1. Exact chunk.name match (most reliable — the defining chunk)
    2. Symbol with COMPONENT type
    3. Symbol with HOOK or FUNCTION type
    4. Any symbol with matching name
    """
    # 1. Exact name match on the chunks table — this is the defining chunk
    row = db.fetchone(
        "SELECT id FROM chunks WHERE name=? AND chunk_type IN ('COMPONENT','HOOK','FUNCTION') LIMIT 1",
        (name,),
    )
    if row:
        return row["id"]

    # 2. Symbol lookup by type priority
    for sym_type in ("COMPONENT", "HOOK", "FUNCTION"):
        row = db.fetchone(
            "SELECT chunk_id FROM symbols WHERE name=? AND symbol_type=? LIMIT 1",
            (name, sym_type),
        )
        if row:
            return row["chunk_id"]

    # 3. Any symbol type
    row = db.fetchone("SELECT chunk_id FROM symbols WHERE name=? LIMIT 1", (name,))
    return row["chunk_id"] if row else None


def _extract_routes(
    db: DBManager,
    chunk_id: str,
    chunk_text: str,
    primary_component_id: str | None,
) -> None:
    """Extract <Route> definitions and insert into the routes table."""
    for path, comp in _ROUTE_RE.findall(chunk_text):
        target = _resolve_component(db, comp)
        if not target:
            logger.debug(f"Route target '{comp}' not resolved for path '{path}'")
            continue
        source_id = primary_component_id or chunk_id
        route_id = sha1_of_string(f"{path}:{comp}")
        try:
            db.execute(
                """INSERT OR REPLACE INTO routes
                   (id, path, component, chunk_id, is_protected, parent_route, metadata)
                   VALUES (?,?,?,?,?,?,?)""",
                (route_id, path, comp, target, 0, None, None),
            )
        except Exception as exc:
            logger.debug(f"Route insert failed ({path}): {exc}")
        # Edge from the App/Router chunk to the target component
        _insert_edge(db, source_id, target, "DEFINES_ROUTE", 1.0)
        # Also edge from the file itself so file-level queries find it
        _insert_edge(db, chunk_id, target, "DEFINES_ROUTE", 0.9)


# ---------------------------------------------------------------------------
# Main extraction function
# ---------------------------------------------------------------------------

def extract_graph_edges(
    db: DBManager,
    file_id: str,
    stored_chunks: list[tuple[str, object]],  # (chunk_id, ParsedChunk-like)
) -> None:
    """Build and store all graph edges for a set of indexed chunks.

    Args:
        db: Connected DBManager instance.
        file_id: The SHA1 ID of the source file.
        stored_chunks: List of (chunk_id, chunk) pairs as stored in the DB.
    """
    # Find the primary component of this file (first COMPONENT chunk)
    primary_component_id: str | None = None
    for cid, c in stored_chunks:
        if getattr(c, "chunk_type", "") == "COMPONENT":
            primary_component_id = cid
            break

    for chunk_id, chunk in stored_chunks:
        chunk_type = getattr(chunk, "chunk_type", "")
        chunk_text = getattr(chunk, "text", "")

        # ------------------------------------------------------------------
        # Import edges (file → imported file)
        # ------------------------------------------------------------------
        if chunk_type == "IMPORT_BLOCK":
            for m in _IMPORT_FROM_RE.finditer(chunk_text):
                import_path = m.group(1)
                if import_path.startswith("."):
                    # Resolve to a stable ID (same hash as scanner uses)
                    target_id = sha1_of_string(import_path)
                    _insert_edge(db, file_id, target_id, "IMPORTS", 1.0)
            continue  # Don't process other edge types for import blocks

        # ------------------------------------------------------------------
        # Hook usage edges
        # ------------------------------------------------------------------
        for hook in set(_HOOK_CALL_RE.findall(chunk_text)):
            target = _resolve_symbol(db, hook, "HOOK")
            if target and target != chunk_id:
                _insert_edge(db, chunk_id, target, "USES_HOOK", 0.9)

        # ------------------------------------------------------------------
        # Context consumption edges
        # ------------------------------------------------------------------
        for ctx in set(_USE_CONTEXT_RE.findall(chunk_text)):
            target = _resolve_any_symbol(db, ctx)
            if target and target != chunk_id:
                _insert_edge(db, chunk_id, target, "CONSUMES_CONTEXT", 0.8)

        # ------------------------------------------------------------------
        # JSX render edges (component renders another component)
        # ------------------------------------------------------------------
        if chunk_type in ("COMPONENT", "FUNCTION"):
            for comp in set(_JSX_TAG_RE.findall(chunk_text)):
                target = _resolve_symbol(db, comp, "COMPONENT")
                if target and target != chunk_id:
                    _insert_edge(db, chunk_id, target, "RENDERS", 0.7)

        # ------------------------------------------------------------------
        # State management edges (signals render-dependency for re-render analysis)
        # ------------------------------------------------------------------
        if _USE_STATE_RE.search(chunk_text):
            _insert_edge(db, chunk_id, chunk_id, "MANAGES_STATE", 0.5)

        # ------------------------------------------------------------------
        # Route definitions
        # ------------------------------------------------------------------
        _extract_routes(db, chunk_id, chunk_text, primary_component_id)
