# 🧠 MyRAG: Local & Memory-Efficient Code Intelligence

A fully offline, structurally aware Retrieval-Augmented Generation (RAG) system designed to index, trace, and understand **Vite + React codebases** with an ultra-low memory footprint of **under 20 Megabytes of RAM** per project.

---

## 📌 Project Overview

MyRAG bridges the gap between raw semantic search and semantic structural understanding. Instead of treating codebases as collections of flat text files, MyRAG maps the architectural building blocks of modern React web applications—specifically **custom hooks, route nodes, context providers, component trees, state bindings, and API clients**—and fuses them with lexical and semantic indices in a local, serverless SQLite database.

```
                  ┌──────────────────────────────┐
                  │       Developer Query        │
                  └──────────────┬───────────────┘
                                 │
                                 ▼
                  ┌──────────────────────────────┐
                  │        Intent Router         │
                  └──────────────┬───────────────┘
                                 │
         ┌───────────────────────┼───────────────────────┐
         ▼                       ▼                       ▼
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│ Lexical Engine  │     │ Semantic Engine │     │  Graph Engine   │
│   (SQLite FTS5) │     │ (ONNX Embedder) │     │ (BFS Traversal) │
└────────┬────────┘     └────────┬────────┘     └────────┬────────┘
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 ▼
                  ┌──────────────────────────────┐
                  │    Hybrid Rerank & Fusion    │
                  └──────────────┬───────────────┘
                                 │
                                 ▼
                  ┌──────────────────────────────┐
                  │    Context Builder / LLM     │
                  └──────────────────────────────┘
```

---

## 📁 System Blueprint & Documentation Index

The complete design specifications are structured into logical planning modules located inside the [`/plan`](./plan) directory.

### Core Documentation File Map

| Section | Document | Key Technical Coverage |
| :--- | :--- | :--- |
| **01** | [`01_system_overview.md`](./plan/01_system_overview.md) | Architecture philosophy, low-latency requirements, and memory limit strategies. |
| **02** | [`02_high_level_architecture.md`](./plan/02_high_level_architecture.md) | Pipeline specifications: Indexing, Retrieval, and Reasoning pipelines. |
| **03** | [`03_project_structure.md`](./plan/03_project_structure.md) | Directory structure of the repository. |
| **04** | [`04_file_responsibility_map.md`](./plan/04_file_responsibility_map.md) | Precise I/O, dependencies, and responsibilities for every code module. |
| **05** | [`05_database_design.md`](./plan/05_database_design.md) | SQLite relational schema, index configurations, and quantized vector storage. |
| **06** | [`06_parser_design.md`](./plan/06_parser_design.md) | Tree-sitter integration, AST node analysis, and React pattern matchers. |
| **07** | [`07_chunking_strategy.md`](./plan/07_chunking_strategy.md) | Granular code-block partitioning rules and AST scopes. |
| **08** | [`08_lexical_search_engine.md`](./plan/08_lexical_search_engine.md) | SQLite FTS5 configuration, BM25 ranking parameters, and tokenizers. |
| **09** | [`09_semantic_search_engine.md`](./plan/09_semantic_search_engine.md) | Local ONNX embedding models and 8-bit scalar vector quantization. |
| **10** | [`10_graph_engine.md`](./plan/10_graph_engine.md) | AST dependency tracking: imports, component rendering, hook usage, and routes. |
| **11** | [`11_intent_router.md`](./plan/11_intent_router.md) | Rule-based query intent classifier and adaptive scoring routers. |
| **12** | [`12_hybrid_retrieval_engine.md`](./plan/12_hybrid_retrieval_engine.md) | Score normalization and hybrid reranking mechanisms. |
| **13** | [`13_context_builder.md`](./plan/13_context_builder.md) | Token-constrained evidence builder and code context formatting. |
| **14** | [`14_llm_layer.md`](./plan/14_llm_layer.md) | Offline inference gateways (Ollama, llama.cpp, local ONNX runtimes). |
| **15** | [`15_memory_optimization_plan.md`](./plan/15_memory_optimization_plan.md) | RAM allocation budgets, database page caches, and lazy loading strategies. |
| **16** | [`16_query_execution_walkthrough.md`](./plan/16_query_execution_walkthrough.md) | Step-by-step trace of queries through the system subsystems. |
| **17** | [`17_extensibility_plan.md`](./plan/17_extensibility_plan.md) | Extension APIs, IDE integrations, and live file watchers. |
| **18** | [`18_mvp_roadmap.md`](./plan/18_mvp_roadmap.md) | Detailed implementation stages and milestones. |
| **19** | [`19_performance_strategy.md`](./plan/19_performance_strategy.md) | Latency limits, caching, and database read optimizations. |
| **20** | [`20_final_recommendations.md`](./plan/20_final_recommendations.md) | Final architecture decisions, technology stacks, and safety parameters. |

---

## ⚡ Core Technical Principles

1. **Strict 20MB Memory Cap**: The runtime page caches, vector LRUs, and buffers are aggressively constrained to keep memory footprints below 20MB per indexed project.
2. **AST-Driven Chunking**: Uses incremental Tree-sitter parsers to split code modules along functional boundaries (components, hooks, routers) rather than generic character counts.
3. **Offline-First Privacy**: Performs all parsing, embedding, and vector traversals locally. No network connections are used in core indexing or retrieval.
4. **Relational-Semantic Fusion**: Combines fast SQLite FTS5 lexical indexing, compressed vector similarity, and relational BFS graph traversals in a single SQLite database file.
5. **Intent-Aware Routing**: Detects the structural nature of developer queries (e.g., Symbol Lookup, Render Tracing, Impact Analysis) to dynamically weight retrieval systems.

---

## 🛠️ The Selected Technology Stack

| Technology Component | Operational Footprint | Rationale & Tradeoffs |
| :--- | :--- | :--- |
| **Python Runtime** | ~10.0 MB core base | Standard platform for ONNX runtimes, system-level file handles, and parsing operations. |
| **SQLite (FTS5)** | $\le$4.0 MB cache pool | Zero-dependency, serverless database with integrated full-text-search index structures. |
| **Tree-sitter** | Temporary C Heap | Fast, incremental syntax parsing that gracefully handles malformed or draft code. |
| **ONNX Runtime (CPU)**| $\sim$30.0 MB shared globally | In-process, single-library vector embedding calculations using compressed MiniLM structures. |
| **FastAPI** | $\le$2.5 MB active memory | Lightweight async routing gateway for exposing query and workspace endpoints. |
| **Watchdog** | Negligible overhead | Dynamic filesystem event integration with system file-system channels and debouncers. |

---

## ⚖️ The 20MB Working Memory Budget

To guarantee standard execution limits on developer machines, memory allocation is locked using explicit platform configurations:

* **SQLite Page Cache Limit (4.0 MB)**: Bounded dynamically on database connection to prevent automatic caching from expanding based on the size of the database.
* **Vector LRU Pool (1.0 MB)**: Limits dequantized float32 vectors stored in active memory, evicting oldest vectors during search sweeps.
* **Graph Traversal BFS Queues (0.5 MB)**: Implemented through dynamic database self-joins and small frontier-only BFS lists.
* **Active Working Buffers (1.0 MB)**: Allocations reserved for active textual query strings, parsed token maps, and result templates.
* **Shared Runtimes & OS Overhead (13.5 MB)**: Bounded memory pools for underlying Python runtime threads, shared object symbols, and general OS interfaces.

---

## 🔄 Query Processing & Reranking Strategy

MyRAG classifies developer queries into structured categories and dynamically balances the retrieval signals accordingly:

$$\text{Final Score} = w_{\text{lex}} \cdot S_{\text{lex}} + w_{\text{sem}} \cdot S_{\text{sem}} + w_{\text{graph}} \cdot S_{\text{graph}}$$

| Query Intent Category | Lexical Weight ($w_{\text{lex}}$) | Semantic Weight ($w_{\text{sem}}$) | Graph Weight ($w_{\text{graph}}$) | Graph BFS Depth |
| :--- | :---: | :---: | :---: | :---: |
| `SYMBOL_LOOKUP` | 0.70 | 0.20 | 0.10 | 1 |
| `ARCHITECTURE` | 0.20 | 0.30 | 0.50 | 3 |
| `MODIFICATION` | 0.30 | 0.50 | 0.20 | 2 |
| `DEBUGGING` | 0.40 | 0.40 | 0.20 | 2 |
| `RERENDER_ANALYSIS` | 0.30 | 0.40 | 0.30 | 2 |
| `ROUTE_TRACING` | 0.20 | 0.20 | 0.60 | 4 |

---

## 💾 Relational Schema Layout

All structural, semantic, and textual attributes are managed through an optimized SQLite configuration. Full database schemas and individual column types are detailed in [`05_database_design.md`](./plan/05_database_design.md).

* **`files`**: Maps path strings, timestamps, and hashes.
* **`chunks`**: Text blocks, functional bounds, and component parameters.
* **`symbols`**: Declared custom hooks, exported helpers, and React components.
* **`embeddings`**: High-performance quantized 8-bit embedding vectors alongside scale parameters.
* **`graph_edges`**: Tracks structural connections between components, child imports, rendering chains, hook triggers, and route paths.
* **`routes`**: React Router endpoints, matching files, and lazy loading configurations.
* **`api_calls`**: HTTP endpoints, dynamic client calls, and request schemas.

---

## 🚀 Key Visualizations

Visual representations of the system pipelines, logical graph structures, and scalar quantization processes are available in:
* **LaTeX High-Fidelity PDF Source**: [`plan/OVERALL_PLAN.tex`](./plan/OVERALL_PLAN.tex)
* **Consolidated Markdown Version**: [`plan/OVERALL_CONSOLIDATED_PLAN.md`](./plan/OVERALL_CONSOLIDATED_PLAN.md)
