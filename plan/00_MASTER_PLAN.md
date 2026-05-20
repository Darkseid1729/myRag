# 🧠 LOCAL RAG CODE INTELLIGENCE SYSTEM — MASTER PLAN
## Lightweight AI Codebase Assistant for Vite + React Projects

---

## 📌 Project Goal

Build a **fully offline, memory-efficient** RAG-based code intelligence system that understands, indexes, and searches through Vite + React codebases (~50 files, ≤20MB RAM per project).

---

## 📁 Plan File Index

| # | File | Description |
|---|------|-------------|
| 01 | `01_system_overview.md` | Architecture philosophy, memory efficiency rationale |
| 02 | `02_high_level_architecture.md` | Module breakdown, pipelines, interaction flow |
| 03 | `03_project_structure.md` | Complete folder/file tree |
| 04 | `04_file_responsibility_map.md` | Every file's role, I/O, dependencies |
| 05 | `05_database_design.md` | SQLite schemas, indexing, compression |
| 06 | `06_parser_design.md` | AST parsing, chunking, metadata extraction |
| 07 | `07_chunking_strategy.md` | Semantic chunking rules and tradeoffs |
| 08 | `08_lexical_search_engine.md` | FTS5 design, BM25, fuzzy matching |
| 09 | `09_semantic_search_engine.md` | Embeddings, compression, similarity search |
| 10 | `10_graph_engine.md` | Import/call/state/route/context graphs |
| 11 | `11_intent_router.md` | Intent detection, rule-based + embedding routing |
| 12 | `12_hybrid_retrieval_engine.md` | Scoring formulas, ranking, reranking |
| 13 | `13_context_builder.md` | Evidence pack, summarization, token efficiency |
| 14 | `14_llm_layer.md` | Ollama, llama.cpp, OpenAI integration |
| 15 | `15_memory_optimization_plan.md` | RAM budgeting, lazy loading, compression |
| 16 | `16_query_execution_walkthrough.md` | Step-by-step query traces |
| 17 | `17_extensibility_plan.md` | Plugins, TypeScript, VSCode, live watch |
| 18 | `18_mvp_roadmap.md` | Phases 1–4, priorities, risks |
| 19 | `19_performance_strategy.md` | Speed, latency, caching, concurrency |
| 20 | `20_final_recommendations.md` | Best tech stack, safest choices |
| — | `schemas/` | Individual SQLite schema files |
| — | `pseudocode/` | Algorithm pseudocode files |
| — | `interfaces/` | TypeScript-style interface definitions |
| — | `workflows/` | Data flow diagrams (text-based) |

---

## ⚡ Core Design Principles

1. **Memory-first**: Every decision evaluated against ≤20MB RAM budget
2. **Symbolic + Semantic**: Tree-sitter AST + ONNX embeddings combined
3. **Offline-first**: Zero network calls required for core functionality
4. **Chunk-level granularity**: Never store full files, only meaningful code units
5. **Intent-aware**: Query type determines retrieval strategy
6. **Modular**: Each subsystem independently testable and replaceable

---

## 🗺️ High-Level Data Flow

```
User Query
    │
    ▼
[Intent Router] ──── detects: lookup / architecture / debug / modify
    │
    ▼
[Hybrid Retriever]
    ├── [Lexical Engine]   → FTS5 BM25 score
    ├── [Semantic Engine]  → ONNX cosine similarity
    └── [Graph Engine]     → structural relevance score
    │
    ▼
[Reranker] ── weighted fusion of all scores
    │
    ▼
[Context Builder] ── evidence pack + compact summaries
    │
    ▼
[Optional LLM] ── Ollama / llama.cpp / OpenAI
    │
    ▼
Final Answer
```

---

## 🧰 Technology Decisions Summary

| Need | Choice | Reason |
|------|--------|--------|
| AST Parsing | Tree-sitter (JS/TSX) | Fast, incremental, low memory |
| Lexical Index | SQLite FTS5 | Built-in, zero deps, BM25 |
| Semantic Index | ONNX tiny model | <50MB model, ~5ms inference |
| Graph Storage | SQLite adjacency | No external graph DB needed |
| Embeddings | int8 quantized | 4x smaller than float32 |
| Optional LLM | Ollama / llama.cpp | Fully local reasoning |
| Query API | FastAPI (Python) or Express (Node) | Lightweight HTTP interface |

---

## 📊 RAM Budget Summary (Per Project)

| Subsystem | Budget |
|-----------|--------|
| SQLite page cache | ~4MB |
| Embedding index (in-memory) | ~6MB |
| Graph (adjacency lists) | ~2MB |
| Intent router model | ~2MB |
| Active chunk buffers | ~3MB |
| OS + runtime overhead | ~3MB |
| **Total** | **~20MB** |
