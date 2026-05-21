"""Main indexing pipeline: scan → parse → chunk → embed → store.

Data flow:
1. FileScanner discovers all JS/TS/JSX/TSX source files.
2. ``detect_changed_files`` compares content hashes for incremental indexing.
3. For each changed file:
   a. Old chunks, FTS rows, symbols, embeddings, api_calls are deleted.
   b. File record is upserted.
   c. Tree-sitter parser (or regex fallback) extracts ParsedChunks.
   d. Chunker splits oversized chunks with overlap.
   e. Each chunk is stored: chunks table, FTS5, symbols, embeddings.
   f. API calls are extracted and stored.
4. After all files: graph edges are extracted in a second pass.
5. Retrieval cache is invalidated (stale results for new code).
"""

from __future__ import annotations

import time
from pathlib import Path

from src.scanner.file_scanner import scan_project, ScannedFile, detect_changed_files
from src.parser.tree_sitter_parser import parse_file, ParsedChunk
from src.chunker.chunker import chunk_all, Chunk
from src.extractor.api_extractor import extract_api_calls
from src.graph.graph_builder import extract_graph_edges
from src.embeddings.onnx_encoder import ONNXEncoder
from src.storage.db_manager import DBManager
from src.plugins.manager import PluginManager
from src.utils import sha1_of_string, get_logger, count_tokens_approx, split_camel_case
from src.config import get_config

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# File-level upsert
# ---------------------------------------------------------------------------

def _upsert_file(db: DBManager, sf: ScannedFile) -> None:
    db.execute(
        """INSERT OR REPLACE INTO files
           (id, path, file_type, size_bytes, line_count, content_hash, indexed_at, modified_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (sf.id, sf.path, sf.file_type, sf.size_bytes, sf.line_count,
         sf.content_hash, sf.indexed_at, sf.modified_at),
    )


def _delete_old_data(db: DBManager, file_id: str) -> None:
    """Remove all stale data for a file before re-indexing it.

    Order matters:
    1. Collect chunk IDs first (needed for FTS5 manual delete).
    2. Delete api_calls (FK to chunks).
    3. Delete FTS5 rows explicitly (no FK cascade on virtual tables).
    4. Delete chunks (cascades to symbols, embeddings via FK).
    5. Delete graph edges that originated from this file.
    """
    rows = db.fetchall("SELECT id FROM chunks WHERE file_id = ?", (file_id,))
    chunk_ids = [r["id"] for r in rows]

    if chunk_ids:
        db.delete_fts_for_chunks(chunk_ids)
        ph = ",".join("?" * len(chunk_ids))
        db.execute(f"DELETE FROM api_calls WHERE chunk_id IN ({ph})", tuple(chunk_ids))

    db.execute("DELETE FROM chunks WHERE file_id = ?", (file_id,))
    db.execute("DELETE FROM graph_edges WHERE from_id = ?", (file_id,))


# ---------------------------------------------------------------------------
# Summary generation
# ---------------------------------------------------------------------------

def _generate_summary(chunk: Chunk) -> str:
    """Rule-based compact summary; no LLM required."""
    lines = chunk.text.strip().splitlines()
    first = lines[0].strip() if lines else ""
    name_part = f"`{chunk.name}`" if chunk.name else "anonymous"
    return f"{chunk.chunk_type} {name_part} — {first[:80]}"


# ---------------------------------------------------------------------------
# Store a single chunk
# ---------------------------------------------------------------------------

def _store_chunk(
    db: DBManager,
    file_id: str,
    chunk: Chunk,
    encoder: ONNXEncoder,
    cfg: dict,
) -> str:
    """Persist one chunk with its FTS entry, symbols, and embedding.

    Returns the chunk_id or empty string if the chunk was rejected.
    """
    chunk_id = sha1_of_string(f"{file_id}:{chunk.start_line}:{chunk.name or ''}")

    summary = _generate_summary(chunk)

    db.execute(
        """INSERT OR REPLACE INTO chunks
           (id, file_id, chunk_type, name, text, start_line, end_line, char_count, summary, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (chunk_id, file_id, chunk.chunk_type, chunk.name, chunk.text,
         chunk.start_line, chunk.end_line, len(chunk.text), summary, int(time.time())),
    )

    # FTS5 — include camelCase-expanded symbol names for better tokenisation
    symbol_text = " ".join(chunk.symbols)
    camel_expanded = " ".join(split_camel_case(s) for s in chunk.symbols)
    fts_symbols = f"{symbol_text} {camel_expanded}".strip()
    db.execute(
        "INSERT INTO fts_chunks(chunk_id, text, symbols, summary) VALUES (?,?,?,?)",
        (chunk_id, chunk.text, fts_symbols, summary or ""),
    )

    # Symbols table
    for sym in chunk.symbols:
        is_exported = 1 if any(
            kw in chunk.text[:100] for kw in ("export ", "module.exports")
        ) else 0
        is_default = 1 if "export default" in chunk.text[:100] else 0
        db.execute(
            """INSERT INTO symbols (chunk_id, name, symbol_type, is_exported, is_default_export)
               VALUES (?,?,?,?,?)""",
            (chunk_id, sym, chunk.chunk_type, is_exported, is_default),
        )

    # Embedding
    qv = encoder.encode_and_quantize(chunk.text)
    db.execute(
        """INSERT OR REPLACE INTO embeddings (chunk_id, vector, scale, model_id, created_at)
           VALUES (?,?,?,?,?)""",
        (chunk_id, qv.data, qv.scale, encoder._model_id, int(time.time())),
    )

    return chunk_id


# ---------------------------------------------------------------------------
# Store API calls for a chunk
# ---------------------------------------------------------------------------

def _store_api_calls(db: DBManager, chunk_id: str, chunk_text: str) -> None:
    calls = extract_api_calls(chunk_text)
    for call in calls:
        try:
            db.execute(
                """INSERT INTO api_calls (chunk_id, method, endpoint, client_type, is_dynamic)
                   VALUES (?,?,?,?,?)""",
                (chunk_id, call.method, call.endpoint, call.client_type, int(call.is_dynamic)),
            )
        except Exception as exc:
            logger.debug(f"API call insert failed: {exc}")


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def index_project(project_root: str, db: DBManager, encoder: ONNXEncoder) -> dict:
    """Index a project directory end-to-end.

    Steps:
    1. Scan the project for source files.
    2. Identify files that have changed since last index.
    3. For each changed file: delete stale data, re-parse, re-embed.
    4. Extract graph edges across all re-indexed files.
    5. Invalidate retrieval cache (stale results removed).
    6. Persist metadata and return stats dict.

    Args:
        project_root: Absolute path to the project directory.
        db: Connected DBManager for this project's SQLite file.
        encoder: ONNX encoder for embedding generation.

    Returns:
        Dict with keys: files_scanned, files_indexed, chunks_indexed, elapsed_ms.
    """
    t0 = time.perf_counter()
    root = Path(project_root).resolve()
    cfg = get_config()

    # 1. Scan
    all_files = scan_project(root)

    # 2. Detect changes (incremental indexing)
    existing_hashes = {
        row["id"]: row["content_hash"]
        for row in db.fetchall("SELECT id, content_hash FROM files")
    }
    changed = detect_changed_files(all_files, existing_hashes)
    logger.info(
        f"Indexing {len(changed)} changed files out of {len(all_files)} total "
        f"in {root.name}"
    )

    chunk_count = 0
    plugins = PluginManager()
    all_stored: list[tuple[str, str, list[tuple[str, Chunk]]]] = []
    # (file_id, file_path, [(chunk_id, chunk)])

    for sf in changed:
        try:
            logger.debug(f"  Indexing: {sf.path}")

            # Delete stale data for this file
            _delete_old_data(db, sf.id)

            # Upsert file record
            _upsert_file(db, sf)

            # Parse → chunk → store
            parsed_chunks: list[ParsedChunk] = parse_file(sf.abs_path)
            chunks: list[Chunk] = chunk_all(parsed_chunks)

            stored_chunks: list[tuple[str, Chunk]] = []
            for chunk in chunks:
                try:
                    cid = _store_chunk(db, sf.id, chunk, encoder, cfg)
                    if cid:
                        chunk.metadata["chunk_id"] = cid
                        stored_chunks.append((cid, chunk))
                        chunk_count += 1
                        _store_api_calls(db, cid, chunk.text)
                        plugins.on_chunk(chunk)
                except Exception as exc:
                    logger.warning(f"    Chunk storage failed ({chunk.name}): {exc}")

            all_stored.append((sf.id, sf.path, stored_chunks))

        except Exception as exc:
            logger.error(f"Error indexing {sf.path}: {exc}")
            continue

    # 3. Graph edges (second pass, after all chunks are stored)
    for file_id, file_path, stored_chunks in all_stored:
        try:
            extract_graph_edges(db, file_id, stored_chunks)
        except Exception as exc:
            logger.warning(f"Graph extraction failed for {file_path}: {exc}")

    # 4. Invalidate retrieval cache
    db.invalidate_cache()

    db.commit()

    elapsed_ms = int((time.perf_counter() - t0) * 1000)

    # 5. Persist metadata
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
