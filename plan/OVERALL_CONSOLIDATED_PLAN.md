# 🧠 CONSOLIDATED OVERALL PROJECT BLUEPRINT: MyRAG
## A Lightweight Local RAG-Based Code Intelligence System for Vite + React Projects

---

> [!NOTE]
> This document serves as the absolute, single consolidated source of truth and architectural blueprint for **MyRAG**, a precision code retrieval and intelligence system. It explains every subsystem, storage design, memory budget, retrieval algorithm, and implementation roadmap in rich detail.

---

## 🗺️ TABLE OF CONTENTS
1. [SYSTEM OBJECTIVES & EXECUTIVE SUMMARY](#1-system-objectives--executive-summary)
2. [HIGH-LEVEL ARCHITECTURE & PIPELINES](#2-high-level-architecture--pipelines)
3. [DATABASE DESIGN & STORAGE SCHEMAS](#3-database-design--storage-schemas)
4. [AST PARSER & SEMANTIC CHUNKING STRATEGY](#4-ast-parser--semantic-chunking-strategy)
5. [LEXICAL & SEMANTIC SEARCH ENGINES](#5-lexical--semantic-search-engines)
6. [GRAPH ENGINE & DEPENDENCY TRACING](#6-graph-engine--dependency-tracing)
7. [INTENT-AWARE ROUTER & STRATEGY SELECTION](#7-intent-aware-router--strategy-selection)
8. [HYBRID RETRIEVAL & SCORE FUSION ENGINE](#8-hybrid-retrieval--score-fusion-engine)
9. [CONTEXT BUILDER & OPTIONAL LLM LAYER](#9-context-builder--optional-llm-layer)
10. [MEMORY OPTIMIZATION & RAM BUDGETING](#10-memory-optimization--ram-budgeting)
11. [QUERY EXECUTION WALKTHROUGHS](#11-query-execution-walkthroughs)
12. [CLI, WATCHDOG & VSCODE EXTENSIBILITY](#12-cli-watchdog--vscode-extensibility)
13. [MVP ROADMAP, RISKS & SUCCESS METRICS](#13-mvp-roadmap-risks--success-metrics)
14. [RECOMMENDED TECH STACK & PRODUCTION CHECKLIST](#14-recommended-tech-stack--production-checklist)

---

## 1. SYSTEM OBJECTIVES & EXECUTIVE SUMMARY

### 1.1 The Mission
Vite + React development moves at high speed, relying heavily on implicit modular structures (hooks, context providers, router configurations, utility modules). Generic AI coding tools often suffer from **context bloat** (trying to read whole files) or **conceptual blindness** (missing functional or structural dependencies).

**MyRAG** is designed to solve this by acting as a **highly precise, resource-conscious, fully local codebase intelligence engine**. It targets small-to-medium codebases (~50 files, up to ~500 chunks) and ensures that developer queries receive high-quality context within a strict **≤20MB RAM budget per indexed project**.

### 1.2 Target Performance Benchmarks
*   **Memory Ceiling:** ≤20MB RAM per project database (excluding shared ONNX encoder).
*   **Indexing Speed:** <10 seconds for a typical 50-file Vite + React project.
*   **Query Latency:** <50ms end-to-end (pure retrieval mode), <1000ms with a local quantized model (Ollama).
*   **Symbol Lookup Accuracy:** >95% exact resolution of components, hooks, and helpers.
*   **Route Flow Tracing:** 100% complete paths from routing components to leaf nodes.

---

## 2. HIGH-LEVEL ARCHITECTURE & PIPELINES

MyRAG divides responsibilities into distinct modules running across three unified pipelines: **Indexing, Retrieval, and Reasoning**.

```
                         ┌──────────────────────────────┐
                         │      User Query Input        │
                         └──────────────┬───────────────┘
                                        │
                                        ▼
                         ┌──────────────────────────────┐
                         │   11. Intent-Aware Router    │
                         └──────────────┬───────────────┘
                                        │ (Intent + Strategy Weights)
                                        ▼
                         ┌──────────────────────────────┐
                         │ 12. Hybrid Retrieval Engine  │
                         │    (Fuses three signals)     │
                         └──────┬───────┬────────┬──────┘
                                │       │        │
         ┌──────────────────────┘       │        └──────────────────────┐
         ▼                              ▼                               ▼
┌──────────────────┐           ┌──────────────────┐           ┌──────────────────┐
│  Lexical Engine  │           │ Semantic Engine  │           │   Graph Engine   │
│  (SQLite FTS5)   │           │ (ONNX int8 BLOB) │           │ (Adjacency Edge) │
└────────┬─────────┘           └────────┬─────────┘           └────────┬─────────┘
         │                              │                              │
         └──────────────────────────────┼──────────────────────────────┘
                                        │
                                        ▼
                         ┌──────────────────────────────┐
                         │  Score Fusion & Deduplication│
                         └──────────────┬───────────────┘
                                        │ (Top-K Chunks)
                                        ▼
                         ┌──────────────────────────────┐
                         │     13. Context Builder      │
                         │  (Assembles Evidence Pack)   │
                         └──────────────┬───────────────┘
                                        │
                                        ▼
                         ┌──────────────────────────────┐
                         │   14. LLM Layer (Optional)   │
                         │ (Ollama/llama.cpp/OpenAI API)│
                         └──────────────────────────────┘
```

### 2.1 The Indexing Pipeline
Executed when a project is registered or when a file modification event triggers a watch update:
1.  **File Scanner:** Recursively walks the workspace, filters non-matching directories (e.g., `node_modules`, `dist`), and tags source files.
2.  **Incremental Change Detector:** Computes a SHA-256 hash of each file's contents, comparing it with the existing DB entry to skip unchanged files.
3.  **AST Parser:** Triggers a fast Tree-sitter pass to find syntax nodes, falling back to `@babel/parser` on failure.
4.  **Metadata Extractor:** Evaluates node shapes to identify components, hooks, route setups, API fetch patterns, and state arrays.
5.  **Chunker:** Segments the file into semantic boundaries (functions, component declarations, import heads) rather than character-count slices.
6.  **Writing & Indexing:** Bulk inserts records into FTS5 virtual tables, writes dependencies into the SQLite graph table, encodes text using a local ONNX MiniLM model, quantizes values to 8-bit integers, and writes them as binary BLOBs.

### 2.2 The Retrieval Pipeline
Executed when the user submits a query to the API or CLI:
1.  **Intent Routing:** The query is routed to check if it asks about symbols, route flows, rerendering logic, or architectural footprints.
2.  **lexical Match (FTS5):** A fast BM25 match searches the index using Porter-stemmed and camelCase-split terms.
3.  **Semantic Match (ONNX Cosine):** Chunks returned from lexical matching are used as a candidate pool. The query is embedded, and cosine similarities are calculated in a single vectorized NumPy step against the candidate BLOBs.
4.  **Graph Expansion (BFS Proximity):** Connected files, hooks, rendering relationships, and routes are traversed outward to calculate a proximity score.
5.  **Weighted Fusion:** Individual normalized scores are fused based on the weights designated by the query's intent type.

### 2.3 The Reasoning Pipeline
Translates retrieval results into a user-facing answer:
1.  **Context Builder:** Evaluates token bounds, truncating lower-scored chunks to summaries while preserving the full text of top-3 results.
2.  **Context Construction:** Creates a clean markdown context separating code blocks, relevance descriptions, and dependency mappings.
3.  **Optional LLM Layer:** If active, streams the formatted prompt to a local model (such as `deepseek-coder:1.3b` inside Ollama) with temperature set to a strict `0.1` to prevent hallucinations.

---

## 3. DATABASE DESIGN & STORAGE SCHEMAS

MyRAG uses a single SQLite file per project, located at `data/projects/<project_id>.db`. 

```
                               SQLite Database File
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                                                                 │
│  ┌──────────────────┐     ┌──────────────────┐     ┌────────────────────────┐   │
│  │      files       │◄────┤      chunks      │◄───►│ fts_chunks (FTS5)      │   │
│  │                  │     │                  │     │                        │   │
│  │ (Hash, Metadata) │     │  (Source, Lines) │     │ (Porter Stemmed Token) │   │
│  └──────────────────┘     └────────┬─────────┘     └────────────────────────┘   │
│                                    │                                            │
│                                    ├──────────────────┐                         │
│                                    ▼                  ▼                         │
│                           ┌──────────────────┐ ┌──────────────┐                 │
│                           │    embeddings    │ │   symbols    │                 │
│                           │                  │ │              │                 │
│                           │ (int8 Vector BLOB)││ (Export tags)│                 │
│                           └──────────────────┘ └──────────────┘                 │
│                                                                                 │
│  ┌──────────────────┐     ┌──────────────────┐     ┌────────────────────────┐   │
│  │   graph_edges    │     │      routes      │     │       api_calls        │   │
│  │                  │     │                  │     │                        │   │
│  │ (Direct / Rev)   │     │  (Paths, Guards) │     │ (Endpoints, Clients)   │   │
│  └──────────────────┘     └──────────────────┘     └────────────────────────┘   │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### 3.1 Migration 001: Core Indexing Tables
```sql
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
PRAGMA cache_size=-4096;   -- Strict 4MB pool limit
PRAGMA temp_store=MEMORY;

CREATE TABLE files (
    id           TEXT PRIMARY KEY,
    path         TEXT NOT NULL UNIQUE,
    file_type    TEXT NOT NULL DEFAULT 'UNKNOWN',
    size_bytes   INTEGER,
    line_count   INTEGER,
    content_hash TEXT NOT NULL,
    indexed_at   INTEGER NOT NULL,
    modified_at  INTEGER NOT NULL
);

CREATE TABLE chunks (
    id          TEXT PRIMARY KEY,
    file_id     TEXT NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    chunk_type  TEXT NOT NULL DEFAULT 'MISC',
    name        TEXT,
    text        TEXT NOT NULL,
    start_line  INTEGER NOT NULL,
    end_line    INTEGER NOT NULL,
    char_count  INTEGER,
    has_state   INTEGER DEFAULT 0,
    has_jsx     INTEGER DEFAULT 0,
    has_api     INTEGER DEFAULT 0,
    has_context INTEGER DEFAULT 0,
    metadata    TEXT, -- Extra JSON payload
    summary     TEXT,
    created_at  INTEGER NOT NULL
);

CREATE VIRTUAL TABLE fts_chunks USING fts5(
    chunk_id UNINDEXED,
    text,
    symbols,
    summary,
    tokenize = "porter unicode61"
);

CREATE TABLE symbols (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    chunk_id            TEXT NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
    name                TEXT NOT NULL,
    symbol_type         TEXT NOT NULL,
    is_exported         INTEGER DEFAULT 0,
    is_default_export   INTEGER DEFAULT 0
);

CREATE TABLE embeddings (
    chunk_id   TEXT PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
    vector     BLOB NOT NULL, -- 384-byte int8 payload
    scale      REAL NOT NULL, -- Scale factor for float32 reconstruction
    model_id   TEXT NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE TABLE graph_edges (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    from_id   TEXT NOT NULL,
    to_id     TEXT NOT NULL,
    edge_type INTEGER NOT NULL, -- Stored as integer for extreme compactness
    weight    REAL DEFAULT 1.0,
    metadata  TEXT
);

CREATE TABLE routes (
    id           TEXT PRIMARY KEY,
    path         TEXT NOT NULL,
    component    TEXT NOT NULL,
    chunk_id     TEXT REFERENCES chunks(id),
    is_protected INTEGER DEFAULT 0,
    parent_route TEXT,
    is_lazy      INTEGER DEFAULT 0,
    metadata     TEXT
);

CREATE TABLE api_calls (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chunk_id    TEXT NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
    method      TEXT,
    endpoint    TEXT,
    client_type TEXT,
    is_dynamic  INTEGER DEFAULT 0
);
```

### 3.2 Indexing Structures
*   **Symbol search index:** `idx_symbols_name` on `symbols(name)` is highly optimized for O(1) matching during exact lookups.
*   **Adjacency graph lookup:** Dual indexes on `graph_edges(from_id, edge_type)` and `graph_edges(to_id, edge_type)` allow rapid bidirectional path traversal.
*   **Covering Chunks Index:** `idx_chunks_cover` contains `(id, name, file_id, chunk_type, start_line, end_line)`. It resolves metadata queries without pulling the raw text column, preserving SQLite pages inside the memory pool.

---

## 4. AST PARSER & SEMANTIC CHUNKING STRATEGY

### 4.1 Hybrid Extraction Architecture
React codebases contain dynamic JS features alongside nested JSX markup. Tree-sitter runs as the default parser due to its efficiency and error recovery. If it encounters highly irregular JSX or TSX declarations, it falls back to a Node-based subprocess executing a Babel AST parser.

```
                           Raw File Content
                                  │
                                  ▼
                      ┌──────────────────────┐
                      │  Tree-sitter Parser  │
                      └──────────┬───────────┘
                                 │
                   ┌─────────────┴─────────────┐
                   │                           │
              Parse Success?               Parse Fail?
                   │                           │
                   ▼                           ▼
         ┌──────────────────┐        ┌──────────────────┐
         │   Extract Nodes  │        │  Babel Fallback  │
         │   & Discard AST  │        │   (Subprocess)   │
         └──────────────────┘        └──────────────────┘
```

The parsing step uses **zero AST retention**. The parser reads the file, extracts token mappings and lines, and immediately deletes the AST representation. This prevents the Python runtime from accumulating C-level AST allocations.

### 4.2 AST Node Rules
*   **Functional Components:** A component is identified if a function name matches PascalCase, and it returns a `jsx_element` or contains an explicit `return` with an expression evaluated as JSX.
*   **Hooks:** Identifies custom hooks starting with `use` followed by an uppercase letter (e.g. `useTheme`). Built-in hooks like `useState` or `useEffect` generate immediate state/hook edge links in the database.
*   **Routes:** Locates `Route` tags (e.g. `<Route path="/login" element={<LoginPage />} />`) to capture route maps.
*   **API footprint:** Scrapes all occurrences of `fetch()`, `axios` references, or react-query instances like `useQuery` or `useMutation`.

### 4.3 Semantic Chunk boundaries
Instead of character-length boundaries that split code mid-statement, MyRAG aligns chunks with AST nodes:

```jsx
// --- CHUNK 1 (IMPORT_BLOCK) ---
import React, { useState } from 'react';
import { useAuth } from '../hooks/useAuth';

// --- CHUNK 2 (COMPONENT: UserProfile) ---
export const UserProfile = ({ userId }) => {
  const { user, logout } = useAuth();
  
  // --- CHUNK 3 (STATE_BLOCK: UserProfile_state) ---
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(user?.name || '');

  return (
    <div className="profile-container">
      {editing ? <input value={name} onChange={e => setName(e.target.value)} /> : <h2>{name}</h2>}
      <button onClick={() => setEditing(!editing)}>Edit</button>
    </div>
  );
};
```

This ensures each chunk acts as a standalone block with its own local symbol bindings and semantic boundaries.

---

## 5. LEXICAL & SEMANTIC SEARCH ENGINES

```
                          Developer Query
                                 │
                                 ▼
                     ┌───────────────────────┐
                     │ 1. Normalization &    │
                     │    camelCase Split    │
                     └───────────┬───────────┘
                                 │
                                 ▼
                     ┌───────────────────────┐
                     │  2. SQLite FTS5 Match │
                     │   (Porter Stemming)   │
                     └───────────┬───────────┘
                                 │ (Top-50 Candidates)
                                 ▼
                     ┌───────────────────────┐
                     │   3. ONNX Embed Query │
                     │  (all-MiniLM-L6 model)│
                     └───────────┬───────────┘
                                 │ (float32 vector)
                                 ▼
                     ┌───────────────────────┐
                     │ 4. Vectorized Cosine  │
                     │  (NumPy dot against   │
                     │   quantized BLOBs)    │
                     └───────────────────────┘
```

### 5.1 FTS5 Lexical Search Strategy
Lexical matching is critical for discovering exact identifier names. A query for `useAuth` must return the `useAuth` declaration instead of a semantically similar hook like `useAuthentication`.

MyRAG uses SQLite FTS5 with **Porter-stemming** and **camelCase token split preprocessing**.

```python
def split_camel_case(text: str) -> str:
    """Converts camelCase/PascalCase to space-separated terms."""
    result = re.sub(r'([a-z])([A-Z])', r'\1 \2', text)
    result = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1 \2', result)
    return result.lower()
```

This transforms `handleUserLogin` into `handle user login` at index time, allowing a search for "login user" to return `handleUserLogin`.

### 5.2 ONNX Embedding Engine
For semantic matching, MyRAG loads `all-MiniLM-L6-v2` inside ONNX Runtime. This tiny model runs directly on the CPU, using ~30MB of RAM.

1.  **Tokenization:** Encodes chunk text up to a strict 256-token limit.
2.  **Mean Pooling:** Averages token vectors while skipping attention mask padding.
3.  **L2 Normalization:** Forces the final 384-dimension vector to unit length.

### 5.3 Scalar Quantization (float32 → int8)
Standard float32 embeddings occupy **1,536 bytes** (384 dimensions × 4 bytes). Storing hundreds of chunks creates significant database overhead. 

MyRAG quantizes vectors to int8, compressing them to **384 bytes** (75% savings).

```python
def quantize_to_int8(vector: np.ndarray) -> Tuple[bytes, float]:
    # Calculate scale factor using max absolute value
    scale = np.max(np.abs(vector)) / 127.0
    if scale == 0:
        return bytes(len(vector)), 1.0
    # Map range to [-127, 127]
    quantized = np.round(vector / scale).astype(np.int8)
    return quantized.tobytes(), scale

def dequantize_from_int8(blob: bytes, scale: float) -> np.ndarray:
    quantized = np.frombuffer(blob, dtype=np.int8).astype(np.float32)
    return quantized * scale
```

### 5.4 Cosine Vectorized Calculation
Cosine calculations skip heavy database queries. The system uses lexical matching to select the top 50 candidates, lazy-loads their 384-byte vector BLOBs, and calculates similarities in a single vectorized step using NumPy.

```python
def batch_cosine_similarity(query_vec: np.ndarray, candidate_blobs: List[Tuple[bytes, float]]) -> np.ndarray:
    matrix = np.zeros((len(candidate_blobs), 384), dtype=np.float32)
    for i, (blob, scale) in enumerate(candidate_blobs):
        matrix[i] = dequantize_from_int8(blob, scale)
    
    # Renormalize rows to handle precision loss from quantization
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    matrix = matrix / np.clip(norms, 1e-9, None)
    
    # Single NumPy dot product
    return matrix @ query_vec
```

---

## 6. GRAPH ENGINE & DEPENDENCY TRACING

MyRAG maps logical connections across the codebase using a lightweight SQLite edge database.

```
                           React Router Path: /dashboard
                                       │
                                       ▼ (DEFINES_ROUTE)
                             ┌───────────────────┐
                             │  Dashboard.jsx    │
                             └─────────┬─────────┘
                                       │
                   ┌───────────────────┴───────────────────┐
                   │ (RENDERS)                             │ (USES_HOOK)
                   ▼                                       ▼
         ┌───────────────────┐                   ┌───────────────────┐
         │   Sidebar.jsx     │                   │    useUserData    │
         └───────────────────┘                   └─────────┬─────────┘
                                                           │
                                                           ▼ (USES_API)
                                                 ┌───────────────────┐
                                                 │   /api/users/me   │
                                                 └───────────────────┘
```

### 6.1 Traversal & BFS Engine
Rather than loading the entire graph into memory, MyRAG runs standard BFS and DFS routines directly against the SQLite database using indexed connection lookups.

```python
def bfs(start_id: str, edge_types: List[int], max_depth: int, db) -> List[TraversalNode]:
    visited = {start_id}
    queue = deque([(start_id, 0, [start_id])])
    results = []
    
    while queue:
        node_id, depth, path = queue.popleft()
        if depth >= max_depth:
            continue
            
        placeholders = ','.join('?' * len(edge_types))
        rows = db.execute(f"""
            SELECT to_id, edge_type FROM graph_edges 
            WHERE from_id=? AND edge_type IN ({placeholders})
        """, [node_id] + edge_types).fetchall()
        
        for to_id, edge_type in rows:
            if to_id not in visited:
                visited.add(to_id)
                new_path = path + [to_id]
                results.append(TraversalNode(to_id, depth + 1, new_path, edge_type))
                queue.append((to_id, depth + 1, new_path))
    return results
```

### 6.2 Impact Analysis (Reverse Tracking)
To answer *"what breaks if I change X?"*, the graph engine runs a reverse traversal. By swapping `from_id` lookups with `to_id` queries, the BFS maps incoming connections:
1.  **Symbols:** Locates direct callers of a targeted function or component.
2.  **Context Consumers:** Follows `CONSUMES_CONTEXT` edges to identify all components wrapped inside a specific Provider.
3.  **Imports:** Traverses files importing the modified module.

---

## 7. INTENT-AWARE ROUTER & STRATEGY SELECTION

Queries like *"where is AuthProvider defined?"* require different scoring parameters than *"why does the dashboard rerender?"*. The first targets direct declarations, while the second relies on hooks and state mappings.

### 7.1 Classifier Heuristics
The Intent Router classifies queries into seven categories using compiled regex patterns.

```python
INTENT_RULES = {
    Intent.SYMBOL_LOOKUP: [
        r"\bwhere is\b", r"\bfind\b.{0,30}\b(function|component|hook|file)\b", r"\blocate\b"
    ],
    Intent.ROUTE_TRACING: [
        r"\broute\b", r"\b\/[a-z\-\/]+\b", r"\bwhich files.{0,20}route\b"
    ],
    Intent.RERENDER_ANALYSIS: [
        r"\brerender\b", r"\bre-render\b", r"\bwhy.{0,20}render\b"
    ]
}
```

If regex rules return a tie or no match, the router falls back to calculating the cosine similarity of the query vector against **pre-defined intent exemplars** (e.g. comparing the query against *"how does authentication flow work"* to detect an architectural intent).

### 7.2 Strategy Matrix
The selected intent determines the weights used during scoring:

| Intent Type | Lexical Weight | Semantic Weight | Graph Weight | BFS Depth | Graph Edge Restrictions |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **SYMBOL_LOOKUP** | 0.70 | 0.20 | 0.10 | 1 | `CALLS`, `USES_HOOK` |
| **ARCHITECTURE** | 0.20 | 0.30 | 0.50 | 3 | All edges allowed |
| **MODIFICATION** | 0.30 | 0.50 | 0.20 | 2 | All edges allowed |
| **DEBUGGING** | 0.40 | 0.40 | 0.20 | 2 | `CALLS`, `MANAGES_STATE` |
| **RERENDER_ANALYSIS** | 0.30 | 0.40 | 0.30 | 2 | `MANAGES_STATE`, `RENDERS` |
| **ROUTE_TRACING** | 0.20 | 0.20 | 0.60 | 4 | `DEFINES_ROUTE`, `IMPORTS` |
| **IMPACT_ANALYSIS** | 0.20 | 0.20 | 0.60 | 3 | All edges (Reverse mode) |

---

## 8. HYBRID RETRIEVAL & SCORE FUSION ENGINE

The Hybrid Retrieval Engine combines FTS5, semantic ONNX, and Graph Proximity signals.

```
                          Lexical Search (FTS5)
                            [Norm BM25 Score] ───► Weight × 0.30 ┐
                                                                 │
                          Semantic Search (ONNX)                 ├─► Weighted Sum Score
                            [Cosine Similarity]  ───► Weight × 0.40 ┤
                                                                 │
                          Graph Engine (BFS)                     │
                            [Proximity Score]    ───► Weight × 0.30 ┘
```

### 8.1 Fusion Scoring Formula
Each signal is normalized to `[0.0, 1.0]` before calculating the final weighted score:

$$\text{Score}(c) = w_{\text{lex}} \cdot S_{\text{lex}}(c) + w_{\text{sem}} \cdot S_{\text{sem}}(c) + w_{\text{graph}} \cdot S_{\text{graph}}(c) + \text{Bonus}_{\text{type}}(c)$$

Where:
*   $S_{\text{lex}}(c)$ is the Porter-stemmed BM25 FTS5 score normalized by dividing by the highest score in the batch.
*   $S_{\text{sem}}(c)$ is the cosine similarity of the query vector against the dequantized int8 vector BLOB.
*   $S_{\text{graph}}(c)$ is the proximity score computed by path distance from seed nodes:
    *   Distance $0$ (Seed itself) = $1.0$
    *   Distance $1$ (Direct neighbor) = $0.7$
    *   Distance $2$ (Transitive connection) = $0.4$
    *   Distance $\ge 3$ = $0.1$
*   $\text{Bonus}_{\text{type}}(c)$ is a context-specific boost (e.g. adding `0.15` to component chunks during a rerender query).

### 8.2 Overlap Deduplication
If multiple returned chunks cover overlapping lines within the same file, the engine merges them to prevent redundancy:

```python
def aggregate_evidence(ranked: List[RankedChunk]) -> List[RankedChunk]:
    seen = {}
    deduplicated = []
    for rc in ranked:
        path = rc.chunk.file_path
        if path not in seen:
            seen[path] = []
        # Check if line range overlaps with an already selected chunk
        overlap = any(max(rc.chunk.start_line, s) <= min(rc.chunk.end_line, e) 
                      for s, e in seen[path])
        if not overlap:
            seen[path].append((rc.chunk.start_line, rc.chunk.end_line))
            deduplicated.append(rc)
    return deduplicated
```

---

## 9. CONTEXT BUILDER & OPTIONAL LLM LAYER

### 9.1 Context Truncation
Retrieved content is formatted to fit within a strict 2000-token limit:
1.  **Top Chunks (Scored 1-3):** Included in full, showing complete code declarations.
2.  **Supporting Chunks (Scored 4-10):** Replaced with pre-computed summaries to save token space.
3.  **Graph Relationships:** Appended as structured relationship summaries.

### 9.2 Summarization Engine
MyRAG uses a three-tier summarization framework:
*   **Tier 1: Rule-Based Summary (Instant).** Deterministically generated from metadata:
    `"React component 'LoginForm' in LoginForm.jsx. Uses hooks: useAuth, useState. Has state."`
*   **Tier 2: Template-Injected Summary (Low Cost).** Concatenates imports, exports, and hook variables:
    `"Function 'fetchUserData' in api.js. Async. References: axios. Parameters: userId."`
*   **Tier 3: Local LLM-Generated Summary (Expensive).** The system can optionally query Ollama to generate a two-sentence summary of the top-ranked code blocks.

### 9.3 Local LLM Prompts
A local quantized LLM is used strictly for reasoning on the structured context, preventing the model from hallucinating code outside the retrieved chunks.

```
You are a precise code intelligence assistant.
Answer the developer's question using ONLY the code context provided.
Do not invent code that is not shown. If unsure, say so.
Be concise. Use code references (file name + line numbers) when possible.

=== CODE CONTEXT ===

[1] COMPONENT: LoginForm (LoginForm.jsx, lines 12-89)
Note: Directly defines the requested component
---
{raw component code}

[2] HOOK: useAuth (useAuth.js, lines 1-65) (Summary Only)
Note: Exposes authentication actions
Summary: Custom hook exposing auth state and actions. Uses axios.
---

=== RELATIONSHIPS ===
'LoginForm' renders 'Button', uses hook 'useAuth'.
'useAuth' consumes context 'AuthContext'.

=== QUESTION ===
Where is authentication handled?

=== ANSWER ===
```

---

## 10. MEMORY OPTIMIZATION & RAM BUDGETING

To meet the strict **≤20MB RAM ceiling per project**, MyRAG applies memory optimizations across all operations.

```
                        Total Project RAM Budget
┌───────────────────────────────────────────────────────────────────────┐
│                                                                       │
│  ┌───────────────────────┐  ┌───────────────────────┐                 │
│  │   SQLite Page Cache   │  │   Embedding Cache     │                 │
│  │                       │  │                       │                 │
│  │  [PRAGMA cache_size]  │  │   [LRU Cache Limit]   │                 │
│  │         4.0MB         │  │         1.0MB         │                 │
│  └───────────────────────┘  └───────────────────────┘                 │
│                                                                       │
│  ┌───────────────────────┐  ┌───────────────────────┐                 │
│  │ Graph Traversal Buff  │  │   Query & FTS Buff    │                 │
│  │                       │  │                       │                 │
│  │  [Frontier ≤50 nodes] │  │ [FTS Candidate Pool]  │                 │
│  │         0.5MB         │  │         1.0MB         │                 │
│  └───────────────────────┘  └───────────────────────┘                 │
│                                                                       │
│  ┌───────────────────────┐  ┌───────────────────────┐                 │
│  │ Python Runtime & OS   │  │   Context Assembly    │                 │
│  │                       │  │                       │                 │
│  │   [Shared Libraries]  │  │  [Token Allocations]  │                 │
│  │         7.0MB         │  │         1.5MB         │                 │
│  └───────────────────────┘  └───────────────────────┘                 │
│                                                                       │
└───────────────────────────────────────────────────────────────────────┘
  (Note: Shared ONNX Embedding model occupies ~30MB as a global instance)
```

### 10.1 Memory Pools
*   **SQLite pool tuning:** Uses `PRAGMA cache_size=-4096` to cap page cache allocations at 4MB.
*   **Lazy BLOB retrieval:** Embedding vectors are loaded only for matching candidates, preventing the system from loading the entire embedding matrix into RAM.
*   **In-Memory Graph Traversal:** Avoids loading the full graph into memory. The BFS frontier holds only active neighbor IDs, keeping traversal memory usage under ~10KB.

### 10.2 Embedding LRU Cache Capping
Decoded float32 vectors are managed inside a dedicated LRU cache to limit memory consumption:

```python
class EmbeddingLRUCache:
    def __init__(self, max_bytes: int = 1_000_000): # 1MB limit (~682 vectors)
        self.cache = OrderedDict()
        self.current_bytes = 0
        self.max_bytes = max_bytes
        self.size_per_vec = 384 * 4 # float32 size

    def put(self, chunk_id: str, vec: np.ndarray):
        while self.current_bytes + self.size_per_vec > self.max_bytes:
            # Evict the oldest entry
            key, _ = self.cache.popitem(last=False)
            self.current_bytes -= self.size_per_vec
        self.cache[chunk_id] = vec
        self.current_bytes += self.size_per_vec
```

---

## 11. QUERY EXECUTION WALKTHROUGHS

### Walkthrough 1: "Where is authentication handled?"
1.  **Intent Classifier:** Rules match "Where is" and the "auth" keyword, routing the query to `ARCHITECTURE_UNDERSTANDING`.
2.  **Query Expansion:** Expands "authentication" with synonyms: `"authentication login token JWT session credentials useAuth AuthContext"`.
3.  **Lexical Match:** FTS5 checks `fts_chunks` for the expanded terms, returning 50 candidate IDs (including `useAuth.js`, `AuthContext.jsx`, and `LoginForm.jsx`).
4.  **Semantic Rescore:** Computes cosine similarity of the query vector against the candidate BLOBs, scoring `useAuth.js` (`0.89`) and `AuthContext.jsx` (`0.87`) at the top.
5.  **Graph BFS Expansion:** Initiates a BFS traversal from `useAuth.js` up to a depth of 3. This discovers `LoginForm.jsx` (direct usage) and `App.jsx` (which defines the parent `AuthProvider` wrapper).
6.  **Weighted Fusion:** Evaluates combined scores ($0.2 \cdot \text{Lex} + 0.3 \cdot \text{Sem} + 0.5 \cdot \text{Graph}$). `AuthContext.jsx` ranks highest ($0.937$) due to strong graph connections.
7.  **Response Assembly:** Returns the context mapping `AuthContext.jsx` and `useAuth.js` alongside structural relationship summaries.

### Walkthrough 2: "Why does the Dashboard rerender?"
1.  **Intent Classifier:** Captures the "rerender" keyword, routing the query to `RERENDER_ANALYSIS`.
2.  **Lexical Match:** Locates the `Dashboard.jsx` component and state hooks.
3.  **Graph BFS Expansion:** Checks `MANAGES_STATE` and `RENDERS` edges starting from the Dashboard node. It maps three `useState` fields inside the Dashboard and identifies the child `DashboardContent` component.
4.  **Semantic Rescore:** Matches code patterns with potential rerender causes (e.g. missing dependency declarations inside `useEffect` blocks).
5.  **Response Assembly:** Identifies that state changes inside the custom `useUserData` hook trigger updates in the parent component, causing all unmemoized children to rerender.

---

## 12. CLI, WATCHDOG & VSCODE EXTENSIBILITY

### 12.1 Incremental File Watching
The `change_detector` and `watchdog` modules enable incremental updates, automatically re-indexing modified files without parsing the entire project.

```python
class IndexChangeWatcher(FileSystemEventHandler):
    def __init__(self, project_id: str, pipeline):
        self.project_id = project_id
        self.pipeline = pipeline
        self.timer = None

    def on_modified(self, event):
        if event.src_path.endswith(('.js', '.jsx', '.ts', '.tsx')):
            # Debounce rapid save events (500ms window)
            if self.timer:
                self.timer.cancel()
            self.timer = Timer(0.5, self.pipeline.reindex_file, args=[event.src_path])
            self.timer.start()
```

### 12.2 VSCode Integration Flow
The REST API allows VSCode extensions to query the index on demand:
1.  **Hover Information:** Hovering over a symbol triggers `GET /deps/<symbol_name>` to display a quick summary card showing the symbol's dependents and dependencies.
2.  **CodeLens Metrics:** Above export statements, the extension queries the graph table to display reference counts inline: `"Used by 12 components"`.
3.  **Interactive webview:** Developers can open a side panel to search the index, explore route flows, or inspect dependency graphs visually.

---

## 13. MVP ROADMAP, RISKS & SUCCESS METRICS

```
                        MVP Phase Timeline
 ═════════════════════════════════════════════════════════════════════
  Phase 1: Core Foundation (W1-2)    ──► Parse + SQLite FTS5 Indexing
  Phase 2: Semantic Layer (W3-4)     ──► ONNX Embeddings + int8 Quantization
  Phase 3: Intelligence Layer (W5-6) ──► Graph Edges + Intent Routing
  Phase 4: Polish & E2E (W7-8)       ──► Ollama E2E + Watchdog + Extension
 ═════════════════════════════════════════════════════════════════════
```

### 13.1 Phase 1: Core Foundation (Weeks 1-2)
*   **Deliverables:** File scanner, Tree-sitter AST parser, metadata extractor, and basic FTS5 BM25 search.
*   **Milestone:** Querying `myrag ask "handleLogin"` returns exact symbol matches in <10ms.

### 13.2 Phase 2: Semantic Layer (Weeks 3-4)
*   **Deliverables:** Local ONNX model loading, float32 → int8 quantization, and hybrid lexical-semantic retrieval.
*   **Milestone:** Resolves conceptual queries (e.g. searching for "dark mode" returns the theme provider).

### 13.3 Phase 3: Intelligence Layer (Weeks 5-6)
*   **Deliverables:** SQLite-backed graph tables, BFS traversal algorithms, and regex intent classification.
*   **Milestone:** Querying `"files affecting /profile"` returns complete route-to-component paths.

### 13.4 Phase 4: Polish & E2E (Weeks 7-8)
*   **Deliverables:** Ollama and OpenAI API connectors, incremental file watching, a minimal Web UI, and a VSCode extension.
*   **Milestone:** File changes trigger debounced background updates, making the updated symbols searchable in <100ms.

---

## 14. RECOMMENDED TECH STACK & PRODUCTION CHECKLIST

### 14.1 Recommended Tech Stack
*   **Runtime:** Python 3.11+ (using `uv` or `poetry` for package management).
*   **Database:** SQLite 3.38+ with FTS5 virtual table support.
*   **Embedding Model:** `all-MiniLM-L6-v2` in ONNX format.
*   **AST Parser:** `tree-sitter` (with JavaScript and TypeScript grammars).
*   **Web Framework:** FastAPI (using `aiosqlite` for async database operations).
*   **File Watching:** `watchdog` for cross-platform file system event handling.

### 14.2 Production Readiness Checklist
- [ ] Verify Tree-sitter parse recovery handles irregular JSX features (HOC declarations, complex render props).
- [ ] Run benchmark validations to confirm memory usage stays below 20MB per database file.
- [ ] Confirm the initial download of the 22MB ONNX model includes integrity checks and error logging.
- [ ] Enable WAL journal mode on all SQLite connections to prevent locking during concurrent reads/writes.
- [ ] Implement path traversal safeguards when resolving file paths to block access outside the workspace.
