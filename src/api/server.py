"""FastAPI server: index and query endpoints."""

from __future__ import annotations

import json
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.config import get_config
from src.storage.project_registry import ProjectRegistry
from src.embeddings.onnx_encoder import ONNXEncoder
from src.indexer.indexing_pipeline import index_project
from src.intent.intent_router import IntentRouter
from src.retriever.hybrid_retriever import hybrid_search, RankedChunk
from src.utils import get_logger, sha256_of_string

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Application state (singletons)
# ---------------------------------------------------------------------------

registry = ProjectRegistry()
encoder = ONNXEncoder()
router_instance = IntentRouter(encoder=encoder)


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
# Request / Response models
# ---------------------------------------------------------------------------

class IndexRequest(BaseModel):
    project_root: str = Field(..., description="Absolute path to the Vite+React project")
    force_reindex: bool = Field(False, description="Re-index all files even if unchanged")


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


class ProjectListItem(BaseModel):
    project_id: str
    db_path: str
    size_bytes: int


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}


@app.post("/index", response_model=IndexResponse)
async def index(req: IndexRequest):
    if not Path(req.project_root).exists():
        raise HTTPException(status_code=400, detail=f"Path not found: {req.project_root}")

    db = registry.get_or_create(req.project_root)
    try:
        stats = index_project(req.project_root, db, encoder)
        from src.utils import sha1_of_string
        project_id = sha1_of_string(str(Path(req.project_root).resolve()))
        return IndexResponse(status="indexed", project_id=project_id, stats=stats)
    finally:
        db.close()


@app.post("/query", response_model=QueryResponse)
async def query(req: QueryRequest):
    t0 = time.perf_counter()

    db = registry.get_or_create(req.project_root)
    try:
        # Check cache
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
            return QueryResponse(**data)

        # Route
        decision = router_instance.route(req.query)

        # Override top_k from request
        decision.strategy.top_k = req.top_k

        # Hybrid retrieval
        chunks: list[RankedChunk] = hybrid_search(
            db, encoder, decision.expanded_query, decision.strategy
        )

        elapsed_ms = int((time.perf_counter() - t0) * 1000)

        results = [
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

        response = QueryResponse(
            query=req.query,
            intent=decision.intent.value,
            confidence=round(decision.confidence, 3),
            results=results,
            elapsed_ms=elapsed_ms,
        )

        # Store in cache
        db.execute(
            """INSERT OR REPLACE INTO retrieval_cache
               (query_hash, result_json, created_at, hit_count)
               VALUES (?,?,?,?)""",
            (cache_key, response.model_dump_json(), int(time.time()), 0),
        )
        db.commit()

        return response

    finally:
        db.close()


@app.get("/projects", response_model=list[ProjectListItem])
async def list_projects():
    return [
        ProjectListItem(**p)
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
            "SELECT from_id, to_id, edge_type, weight FROM graph_edges LIMIT 500"
        )
        return {
            "edges": [dict(e) for e in edges],
            "total": len(edges),
        }
    finally:
        db.close()
