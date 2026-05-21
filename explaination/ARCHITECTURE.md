# MyRAG Architecture

## System Philosophy

MyRAG is designed around three constraints that drive every decision:

1. **Memory-first** — Every data structure is evaluated against a 20 MB per-project RAM budget.
2. **Offline-first** — The entire retrieval pipeline runs without network calls. LLM integration is optional and pluggable.
3. **Intent-aware** — The query type determines the retrieval strategy, not a one-size-fits-all approach.

---

## High-Level Module Map

```
┌─────────────────────────────────────────────────────────────┐
│                        src/                                 │
│                                                             │
│  ┌──────────┐    ┌────────────┐    ┌──────────────────┐   │
│  │ scanner  │───▶│  parser    │───▶│    chunker       │   │
│  │ (walk FS)│    │ (tree-sit.)│    │  (overlap split) │   │
│  └──────────┘    └────────────┘    └────────┬─────────┘   │
│                                             │              │
│  ┌──────────┐    ┌────────────┐             ▼              │
│  │extractor │    │   graph    │    ┌──────────────────┐   │
│  │(api calls│───▶│  builder   │    │    indexer       │   │
│  │ regex)   │    │ (edges)    │    │  (orchestrates)  │   │
│  └──────────┘    └─────┬──────┘    └────────┬─────────┘   │
│                        │                    │              │
│                        ▼                    ▼              │
│                  ┌─────────────────────────────────┐      │
│                  │       storage / DBManager        │      │
│                  │   SQLite: FTS5, embeddings,      │      │
│                  │   graph_edges, chunks, symbols   │      │
│                  └──────────────────┬──────────────┘      │
│                                     │                      │
│  ┌──────────┐    ┌────────────┐     │    ┌─────────────┐  │
│  │ intent   │    │ retriever  │◀────┘    │ embeddings  │  │
│  │ router   │───▶│ (hybrid)   │          │ (ONNX+LRU)  │  │
│  └──────────┘    └─────┬──────┘          └─────────────┘  │
│                        │                                   │
│                        ▼                                   │
│                  ┌─────────────────┐                      │
│                  │ context/builder │                       │
│                  └────────┬────────┘                      │
│                           │                               │
│                  ┌────────▼────────┐                      │
│                  │   llm/manager   │                       │
│                  │ ollama|llamacpp  │                       │
│                  │   |openai|none  │                       │
│                  └─────────────────┘                      │
│                                                             │
│  ┌──────────┐    ┌────────────┐    ┌─────────────────┐   │
│  │ api/     │    │  cli.py    │    │    watcher.py   │   │
│  │ server   │    │ (click CLI)│    │ (watchdog FS)   │   │
│  └──────────┘    └────────────┘    └─────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## Data Flow: Indexing

```
FileScanner.scan_project(root)
    │
    │  ScannedFile[]
    ▼
detect_changed_files(scanned, existing_db_hashes)
    │
    │  [only changed ScannedFile]
    ▼
for each changed file:
    │
    ├─ parse_file(abs_path)           → ParsedChunk[]   (tree-sitter or regex)
    │
    ├─ chunk_all(parsed_chunks)       → Chunk[]         (overlap-aware split)
    │
    ├─ for each Chunk:
    │   ├─ _store_chunk(db, chunk, encoder)
    │   │   ├─ INSERT chunks
    │   │   ├─ INSERT fts_chunks (FTS5)
    │   │   ├─ INSERT symbols
    │   │   └─ INSERT embeddings (int8 quantized blob)
    │   └─ _store_api_calls(db, chunk_id, text)
    │       └─ INSERT api_calls
    │
    └─ extract_graph_edges(db, file_id, stored_chunks)
        ├─ IMPORT edges (from_id=file → to_id=imported_file)
        ├─ USES_HOOK edges (chunk → hook chunk)
        ├─ RENDERS edges (component → rendered component)
        ├─ DEFINES_ROUTE edges (app chunk → route component)
        └─ CONSUMES_CONTEXT edges (chunk → context)

db.invalidate_cache()
db.commit()
```

---

## Data Flow: Query

```
User Query String
    │
    ▼
IntentRouter.route(query)
    ├─ Rule-based regex matching → Intent enum
    ├─ Query expansion (auth → authentication, login, JWT, ...)
    └─ RetrievalStrategy (weights, depth, edge filters)
    │
    ▼
hybrid_search(db, encoder, expanded_query, strategy)
    │
    ├─ lexical_search(db, query, top_k=50)
    │   └─ FTS5 MATCH query → BM25 ranked chunks (normalised to [0,1])
    │
    ├─ semantic_search(db, encoder, query, candidate_ids)
    │   ├─ encoder.encode([query]) → float32[384]
    │   ├─ fetch int8 blobs from embeddings table
    │   └─ cosine similarity batch → dict[chunk_id, score ∈ [0,1]]
    │
    └─ graph_search(db, seed_ids, strategy)
        ├─ BFS from top-10 lexical seeds
        ├─ Up to strategy.graph_depth hops
        └─ Exponential decay (0.5^depth) per hop
    │
    ▼
Score Fusion:
    final = w_l * lexical + w_s * semantic + w_g * graph
    │
    ▼ (if use_reranker=true)
CrossEncoder.predict([(query, text) for chunk])
    │
    ▼
Top-K RankedChunk[]
    │
    ▼
build_context(query, chunks, max_tokens=4096)
    │ Token-budgeted evidence pack with code fences
    ▼
llm_generate(prompt)  (optional)
```

---

## Module Responsibilities

### `src/scanner/file_scanner.py`
- Walks the project directory with `os.walk`
- Filters by extension (from config: `.js .jsx .ts .tsx`)
- Excludes configured dirs (`node_modules`, `.git`, `dist`, …)
- Classifies files by path heuristics (HOOK, COMPONENT, PAGE, STORE, ROUTE, UTIL)
- Computes SHA256 content hash for incremental indexing
- Returns `ScannedFile` dataclasses

### `src/parser/tree_sitter_parser.py`
- Uses `tree-sitter-javascript` grammar (covers JS, JSX, TS, TSX)
- Extracts: `function_declaration`, `arrow_function`, `lexical_declaration`, `import_declaration`
- Classifies as COMPONENT (PascalCase + JSX), HOOK (`useXxx`), FUNCTION, IMPORT_BLOCK
- Falls back to regex if tree-sitter unavailable
- Returns `ParsedChunk` dataclasses with line numbers and symbol names

### `src/chunker/chunker.py`
- Converts `ParsedChunk` → one or more `Chunk` objects
- Respects `max_chunk_tokens` and `min_chunk_tokens` from config
- Splits oversized chunks using sliding window with `overlap_tokens` overlap
- Overlap preserves context across split boundaries for embedding quality

### `src/extractor/api_extractor.py`
- Regex-based extraction of `fetch()`, `axios.*()`, `useQuery`, RTK `createApi`
- Extracts HTTP method, endpoint URL, client type, and whether URL is dynamic
- Populates the `api_calls` table (enables endpoint-specific queries)

### `src/graph/graph_builder.py`
- Extracts 5 edge types: IMPORTS, USES_HOOK, RENDERS, DEFINES_ROUTE, CONSUMES_CONTEXT
- Uses `INSERT OR IGNORE` with a UNIQUE index to prevent duplicates
- Weighted edges (IMPORTS=1.0, USES_HOOK=0.9, RENDERS=0.7, …)
- Also extracts route definitions into the `routes` table

### `src/embeddings/onnx_encoder.py`
- Loads `all-MiniLM-L6-v2` ONNX model (~22 MB, auto-downloaded once)
- int8 scalar quantization: `float32[384]` → `bytes[384]` (4× storage reduction)
- Thread-safe LRU cache for dequantized vectors (configurable byte cap)
- `cosine_similarity_batch()` dequantizes on-the-fly using cache

### `src/storage/db_manager.py`
- One SQLite file per indexed project (no shared global DB)
- WAL mode for concurrent reads without blocking writes
- FTS5 virtual table with porter stemmer for BM25 search
- `UNIQUE INDEX` on `graph_edges(from_id, to_id, edge_type)` prevents duplicates
- Explicit FTS5 cleanup (virtual tables don't support FK cascades)

### `src/intent/intent_router.py`
- 7 intent types with regex pattern sets (pre-compiled at module load)
- Embedding-based fallback using exemplar cosine similarity
- Query expansion dictionary (auth → authentication, login, JWT, …)
- Per-intent `RetrievalStrategy` (weights, graph depth, edge type filters)

### `src/retriever/hybrid_retriever.py`
- **Lexical**: FTS5 BM25, normalised to [0,1] via `1/(1+abs(rank))`
- **Semantic**: ONNX cosine on FTS candidates; full scan fallback if FTS returns 0
- **Graph**: BFS with exponential decay and frontier size cap
- **Fusion**: weighted sum with strategy-defined weights
- **Reranker**: optional CrossEncoder (singleton cache, not per-query)

### `src/llm/`
- `manager.py`: routes to configured provider
- `providers.py`: `ollama_generate`, `llamacpp_generate`, `openai_generate`
- All providers support both streaming (`Iterable[str]`) and non-streaming (`str`)

---

## Database Schema (11 tables)

```sql
files            -- one row per source file (hash for incremental indexing)
chunks           -- code chunks with text, line range, type, name
fts_chunks       -- FTS5 virtual table (BM25 over text + symbols + summary)
symbols          -- named symbols extracted from chunks
embeddings       -- int8 quantized embedding blobs
graph_edges      -- directed edges: from_id → to_id, edge_type, weight
routes           -- React Router <Route> definitions
api_calls        -- HTTP endpoint calls extracted from source
retrieval_cache  -- TTL-based query result cache
summaries        -- optional LLM-generated summaries
indexing_metadata -- key-value store for project metadata
```

---

## Plugin System

Plugins receive three lifecycle hooks:

```python
class Plugin(Protocol):
    name: str
    def on_chunk(self, chunk: object) -> None: ...     # called per chunk during indexing
    def on_results(self, query: str, results) -> None: ...  # called after retrieval
    def on_prompt(self, prompt: str) -> str: ...       # can transform the LLM prompt
```

Enable plugins in `config/default.yaml`:
```yaml
plugins:
  enabled:
    - "src.plugins.typescript_plugin"
```

---

## Design Tradeoffs

| Decision | Alternative | Why we chose this |
|----------|------------|-------------------|
| SQLite FTS5 | ElasticSearch | Zero external deps, 20 MB target |
| ONNX encoder | sentence-transformers | CPU-only, 5ms inference |
| int8 quantization | float32 storage | 4× smaller, <1% quality loss |
| One DB per project | Shared global DB | Isolation, easy deletion |
| BFS graph traversal | PageRank | Predictable, bounded memory |
| Rule-based intent | LLM classification | No model needed, deterministic |
| Regex API extraction | AST-based | Fast, no additional parsers |
