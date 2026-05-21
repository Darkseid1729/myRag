"""Simple benchmark runner for MyRAG indexing and querying."""

from __future__ import annotations

import time
from pathlib import Path

from src.embeddings.onnx_encoder import ONNXEncoder
from src.indexer.indexing_pipeline import index_project
from src.intent.intent_router import IntentRouter
from src.retriever.hybrid_retriever import hybrid_search
from src.storage.project_registry import ProjectRegistry
from src.utils import current_rss_mb


def main(project_root: str, query: str = "login") -> None:
    root = str(Path(project_root).resolve())
    registry = ProjectRegistry()
    encoder = ONNXEncoder()

    t0 = time.perf_counter()
    db = registry.get_or_create(root)
    stats = index_project(root, db, encoder)
    t_index = (time.perf_counter() - t0) * 1000

    router = IntentRouter(encoder=encoder)
    decision = router.route(query)
    t1 = time.perf_counter()
    results = hybrid_search(db, encoder, decision.expanded_query, decision.strategy)
    t_query = (time.perf_counter() - t1) * 1000

    print(f"Indexing ms: {t_index:.1f} | Query ms: {t_query:.1f} | RSS MB: {current_rss_mb():.1f}")
    print(f"Files: {stats['files_scanned']} | Chunks: {stats['chunks_indexed']} | Results: {len(results)}")
    db.close()


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python benchmarks/run_bench.py <project_root> [query]")
        raise SystemExit(1)
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "login")
