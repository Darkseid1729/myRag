# MyRAG — Local Code Intelligence

> **Memory-efficient, fully offline RAG system for Vite + React codebases.**
> Index your project once, query it in milliseconds with lexical, semantic, and graph-aware retrieval.

---

## ✨ What It Does

### Brutally Honest Assessment: What it ACTUALLY Does Right Now
At its core, this project is a **highly advanced, context-aware code search engine (a smart `grep`)**, *not* a standalone AI agent. It does **not** write code, it does not fix bugs, and unless you explicitly plug in an external LLM (like Ollama or OpenAI), it does not generate text answers.

What it *does* do incredibly well is find the exact code chunks you need by combining three things:
1. **Lexical Search (FTS5):** Fast keyword matching.
2. **Semantic Search (ONNX MiniLM):** Finding code by meaning rather than exact words.
3. **Graph Traversal:** Understanding how files connect via imports and React routes.

It parses your code, chunks it smartly, categorizes your query intent, and returns the top 5 most relevant pieces of code. That's it. It is the "Retrieval" (R) in RAG, waiting for you to provide the "Generation" (G).

*Note: Recent updates include a 2.0x lexical boost for exact symbol matches (crushing FTS noise for direct lookups) and a relaxed graph decay multiplier (0.85) for robust React route tracing.*

| Query | What MyRAG does |
|-------|----------------|
| *"Where is `useAuth` defined?"* | Symbol lookup via FTS5 BM25 |
| *"How does authentication work?"* | Semantic search + graph traversal |
| *"What breaks if I change `ThemeContext`?"* | Reverse dependency BFS |
| *"Why does Dashboard re-render?"* | State + hook edge analysis |
| *"Which files affect the `/dashboard` route?"* | Route graph traversal |

---

## 🚀 Quick Start

### 1. Install

```bash
# Clone the repo
git clone <repo-url>
cd myrag

# Create virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux/macOS

# Install dependencies
pip install -e ".[dev]"
```

### 2. Configure (optional)

```bash
cp .env.example .env
# Edit .env — set LLM_PROVIDER if you want LLM answers
```

### 3. Index your project

```bash
myrag index D:\path\to\your\react-project
```

### 4. Search

```bash
# CLI search
myrag search D:\path\to\project "where is useAuth defined?"

# Start web server + open browser
myrag serve
# → http://localhost:8000
```

### 5. (Optional) Get LLM answers

```bash
# With Ollama running locally:
# Set in .env: LLM_PROVIDER=ollama, OLLAMA_MODEL=llama3
myrag answer D:\path\to\project "how does authentication work?"
```

---

## 🏗️ Architecture

```
User Query
    │
    ▼
[Intent Router]
  Rule-based + embedding fallback
  → Detects: lookup / architecture / debug / modify / route / impact
    │
    ▼
[Hybrid Retriever]
  ├── [Lexical Engine]   FTS5 BM25 — fast keyword match
  ├── [Semantic Engine]  ONNX cosine similarity — concept search
  └── [Graph Engine]     BFS over import/hook/render/route edges
    │
    ▼
[Score Fusion]  w_l * lexical + w_s * semantic + w_g * graph
    │
    ▼ (optional)
[Cross-Encoder Reranker]
    │
    ▼
[Context Builder]  token-budgeted evidence pack
    │
    ▼ (optional)
[LLM Layer]  Ollama | llama.cpp | OpenAI
    │
    ▼
Answer
```

---

## 📁 Project Structure

```
myrag/
├── src/
│   ├── api/          FastAPI REST server
│   ├── chunker/      Overlap-aware code chunker
│   ├── context/      Prompt context builder
│   ├── embeddings/   ONNX encoder + LRU cache
│   ├── extractor/    API call extractor
│   ├── graph/        Dependency graph builder
│   ├── indexer/      Main indexing pipeline
│   ├── intent/       Intent router (7 intent types)
│   ├── llm/          LLM provider integrations
│   ├── parser/       Tree-sitter AST parser
│   ├── plugins/      Plugin system
│   ├── retriever/    Hybrid retrieval engine
│   ├── scanner/      File scanner + classifier
│   ├── storage/      SQLite DB manager + registry
│   └── web/          Browser UI (ui.html)
├── config/
│   └── default.yaml  All configuration defaults
├── tests/
│   ├── unit/         Unit tests (fast, no model needed)
│   └── integration/  End-to-end pipeline tests
├── benchmarks/       Performance benchmark runner
├── scripts/          Utility scripts
├── vscode-extension/ VSCode extension
└── plan/             Architecture design docs
```

---

## ⚙️ CLI Reference

| Command | Description |
|---------|-------------|
| `myrag index <path>` | Index a project (incremental by default) |
| `myrag index <path> --force` | Re-index all files from scratch |
| `myrag search <path> "<query>"` | Hybrid search (no LLM) |
| `myrag answer <path> "<query>"` | Search + LLM answer |
| `myrag answer <path> "<query>" --stream` | Streaming LLM answer |
| `myrag serve` | Start REST API server |
| `myrag serve --port 8420` | Custom port |
| `myrag watch <path>` | Auto-reindex on file changes |
| `myrag list` | List all indexed projects |
| `myrag graph <path>` | Show graph edge summary |

---

## 🌐 REST API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Server health check |
| `/stats` | GET | Memory usage + project count |
| `/index` | POST | Index or re-index a project |
| `/query` | POST | Hybrid search (returns chunks + scores) |
| `/ask` | POST | Search + LLM answer |
| `/projects` | GET | List indexed projects |
| `/project` | DELETE | Remove a project from the registry |
| `/project/meta` | GET | Project indexing metadata |
| `/graph` | GET | Graph nodes and edges |
| `/docs` | GET | Auto-generated Swagger UI |

---

## 🔌 LLM Providers

Set `LLM_PROVIDER` in your `.env`:

| Provider | Config |
|----------|--------|
| Ollama | `LLM_PROVIDER=ollama`, `OLLAMA_MODEL=llama3` |
| llama.cpp | `LLM_PROVIDER=llamacpp`, `LLAMACPP_BASE_URL=http://localhost:8080` |
| OpenAI | `LLM_PROVIDER=openai`, `OPENAI_API_KEY=sk-...` |
| None | `LLM_PROVIDER=none` (retrieval only, default) |

---

## 📊 Memory Profile (per project)

### Brutally Honest RAM Assessment
Are you *actually* only using 20 MB of RAM? **No.**
If you open your OS Task Manager while running a query, you will see the Python process consuming roughly **150 MB to 180 MB** of RAM (e.g., a recent benchmark clocked in at 166.1 MB).

Why the discrepancy?
The "20 MB" claim is the **incremental per-project budget allocated by our internal logic**. It assumes the baseline environment is already running. Here is the actual breakdown of your system's memory:
- **Baseline Python Interpreter + OS Overhead:** ~40-50 MB
- **ONNX Model (MiniLM) Loaded in RAM:** ~30-50 MB
- **Loaded Python Libraries (Numpy, FastAPI, etc.):** ~50 MB
- **MyRAG Internal DB & Buffers (The 20 MB part!):** SQLite cache (~4 MB), Graph BFS frontier (~0.5 MB), and LRU Caches (~1 MB).

So, while the architectural optimizations (like int8 quantization and SQLite tuning) prevent the memory from *growing* exponentially when indexing massive projects, the absolute baseline required to boot up Python and the ML model is firmly around 150+ MB.

| Component | Theoretical Budget | Actual OS Reality |
|-----------|--------|--------|
| Shared ONNX Model + Libs | - | ~100+ MB |
| Baseline OS/Python Overhead| - | ~40-50 MB |
| SQLite page cache | ~4 MB | ~4 MB |
| Embedding LRU cache | ~1 MB | ~1 MB |
| Graph BFS frontier | ~0.5 MB | ~0.5 MB |
| Active query buffers | ~1 MB | ~1 MB |
| **Total** | **≤ 20 MB overhead** | **~166 MB Total Process RSS** |

---

## 🧪 Running Tests

```bash
# All tests
pytest tests/ -v

# Unit tests only (fast — no model download)
pytest tests/unit/ -v

# Integration tests
pytest tests/integration/ -v

# With coverage
pytest tests/ --cov=src --cov-report=html
```

---

## 🔌 VSCode Extension

```
vscode-extension/
```

1. Open `vscode-extension/` in VSCode
2. Run `npm install` (for `@types/vscode`)
3. Press **F5** to launch Extension Development Host
4. Commands:
   - `Ctrl+Shift+M` — Open search panel
   - `Ctrl+Shift+Q` — Search selected text
   - **MyRAG: Index Project** — Index current workspace
   - **MyRAG: Open Web UI** — Open browser UI

---

## 📖 Documentation

| File | Description |
|------|-------------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Module design and data flow |
| [SETUP.md](SETUP.md) | Detailed installation guide |
| [INDEXING_PIPELINE.md](INDEXING_PIPELINE.md) | How indexing works |
| [RETRIEVAL_SYSTEM.md](RETRIEVAL_SYSTEM.md) | How retrieval works |
| [MEMORY_OPTIMIZATION.md](MEMORY_OPTIMIZATION.md) | RAM budget and strategies |
| [API_REFERENCE.md](API_REFERENCE.md) | HTTP API reference |
| [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md) | Annotated file tree |
| [CONTRIBUTING.md](CONTRIBUTING.md) | How to contribute |
