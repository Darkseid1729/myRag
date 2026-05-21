"""CLI entry-point for MyRAG."""

from __future__ import annotations

import sys
from pathlib import Path

import click
import uvicorn
from rich.console import Console
from rich.table import Table

console = Console()


@click.group()
def main():
    """MyRAG — local code intelligence for Vite + React projects."""


@main.command()
@click.argument("project_root", type=click.Path(exists=True, file_okay=False))
@click.option("--force", is_flag=True, default=False, help="Re-index all files from scratch")
def index(project_root: str, force: bool):
    """Index a Vite+React project for retrieval."""
    from src.config import get_config
    from src.storage.project_registry import ProjectRegistry
    from src.embeddings.onnx_encoder import ONNXEncoder
    from src.indexer.indexing_pipeline import index_project

    console.rule("[bold cyan]MyRAG Indexer")
    console.print(f"Project: [bold]{project_root}[/bold]")

    with console.status("Setting up…"):
        registry = ProjectRegistry()
        encoder = ONNXEncoder()
        db = registry.get_or_create(project_root)

    if force:
        db.execute("DELETE FROM chunks")
        db.execute("DELETE FROM files")
        db.execute("DELETE FROM fts_chunks")
        db.execute("DELETE FROM embeddings")
        db.execute("DELETE FROM graph_edges")
        db.execute("DELETE FROM routes")
        db.execute("DELETE FROM symbols")
        db.execute("DELETE FROM api_calls")
        db.execute("DELETE FROM summaries")
        db.execute("DELETE FROM retrieval_cache")
        db.commit()

    with console.status("Indexing…"):
        stats = index_project(project_root, db, encoder)
        db.close()

    table = Table(title="Indexing Results", show_header=True)
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    for k, v in stats.items():
        table.add_row(k.replace("_", " ").title(), str(v))
    console.print(table)


@main.command()
@click.argument("project_root", type=click.Path(exists=True, file_okay=False))
@click.argument("query")
@click.option("--top-k", default=5, help="Number of results")
def search(project_root: str, query: str, top_k: int):
    """Query an indexed project."""
    from src.storage.project_registry import ProjectRegistry
    from src.embeddings.onnx_encoder import ONNXEncoder
    from src.intent.intent_router import IntentRouter
    from src.retriever.hybrid_retriever import hybrid_search

    registry = ProjectRegistry()
    encoder = ONNXEncoder()
    router_inst = IntentRouter(encoder=encoder)
    db = registry.get_or_create(project_root)

    decision = router_inst.route(query)
    decision.strategy.top_k = top_k

    console.rule(f"[bold cyan]Intent: {decision.intent.value}")
    results = hybrid_search(db, encoder, decision.expanded_query, decision.strategy)
    db.close()

    for i, r in enumerate(results, 1):
        console.print(f"\n[bold green][{i}] {r.file_path}:{r.start_line}[/bold green]  "
                      f"[dim]score={r.final_score:.3f}[/dim]")
        console.print(f"  [bold]{r.chunk_type}[/bold] {r.name or ''}")
        console.print(r.text[:300] + ("…" if len(r.text) > 300 else ""))


@main.command()
@click.argument("project_root", type=click.Path(exists=True, file_okay=False))
@click.argument("query")
@click.option("--top-k", default=5, help="Number of results")
def ask(project_root: str, query: str, top_k: int):
    """Alias for search (kept for roadmap compatibility)."""
    return search(project_root, query, top_k)


@main.command()
@click.argument("project_root", type=click.Path(exists=True, file_okay=False))
@click.argument("query")
@click.option("--top-k", default=5, help="Number of results")
@click.option("--stream", is_flag=True, default=False, help="Stream tokens as they arrive")
def answer(project_root: str, query: str, top_k: int, stream: bool):
    """Retrieve context and ask the configured LLM for an answer."""
    from src.storage.project_registry import ProjectRegistry
    from src.embeddings.onnx_encoder import ONNXEncoder
    from src.intent.intent_router import IntentRouter
    from src.retriever.hybrid_retriever import hybrid_search
    from src.context.builder import build_context
    from src.llm.manager import generate as llm_generate
    from src.config import get_config

    registry = ProjectRegistry()
    encoder = ONNXEncoder()
    router_inst = IntentRouter(encoder=encoder)
    db = registry.get_or_create(project_root)

    decision = router_inst.route(query)
    decision.strategy.top_k = top_k

    results = hybrid_search(db, encoder, decision.expanded_query, decision.strategy)
    prompt = build_context(query, results, max_tokens=get_config()["llm"]["max_context_tokens"])
    db.close()

    if stream:
        for token in llm_generate(prompt, stream=True):
            console.print(token, end="", soft_wrap=True)
        console.print()
        return

    answer_text = llm_generate(prompt, stream=False)
    console.print(answer_text)


@main.command()
@click.option("--host", default="127.0.0.1")
@click.option("--port", default=8000)
@click.option("--reload", is_flag=True, default=False)
def serve(host: str, port: int, reload: bool):
    """Start the MyRAG REST API server."""
    console.rule("[bold cyan]MyRAG Server")
    console.print(f"Listening on [bold]http://{host}:{port}[/bold]")
    console.print(f"Docs available at [bold]http://{host}:{port}/docs[/bold]")
    uvicorn.run("src.api.server:app", host=host, port=port, reload=reload)


@main.command()
@click.argument("project_root", type=click.Path(exists=True, file_okay=False))
def watch(project_root: str):
    """Watch a project and auto-reindex on changes."""
    from src.watcher import watch as watch_project
    watch_project(project_root)


@main.command()
@click.argument("project_root", type=click.Path(exists=True, file_okay=False))
def graph(project_root: str):
    """Show a simple summary of graph edges for a project."""
    from src.storage.project_registry import ProjectRegistry

    registry = ProjectRegistry()
    db = registry.get_or_create(project_root)
    rows = db.fetchall("SELECT edge_type, COUNT(*) as cnt FROM graph_edges GROUP BY edge_type")
    db.close()

    if not rows:
        console.print("[yellow]No graph edges yet. Try indexing first.[/yellow]")
        return

    table = Table(title="Graph Edge Summary")
    table.add_column("Edge Type")
    table.add_column("Count", justify="right")
    for row in rows:
        table.add_row(row["edge_type"], str(row["cnt"]))
    console.print(table)


@main.command(name="list")
def list_projects():
    """List all indexed projects."""
    from src.storage.project_registry import ProjectRegistry
    registry = ProjectRegistry()
    projects = registry.list_projects()
    if not projects:
        console.print("[yellow]No projects indexed yet.[/yellow]")
        return
    table = Table(title="Indexed Projects")
    table.add_column("Project ID")
    table.add_column("DB Path")
    table.add_column("Size")
    table.add_column("Exists")
    for p in projects:
        table.add_row(
            p["project_id"][:12] + "…",
            p["db_path"],
            f"{p['size_bytes'] // 1024} KB",
            "✓" if p["exists"] else "✗",
        )
    console.print(table)


if __name__ == "__main__":
    main()
