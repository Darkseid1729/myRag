"""Main indexing pipeline: scan → parse → chunk → embed → store."""

from __future__ import annotations

import time
from pathlib import Path

from src.scanner.file_scanner import scan_project, ScannedFile, detect_changed_files
from src.parser.tree_sitter_parser import parse_file, ParsedChunk
from src.embeddings.onnx_encoder import ONNXEncoder
from src.storage.db_manager import DBManager
from src.utils import sha1_of_string, get_logger, count_tokens_approx

logger = get_logger(__name__)

_MAX_CHUNK_TOKENS = 300
_MIN_CHUNK_TOKENS = 20


# ---------------------------------------------------------------------------
# Helper: store a single file record
# ---------------------------------------------------------------------------

def _upsert_file(db: DBManager, sf: ScannedFile) -> None:
    db.execute(
        """INSERT OR REPLACE INTO files
           (id, path, file_type, size_bytes, line_count, content_hash, indexed_at, modified_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (sf.id, sf.path, sf.file_type, sf.size_bytes, sf.line_count,
         sf.content_hash, sf.indexed_at, sf.modified_at),
    )


def _delete_old_chunks(db: DBManager, file_id: str) -> None:
    """Remove previously indexed chunks (and cascades to embeddings, fts, symbols)."""
    db.execute("DELETE FROM chunks WHERE file_id = ?", (file_id,))
    db.execute("DELETE FROM fts_chunks WHERE chunk_id NOT IN (SELECT id FROM chunks)")


def _store_chunk(
    db: DBManager,
    file_id: str,
    chunk: ParsedChunk,
    encoder: ONNXEncoder,
) -> str:
    chunk_id = sha1_of_string(f"{file_id}:{chunk.start_line}")

    # Filter by token count
    token_count = count_tokens_approx(chunk.text)
    if token_count < _MIN_CHUNK_TOKENS:
        return ""

    # Truncate oversized chunks
    text = chunk.text
    if token_count > _MAX_CHUNK_TOKENS:
        text = text[: _MAX_CHUNK_TOKENS * 4]

    summary = _generate_summary(chunk)

    db.execute(
        """INSERT OR REPLACE INTO chunks
           (id, file_id, chunk_type, name, text, start_line, end_line, char_count, summary, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (chunk_id, file_id, chunk.chunk_type, chunk.name, text,
         chunk.start_line, chunk.end_line, len(text), summary, int(time.time())),
    )

    # FTS5
    symbols_str = " ".join(chunk.symbols)
    db.execute(
        "INSERT INTO fts_chunks(chunk_id, text, symbols, summary) VALUES (?,?,?,?)",
        (chunk_id, text, symbols_str, summary or ""),
    )

    # Symbols table
    for sym in chunk.symbols:
        db.execute(
            """INSERT INTO symbols (chunk_id, name, symbol_type, is_exported)
               VALUES (?,?,?,?)""",
            (chunk_id, sym, chunk.chunk_type, 1 if "export" in text[:50] else 0),
        )

    # Embedding
    qv = encoder.encode_and_quantize(text)
    cfg_model = encoder._model_id
    db.execute(
        """INSERT OR REPLACE INTO embeddings (chunk_id, vector, scale, model_id, created_at)
           VALUES (?,?,?,?,?)""",
        (chunk_id, qv.data, qv.scale, cfg_model, int(time.time())),
    )

    return chunk_id


def _generate_summary(chunk: ParsedChunk) -> str:
    """Rule-based compact summary; no LLM needed."""
    lines = chunk.text.strip().splitlines()
    first = lines[0].strip() if lines else ""
    name_part = f"`{chunk.name}`" if chunk.name else "anonymous"
    return f"{chunk.chunk_type} {name_part} — {first[:80]}"


# ---------------------------------------------------------------------------
# Graph edge extraction from import statements
# ---------------------------------------------------------------------------

import re as _re
_IMPORT_FROM_RE = _re.compile(r"from\s+['\"]([^'\"]+)['\"]")


def _extract_graph_edges(
    db: DBManager,
    file_id: str,
    chunks: list[ParsedChunk],
    project_root: str,
) -> None:
    """Build IMPORTS edges from import blocks."""
    for chunk in chunks:
        if chunk.chunk_type != "IMPORT_BLOCK":
            continue
        for match in _IMPORT_FROM_RE.finditer(chunk.text):
            import_path = match.group(1)
            if import_path.startswith("."):
                # Resolve relative import → file_id
                target_id = sha1_of_string(import_path)
                db.execute(
                    """INSERT INTO graph_edges (from_id, to_id, edge_type, weight)
                       VALUES (?,?,?,?)""",
                    (file_id, target_id, "IMPORTS", 1.0),
                )


# ---------------------------------------------------------------------------
# Main indexing orchestrator
# ---------------------------------------------------------------------------

def index_project(project_root: str, db: DBManager, encoder: ONNXEncoder) -> dict:
    t0 = time.perf_counter()
    root = Path(project_root).resolve()

    # 1. Scan
    all_files = scan_project(root)

    # 2. Detect changes (incremental)
    existing_hashes = {
        row["id"]: row["content_hash"]
        for row in db.fetchall("SELECT id, content_hash FROM files")
    }
    changed = detect_changed_files(all_files, existing_hashes)
    logger.info(f"Files to index: {len(changed)} / {len(all_files)} total")

    chunk_count = 0

    for sf in changed:
        try:
            # Delete stale data for this file
            _delete_old_chunks(db, sf.id)

            # Upsert file record
            _upsert_file(db, sf)

            # Parse
            parsed_chunks = parse_file(sf.abs_path)

            # Store chunks + embeddings
            for pc in parsed_chunks:
                cid = _store_chunk(db, sf.id, pc, encoder)
                if cid:
                    chunk_count += 1

            # Graph edges
            _extract_graph_edges(db, sf.id, parsed_chunks, str(root))

        except Exception as exc:
            logger.error(f"Error indexing {sf.path}: {exc}")
            continue

    db.commit()

    elapsed_ms = int((time.perf_counter() - t0) * 1000)

    # Update metadata
    db.set_meta("project_root", str(root))
    db.set_meta("indexed_at", str(int(time.time())))
    db.set_meta("file_count", str(len(all_files)))
    db.set_meta("chunk_count", str(chunk_count))
    db.set_meta("total_index_ms", str(elapsed_ms))
    db.commit()

    stats = {
        "files_scanned": len(all_files),
        "files_indexed": len(changed),
        "chunks_indexed": chunk_count,
        "elapsed_ms": elapsed_ms,
    }
    logger.info(f"Indexing complete: {stats}")
    return stats
