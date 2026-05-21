# Setup Guide

## Prerequisites

| Requirement | Minimum | Notes |
|-------------|---------|-------|
| Python | 3.10+ | `python --version` |
| pip | 23+ | `pip --version` |
| RAM | 4 GB | 20 MB used per indexed project |
| Disk | 200 MB | ~22 MB for embedding model |
| OS | Windows / Linux / macOS | All supported |

---

## Step 1: Clone and Enter the Project

```bash
git clone <repo-url> myrag
cd myrag
```

---

## Step 2: Create a Virtual Environment

### Windows (PowerShell)
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

### Linux / macOS
```bash
python3 -m venv .venv
source .venv/bin/activate
```

---

## Step 3: Install Dependencies

```bash
# Core install (development mode)
pip install -e ".[dev]"

# Optional: cross-encoder reranker (requires ~400 MB of model)
pip install -e ".[reranker]"
```

### What gets installed
- `fastapi` + `uvicorn` — REST API server
- `tree-sitter` + `tree-sitter-javascript` — AST parser
- `onnxruntime` + `tokenizers` — embedding inference
- `numpy` — vector math
- `watchdog` — file system watcher
- `pyyaml` + `python-dotenv` — configuration
- `httpx` — LLM provider HTTP client
- `click` + `rich` — CLI + pretty output
- `psutil` — memory monitoring
- `huggingface_hub` — model download

---

## Step 4: Configure Environment

```bash
cp .env.example .env
```

Edit `.env` with your settings:

```env
# Server
APP_HOST=127.0.0.1
APP_PORT=8000

# LLM provider (none | ollama | llamacpp | openai)
LLM_PROVIDER=none

# If using Ollama:
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3

# If using OpenAI:
OPENAI_API_KEY=sk-...

# Memory limits (in KB)
SQLITE_PAGE_CACHE_KB=4096
VECTOR_LRU_CACHE_KB=1024

# Embedding model (downloaded automatically on first run)
EMBEDDING_MODEL=all-MiniLM-L6-v2
MODELS_DIR=./models

# Data directory for SQLite databases
DATA_DIR=./data

# Logging level
LOG_LEVEL=INFO
```

---

## Step 5: Verify Installation

```bash
# Run the test suite (no model download needed)
pytest tests/unit/ -v

# Check CLI works
myrag --help
```

Expected output:
```
Usage: myrag [OPTIONS] COMMAND [ARGS]...

  MyRAG — local code intelligence for Vite + React projects.

Commands:
  answer  Retrieve context and ask the configured LLM for an answer.
  ask     Alias for search (kept for roadmap compatibility).
  graph   Show a simple summary of graph edges for a project.
  index   Index a Vite+React project for retrieval.
  list    List all indexed projects.
  search  Query an indexed project.
  serve   Start the MyRAG REST API server.
  watch   Watch a project and auto-reindex on changes.
```

---

## Step 6: First Index

The embedding model (~22 MB) is downloaded automatically on first use:

```bash
myrag index D:\path\to\your\react-project
```

Expected output:
```
──── MyRAG Indexer ────
Project: D:\path\to\your\react-project
Downloading embedding model (first run)…   ← only on first run
┌───────────────────┬──────────┐
│ Metric            │    Value │
├───────────────────┼──────────┤
│ Files Scanned     │       47 │
│ Files Indexed     │       47 │
│ Chunks Indexed    │      312 │
│ Elapsed Ms        │     4821 │
└───────────────────┴──────────┘
```

---

## Step 7: Search

```bash
# Basic search
myrag search D:\path\to\project "where is useAuth defined?"

# Start the web server
myrag serve

# Open browser
# → http://localhost:8000
```

---

## Ollama Setup (optional)

1. Install Ollama from https://ollama.com
2. Pull a model: `ollama pull llama3`
3. Set in `.env`: `LLM_PROVIDER=ollama`, `OLLAMA_MODEL=llama3`
4. Run: `myrag answer D:\path\to\project "how does authentication work?"`

---

## llama.cpp Setup (optional)

1. Install llama.cpp server: https://github.com/ggerganov/llama.cpp
2. Start it: `./server -m model.gguf -c 4096`
3. Set in `.env`: `LLM_PROVIDER=llamacpp`, `LLAMACPP_BASE_URL=http://localhost:8080`

---

## VSCode Extension Setup

```bash
cd vscode-extension

# Install TypeScript compiler (if not already)
npm install

# Compile
npm run compile
```

1. Open `vscode-extension/` in VSCode
2. Press **F5** to launch a new Extension Development Host window
3. In the new window, open your React project
4. Use **Ctrl+Shift+M** to open the search panel

---

## Troubleshooting

### `No .onnx file found`
The model download failed. Run manually:
```bash
python -c "
from huggingface_hub import snapshot_download
snapshot_download('sentence-transformers/all-MiniLM-L6-v2', local_dir='./models/all-MiniLM-L6-v2')
"
```

### `tree-sitter unavailable`
Install the JS grammar:
```bash
pip install tree-sitter-javascript
```
The system falls back to regex parsing automatically — it still works, just less accurate.

### `FTS5 error` on Windows
SQLite FTS5 is built into Python's `sqlite3` module. If you see FTS5 errors, check:
```python
import sqlite3
conn = sqlite3.connect(':memory:')
conn.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
```
If this fails, your Python was built without FTS5. Install a pre-built Python from python.org.

### Port already in use
```bash
myrag serve --port 8420
```

### High memory usage
Reduce cache sizes in `.env`:
```env
SQLITE_PAGE_CACHE_KB=2048
VECTOR_LRU_CACHE_KB=512
```
