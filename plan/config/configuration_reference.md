# Configuration Files Reference

## default.yaml

```yaml
# ============================================================
# MyRAG — Default System Configuration
# ============================================================

server:
  host: "127.0.0.1"
  port: 8420
  reload: false
  workers: 1  # Single worker for SQLite (WAL handles concurrency)

storage:
  data_dir: "data/projects"    # Where project .db files are stored
  model_dir: "models"          # Where ONNX models are stored
  max_db_size_mb: 500          # Warn if project DB exceeds this

indexing:
  max_file_size_kb: 512        # Skip files larger than this
  max_chunks_per_file: 30      # Hard cap on chunks per file
  max_chunk_size_chars: 4096   # Truncate chunk text at this length
  min_chunk_lines: 3           # Minimum lines to form a chunk
  max_chunk_lines: 150         # Split chunks larger than this
  batch_size_embeddings: 16    # Chunks per ONNX batch
  parallel_parsers: 4          # Parallel Tree-sitter processes

  include_patterns:
    - "**/*.js"
    - "**/*.jsx"
    - "**/*.ts"
    - "**/*.tsx"

  exclude_patterns:
    - "**/node_modules/**"
    - "**/dist/**"
    - "**/.next/**"
    - "**/build/**"
    - "**/coverage/**"
    - "**/*.test.*"
    - "**/*.spec.*"
    - "**/*.d.ts"
    - "**/vite.config.*"
    - "**/jest.config.*"

retrieval:
  default_top_k: 10
  max_top_k: 50
  max_context_tokens: 2000
  enable_reranker: false       # Disabled by default (+100ms)
  cache_ttl_seconds: 3600
  graph_max_depth: 3

memory:
  sqlite_page_cache_kb: 4096   # 4MB SQLite page cache
  embedding_lru_cache_kb: 1024 # 1MB LRU cache for decoded embeddings
  graph_cache_kb: 512

llm:
  default_backend: "none"      # none | ollama | llamacpp | openai
  max_tokens: 500
  temperature: 0.1
  stream: true

  ollama:
    base_url: "http://localhost:11434"
    model: "deepseek-coder:1.3b"
    timeout_seconds: 60

  llamacpp:
    executable: "llama-cli"    # Or full path
    model_path: null           # Required if using llamacpp
    n_ctx: 2048
    n_threads: 4

  openai:
    model: "gpt-4o-mini"
    api_key: null              # Or set OPENAI_API_KEY env var

plugins:
  enabled: []                  # List of plugin names to enable
  # - "typescript"
  # - "test_coverage"

logging:
  level: "INFO"                # DEBUG | INFO | WARNING | ERROR
  format: "%(asctime)s %(levelname)s %(name)s: %(message)s"
  file: null                   # null = stdout only
```

---

## memory_profiles.yaml

```yaml
# ============================================================
# Memory Profiles — Trade off RAM for speed or vice versa
# ============================================================

profiles:
  minimal:
    description: "Minimum RAM usage. Best for <4GB RAM systems."
    sqlite_page_cache_kb: 2048       # 2MB
    embedding_lru_cache_kb: 256      # 256KB
    graph_cache_kb: 128
    batch_size_embeddings: 8         # Smaller batches
    max_chunks_per_file: 20          # Fewer chunks
    max_context_tokens: 1000         # Shorter context

  default:
    description: "Balanced. Recommended for most users."
    sqlite_page_cache_kb: 4096       # 4MB
    embedding_lru_cache_kb: 1024     # 1MB
    graph_cache_kb: 512
    batch_size_embeddings: 16
    max_chunks_per_file: 30
    max_context_tokens: 2000

  performance:
    description: "Maximum speed. Requires 32GB+ RAM."
    sqlite_page_cache_kb: 16384      # 16MB
    embedding_lru_cache_kb: 8192     # 8MB (caches entire project)
    graph_cache_kb: 4096             # 4MB
    batch_size_embeddings: 32
    max_chunks_per_file: 50
    max_context_tokens: 4000
    enable_reranker: true
```

---

## llm_providers.yaml

```yaml
# ============================================================
# LLM Provider Configurations
# ============================================================

providers:
  ollama_deepseek_small:
    backend: ollama
    model: "deepseek-coder:1.3b"
    description: "Fast, ~1GB RAM, good for simple lookups"
    temperature: 0.1
    max_tokens: 400

  ollama_deepseek_large:
    backend: ollama
    model: "deepseek-coder:6.7b-q4_K_M"
    description: "Higher quality, ~4GB RAM"
    temperature: 0.1
    max_tokens: 600

  ollama_mistral:
    backend: ollama
    model: "mistral:7b-q4_K_M"
    description: "General purpose, good for explanations"
    temperature: 0.2
    max_tokens: 600

  llamacpp_codellama:
    backend: llamacpp
    model_path: "models/codellama-7b.Q4_K_M.gguf"
    n_ctx: 4096
    n_threads: 6
    description: "Fully local, no Ollama required"

  openai_mini:
    backend: openai
    model: "gpt-4o-mini"
    description: "Best quality, requires internet + API key"
    temperature: 0.1
    max_tokens: 800

  retrieval_only:
    backend: none
    description: "No LLM. Returns raw retrieved chunks only."
```

---

## .env.example

```bash
# ============================================================
# MyRAG Environment Variables
# ============================================================

# Server
MYRAG_HOST=127.0.0.1
MYRAG_PORT=8420
MYRAG_ENV=development  # development | production

# Storage
MYRAG_DATA_DIR=data/projects
MYRAG_MODEL_DIR=models

# LLM (optional)
OPENAI_API_KEY=sk-...
MYRAG_LLM_BACKEND=none  # none | ollama | llamacpp | openai
MYRAG_OLLAMA_URL=http://localhost:11434
MYRAG_OLLAMA_MODEL=deepseek-coder:1.3b

# Memory profile
MYRAG_MEMORY_PROFILE=default  # minimal | default | performance

# Debug
MYRAG_LOG_LEVEL=INFO
MYRAG_ENABLE_QUERY_LOG=false  # Set true to log all queries
```
