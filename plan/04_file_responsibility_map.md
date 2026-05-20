# 04 — FILE RESPONSIBILITY MAP

## Core Source Files

---

### `src/scanner/file_scanner.py`
- **Role**: Entry point of the indexing pipeline. Walks a project directory and discovers all indexable source files.
- **Input**: `project_root: str`, config options (include/exclude patterns)
- **Output**: `List[FileInfo]` — each containing `{path, type, size_bytes, modified_at, content_hash}`
- **Dependencies**: `file_classifier.py`, `hash_utils.py`
- **Memory**: Streams file list, never loads all files at once. Peak RAM: ~1KB per file entry × 50 files = ~50KB.

---

### `src/scanner/file_classifier.py`
- **Role**: Assigns a semantic type to each file based on naming conventions and directory position.
- **Input**: file path + file name
- **Output**: `FileType` enum: `COMPONENT | HOOK | ROUTE | PAGE | UTIL | CONTEXT | CONFIG | STORE`
- **Logic**:
  - `use*.js(x)` → HOOK
  - `*Page.jsx`, `pages/**` → PAGE
  - `*Context.jsx` → CONTEXT
  - `routes/**`, `*Router.jsx` → ROUTE
  - `store/**`, `*.slice.js` → STORE
- **Memory**: Stateless, zero allocation.

---

### `src/scanner/change_detector.py`
- **Role**: Enables incremental re-indexing. Compares current file state (mtime + hash) against stored state in DB.
- **Input**: `List[FileInfo]`, `project_id`
- **Output**: `ChangedFiles` = `{new: [], modified: [], deleted: []}`
- **Dependencies**: `db_manager.py`, `hash_utils.py`
- **Memory**: Holds only current + stored hashes in memory temporarily. ~4KB peak.

---

### `src/parser/tree_sitter_parser.py`
- **Role**: Parses JS/JSX/TSX files using Tree-sitter. Extracts symbol ranges without storing the full AST.
- **Input**: file content as `str`
- **Output**: `ParseResult` — contains node ranges for functions, components, imports, hooks
- **Dependencies**: `tree-sitter` Python package, `node_extractor.py`
- **Memory**: Tree-sitter AST is built in C memory, Python side holds only extracted ranges. Discarded after extraction. Peak: ~500KB per file (immediately freed).
- **Key constraint**: AST object is NEVER persisted. Only extracted metadata is passed forward.

---

### `src/parser/node_extractor.py`
- **Role**: Converts Tree-sitter AST nodes into a structured `NodeList` with type, name, range, and children.
- **Input**: Tree-sitter root node, file content
- **Output**: `List[ExtractedNode]` = `{type, name, start_line, end_line, source_text}`
- **Dependencies**: none (pure Tree-sitter traversal)
- **Memory**: Only stores extracted metadata, not the AST. ~2KB per file.

---

### `src/extractor/component_extractor.py`
- **Role**: Detects React functional components and class components from extracted nodes.
- **Input**: `List[ExtractedNode]`, file content
- **Output**: `List[ComponentMetadata]` = `{name, type, props, returns_jsx, uses_hooks[], renders[]}`
- **Detection rules**:
  - Arrow function assigned to `const` starting with capital letter
  - Function returning JSX (`return <...>`)
  - Class extending `React.Component`
- **Memory**: Small dicts per component. ~500B per component.

---

### `src/extractor/hook_extractor.py`
- **Role**: Detects custom React hooks (functions named `use*`).
- **Input**: `List[ExtractedNode]`
- **Output**: `List[HookMetadata]` = `{name, uses_hooks[], returns, state_vars[]}`
- **Memory**: ~300B per hook.

---

### `src/extractor/state_extractor.py`
- **Role**: Detects all state management patterns in a file.
- **Input**: file content + node list
- **Output**: `List[StateUsage]` = `{var_name, setter, initial_value, state_type}`
- **State types detected**: `useState`, `useReducer`, `Redux`, `Zustand`, `Jotai`, `Recoil`
- **Memory**: ~200B per state variable.

---

### `src/chunker/chunk_models.py`
- **Role**: Defines the `Chunk` dataclass used throughout the system.
- **Schema**:
  ```python
  @dataclass
  class Chunk:
      id: str          # SHA-1 of (file_path + start_line)
      file_path: str
      file_type: FileType
      chunk_type: ChunkType  # COMPONENT | HOOK | FUNCTION | ROUTE | IMPORT_BLOCK | MISC
      name: str        # function/component name
      text: str        # source code of this chunk
      start_line: int
      end_line: int
      symbols: List[str]     # identifiers present in chunk
      imports: List[str]     # external symbols this chunk references
      summary: str           # short description (generated or rule-based)
  ```
- **Memory**: ~1–3KB per chunk depending on text size.

---

### `src/indexer/embedding_indexer.py`
- **Role**: Generates embeddings for each chunk and stores them as quantized BLOBs in SQLite.
- **Input**: `List[Chunk]`
- **Output**: writes to `embeddings` table
- **Process**:
  1. Batch chunks (size=16) for efficiency
  2. Encode via ONNX model (returns float32 384-dim vectors)
  3. Quantize to int8 (384 bytes per embedding vs 1536 bytes)
  4. Store as BLOB with chunk_id FK
- **Dependencies**: `onnx_encoder.py`, `quantizer.py`, `db_manager.py`
- **Memory**: Only one batch (16 chunks) in memory at a time. Peak: ~1MB during encoding.

---

### `src/embeddings/onnx_encoder.py`
- **Role**: Wraps ONNX Runtime session for sentence embedding inference.
- **Input**: `List[str]` (chunk texts)
- **Output**: `np.ndarray` shape `(N, 384)` float32
- **Model**: `all-MiniLM-L6-v2` ONNX (22MB on disk, ~30MB loaded into memory)
- **Optimization**: Model loaded once at startup, shared across all requests via singleton.
- **Memory**: ~30MB for model (shared), ~50KB per batch of 16 chunks.

---

### `src/embeddings/quantizer.py`
- **Role**: Converts float32 embeddings to int8 for 4x memory reduction.
- **Input**: `np.ndarray` float32
- **Output**: `np.ndarray` int8 + scale factor
- **Formula**: `q = round(v / scale)` where `scale = max(abs(v)) / 127`
- **Dequantize**: `v ≈ q × scale`
- **Memory**: Halves embedding storage. 384 bytes vs 1536 bytes per chunk.

---

### `src/graph/graph_builder.py`
- **Role**: Constructs all graph edges from extracted metadata.
- **Edge types produced**:
  - `IMPORTS`: file → imported_file
  - `CALLS`: function → function
  - `USES_HOOK`: component → hook
  - `RENDERS`: component → component
  - `PROVIDES_CONTEXT`: provider → context
  - `CONSUMES_CONTEXT`: component → context
  - `MANAGES_STATE`: component → state_var
- **Output**: `List[GraphEdge]` → written to `graph_edges` table
- **Memory**: Edges are written in streaming fashion. ~100B per edge.

---

### `src/graph/graph_traversal.py`
- **Role**: BFS/DFS algorithms over the SQLite-backed graph.
- **Input**: `start_node_id`, `edge_types[]`, `max_depth`
- **Output**: `List[TraversalResult]` = `{node_id, depth, path, edge_type}`
- **Algorithm**:
  ```
  BFS(start):
      visited = set()
      queue = [(start, 0, [])]
      while queue:
          node, depth, path = queue.pop(0)
          if depth > max_depth: continue
          for neighbor in get_neighbors(node):
              if neighbor not in visited:
                  queue.append((neighbor, depth+1, path+[node]))
  ```
- **Memory**: Only active frontier in RAM. For max_depth=3 and avg 5 neighbors: ~1KB.

---

### `src/retriever/hybrid_retriever.py`
- **Role**: Orchestrates lexical + semantic + graph retrieval and fuses scores.
- **Input**: `query: str`, `intent: Intent`, `project_id: str`, `top_k: int`
- **Output**: `List[RankedChunk]` = `{chunk, lex_score, sem_score, graph_score, final_score}`
- **Dependencies**: `lexical_retriever.py`, `semantic_retriever.py`, `graph_retriever.py`, `reranker.py`
- **Memory**: Holds candidate lists for all three signals simultaneously. ~100KB peak for top-50 candidates.

---

### `src/intent/intent_classifier.py`
- **Role**: Classifies user query into one of 7 intents using rule-based heuristics + optional embedding.
- **Intents**:
  1. `SYMBOL_LOOKUP` — "where is X", "find X", "show me X"
  2. `ARCHITECTURE_UNDERSTANDING` — "how does X work", "explain X"
  3. `MODIFICATION_GUIDANCE` — "where should I add X", "how do I implement X"
  4. `DEBUGGING` — "why does X fail", "what's wrong with X"
  5. `RERENDER_ANALYSIS` — "why does X rerender", "unnecessary renders"
  6. `ROUTE_TRACING` — "which files affect /route", "route flow"
  7. `IMPACT_ANALYSIS` — "what breaks if I change X", "what depends on X"
- **Memory**: Rule-based: zero allocation. Embedding-based: reuses ONNX encoder.

---

### `src/context/evidence_builder.py`
- **Role**: Assembles the final evidence pack from ranked chunks.
- **Input**: `List[RankedChunk]`, `token_budget: int`
- **Output**: `EvidencePack` = `{chunks[], dependency_summary, total_tokens}`
- **Strategy**:
  1. Take top-K chunks
  2. Add direct dependency chunks (1-hop from graph)
  3. Truncate to token budget (default: 2000 tokens)
  4. Generate compact summary for each chunk
- **Memory**: All retrieved text in RAM briefly. Max ~200KB for 2000 tokens.

---

### `src/storage/db_manager.py`
- **Role**: Manages SQLite connection lifecycle, schema migrations, and provides query helpers.
- **Input**: `project_id: str`
- **Output**: Active `sqlite3.Connection` with optimizations applied
- **SQLite optimizations**:
  - `PRAGMA journal_mode=WAL`
  - `PRAGMA cache_size=-4096` (4MB page cache)
  - `PRAGMA synchronous=NORMAL`
  - `PRAGMA temp_store=MEMORY`
- **Connection pooling**: One connection per project, cached per thread.
- **Memory**: SQLite page cache: 4MB (configured, not guaranteed).

---

### `src/llm/base_llm.py`
- **Role**: Abstract base class for all LLM backends.
- **Interface**:
  ```python
  class BaseLLM(ABC):
      def generate(self, prompt: str, stream: bool = False) -> str: ...
      def is_available(self) -> bool: ...
      def get_model_name(self) -> str: ...
  ```
- **Memory**: Depends on backend. Ollama/llama.cpp live in separate process.

---

### `src/api/server.py`
- **Role**: FastAPI application entry point. Configures routes, CORS, lifespan events.
- **Startup**: Loads ONNX model into memory, opens project registry.
- **Shutdown**: Closes DB connections, flushes caches.
- **Memory**: The most significant consumer — holds the ONNX model (~30MB) throughout lifetime.
