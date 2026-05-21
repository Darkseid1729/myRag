"""FastAPI server: index and query endpoints.

All routes are stateless with respect to open DB connections — every request
opens and closes its own DBManager instance via ``registry.get_or_create()``.

Streaming responses (/ask with stream=True) deliberately do NOT close the DB
inside the streaming generator, because the generator runs after the response
is sent.  Instead, the DB is closed after the generator is exhausted.
"""

from __future__ import annotations

import json
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator

from src.config import get_config, get_log_level
from src.utils import setup_logging, get_logger, sha256_of_string, sha1_of_string, current_rss_mb
from src.storage.project_registry import ProjectRegistry
from src.embeddings.onnx_encoder import ONNXEncoder
from src.indexer.indexing_pipeline import index_project
from src.intent.intent_router import IntentRouter
from src.retriever.hybrid_retriever import hybrid_search, RankedChunk
from src.context.builder import build_context
from src.llm.manager import generate as llm_generate
from src.plugins.manager import PluginManager

# Boot logging before anything else
setup_logging(get_log_level())
logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Application singletons (created once per process)
# ---------------------------------------------------------------------------

registry = ProjectRegistry()
encoder = ONNXEncoder()
router_instance = IntentRouter(encoder=encoder)
plugins = PluginManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("MyRAG server starting up…")
    yield
    logger.info("MyRAG server shut down.")


app = FastAPI(
    title="MyRAG API",
    description="Memory-efficient local RAG for Vite + React codebases",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Global exception handler
# ---------------------------------------------------------------------------

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled error on {request.url}: {exc}", exc_info=True)
    return JSONResponse(status_code=500, content={"detail": str(exc)})


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class IndexRequest(BaseModel):
    project_root: str = Field(..., description="Absolute path to the Vite+React project")
    force_reindex: bool = Field(False, description="Re-index all files even if unchanged")

    @field_validator("project_root")
    @classmethod
    def root_must_exist(cls, v: str) -> str:
        if not Path(v).exists():
            raise ValueError(f"Path does not exist: {v}")
        return v


class IndexResponse(BaseModel):
    status: str
    project_id: str
    stats: dict[str, Any]


class QueryRequest(BaseModel):
    project_root: str
    query: str = Field(..., min_length=1, max_length=1000)
    top_k: int = Field(10, ge=1, le=50)


class ChunkResult(BaseModel):
    chunk_id: str
    file_path: str
    chunk_type: str
    name: str | None
    start_line: int
    end_line: int
    text: str
    final_score: float
    lexical_score: float
    semantic_score: float
    graph_score: float


class QueryResponse(BaseModel):
    query: str
    intent: str
    confidence: float
    results: list[ChunkResult]
    elapsed_ms: int


class AskRequest(BaseModel):
    project_root: str
    query: str = Field(..., min_length=1, max_length=1000)
    top_k: int = Field(10, ge=1, le=50)
    stream: bool = False


class AskResponse(BaseModel):
    query: str
    answer: str
    results: list[ChunkResult]


class ProjectListItem(BaseModel):
    project_id: str
    db_path: str
    size_bytes: int


class StatsResponse(BaseModel):
    rss_mb: float
    projects: int
    version: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_chunk_results(chunks: list[RankedChunk]) -> list[ChunkResult]:
    return [
        ChunkResult(
            chunk_id=c.chunk_id,
            file_path=c.file_path,
            chunk_type=c.chunk_type,
            name=c.name,
            start_line=c.start_line,
            end_line=c.end_line,
            text=c.text,
            final_score=round(c.final_score, 4),
            lexical_score=round(c.lexical_score, 4),
            semantic_score=round(c.semantic_score, 4),
            graph_score=round(c.graph_score, 4),
        )
        for c in chunks
    ]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}


@app.get("/stats", response_model=StatsResponse)
async def stats():
    return StatsResponse(
        rss_mb=round(current_rss_mb(), 2),
        projects=len(registry.list_projects()),
        version="1.0.0",
    )


@app.get("/", response_class=HTMLResponse)
async def ui():
    ui_path = Path(__file__).resolve().parent.parent / "web" / "ui.html"
    if not ui_path.exists():
        return HTMLResponse("<h1>MyRAG</h1><p>UI not found.</p>")
    return HTMLResponse(ui_path.read_text(encoding="utf-8"))


@app.post("/index", response_model=IndexResponse)
async def index(req: IndexRequest):
    db = registry.get_or_create(req.project_root)
    try:
        if req.force_reindex:
            for table in ("chunks", "files", "embeddings", "graph_edges",
                          "routes", "symbols", "api_calls", "summaries",
                          "retrieval_cache"):
                try:
                    db.execute(f"DELETE FROM {table}")
                except Exception:
                    pass
            # FTS5 must be cleared separately
            try:
                db.execute("DELETE FROM fts_chunks")
            except Exception:
                pass
            db.commit()

        stats = index_project(req.project_root, db, encoder)
        project_id = sha1_of_string(str(Path(req.project_root).resolve()))
        return IndexResponse(status="indexed", project_id=project_id, stats=stats)
    except Exception as exc:
        logger.error(f"Indexing failed for {req.project_root}: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        db.close()


@app.post("/query", response_model=QueryResponse)
async def query(req: QueryRequest):
    t0 = time.perf_counter()
    db = registry.get_or_create(req.project_root)
    try:
        # Check retrieval cache
        cache_key = sha256_of_string(f"{req.project_root}::{req.query}::{req.top_k}")
        cached = db.fetchone(
            "SELECT result_json FROM retrieval_cache WHERE query_hash=?", (cache_key,)
        )
        if cached:
            db.execute(
                "UPDATE retrieval_cache SET hit_count=hit_count+1 WHERE query_hash=?",
                (cache_key,),
            )
            db.commit()
            data = json.loads(cached["result_json"])
            # Update elapsed_ms with fresh timing
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            data["elapsed_ms"] = elapsed_ms
            return QueryResponse(**data)

        # Route
        decision = router_instance.route(req.query)
        decision.strategy.top_k = req.top_k

        # Hybrid retrieval
        chunks = hybrid_search(db, encoder, decision.expanded_query, decision.strategy)
        elapsed_ms = int((time.perf_counter() - t0) * 1000)

        results = _to_chunk_results(chunks)
        response = QueryResponse(
            query=req.query,
            intent=decision.intent.value,
            confidence=round(decision.confidence, 3),
            results=results,
            elapsed_ms=elapsed_ms,
        )

        plugins.on_results(req.query, results)

        # Store in cache
        db.execute(
            """INSERT OR REPLACE INTO retrieval_cache
               (query_hash, result_json, created_at, hit_count)
               VALUES (?,?,?,?)""",
            (cache_key, response.model_dump_json(), int(time.time()), 0),
        )
        db.commit()
        return response

    except Exception as exc:
        logger.error(f"Query failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        db.close()


@app.post("/ask")
async def ask(req: AskRequest):
    db = registry.get_or_create(req.project_root)
    try:
        decision = router_instance.route(req.query)
        decision.strategy.top_k = req.top_k

        chunks = hybrid_search(db, encoder, decision.expanded_query, decision.strategy)
        results = _to_chunk_results(chunks)

        cfg = get_config()
        prompt = build_context(req.query, chunks, max_tokens=cfg["llm"]["max_context_tokens"])
        prompt = plugins.on_prompt(prompt)

        try:
            if req.stream:
                # For streaming: close DB now (chunks already fetched) and stream tokens
                db.close()
                db = None  # type: ignore[assignment]

                stream = llm_generate(prompt, stream=True)

                async def token_generator() -> AsyncIterator[str]:
                    for token in stream:
                        yield token

                return StreamingResponse(token_generator(), media_type="text/plain")

            answer = llm_generate(prompt, stream=False)
            return AskResponse(query=req.query, answer=str(answer), results=results)

        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Ask failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        if db is not None:
            db.close()


@app.get("/projects", response_model=list[ProjectListItem])
async def list_projects():
    return [
        ProjectListItem(
            project_id=p["project_id"],
            db_path=p["db_path"],
            size_bytes=p.get("size_bytes", 0),
        )
        for p in registry.list_projects()
    ]


@app.delete("/project")
async def delete_project(project_root: str):
    removed = registry.delete_project(project_root)
    if not removed:
        raise HTTPException(status_code=404, detail="Project not found in registry")
    return {"status": "deleted", "project_root": project_root}


@app.get("/graph")
async def get_graph(project_root: str, depth: int = 2):
    db = registry.get_or_create(project_root)
    try:
        edges = db.fetchall(
            "SELECT from_id, to_id, edge_type, weight FROM graph_edges LIMIT 1000"
        )
        # Fetch node labels for the UI
        node_ids = set()
        for e in edges:
            node_ids.add(e["from_id"])
            node_ids.add(e["to_id"])

        nodes: list[dict] = []
        if node_ids:
            ph = ",".join("?" * len(node_ids))
            chunk_rows = db.fetchall(
                f"SELECT id, name, chunk_type FROM chunks WHERE id IN ({ph})",
                tuple(node_ids),
            )
            nodes = [
                {"id": r["id"], "label": r["name"] or r["chunk_type"], "type": r["chunk_type"]}
                for r in chunk_rows
            ]

        return {
            "nodes": nodes,
            "edges": [dict(e) for e in edges],
            "total_edges": len(edges),
        }
    finally:
        db.close()


@app.get("/project/meta")
async def project_meta(project_root: str):
    """Return indexing metadata for a project."""
    db = registry.get_or_create(project_root)
    try:
        rows = db.fetchall("SELECT key, value FROM indexing_metadata")
        meta = {r["key"]: r["value"] for r in rows}

        file_count = db.fetchone("SELECT COUNT(*) as n FROM files")
        chunk_count = db.fetchone("SELECT COUNT(*) as n FROM chunks")
        edge_count = db.fetchone("SELECT COUNT(*) as n FROM graph_edges")

        meta["db_file_count"] = str(file_count["n"] if file_count else 0)
        meta["db_chunk_count"] = str(chunk_count["n"] if chunk_count else 0)
        meta["db_edge_count"] = str(edge_count["n"] if edge_count else 0)
        return meta
    finally:
        db.close()
