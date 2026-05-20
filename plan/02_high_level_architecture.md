# 02 — HIGH LEVEL ARCHITECTURE

## 2.1 Module Breakdown

The system is divided into **10 independent modules**, each with a single responsibility:

```
┌─────────────────────────────────────────────────────────────────┐
│                     RAG CODE INTELLIGENCE SYSTEM                │
│                                                                 │
│  INDEXING PIPELINE (runs once per project)                      │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │  File    │  │   AST    │  │ Metadata │  │ Chunker  │       │
│  │ Scanner  │─►│  Parser  │─►│Extractor │─►│          │       │
│  └──────────┘  └──────────┘  └──────────┘  └────┬─────┘       │
│                                                  │             │
│       ┌──────────────────┬─────────────┬─────────▼──────┐     │
│       │  Lexical Index   │  Embedding  │  Graph Builder │     │
│       │  Builder (FTS5)  │  Generator  │                │     │
│       └──────────────────┴─────────────┴────────────────┘     │
│                          │                                      │
│                    SQLite Database                              │
│                                                                 │
│  RETRIEVAL PIPELINE (runs per query)                            │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │  Intent  │  │ Hybrid   │  │ Context  │  │  LLM     │       │
│  │  Router  │─►│Retriever │─►│ Builder  │─►│  Layer   │       │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘       │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2.2 Module Responsibilities

| Module | Responsibility |
|--------|---------------|
| **File Scanner** | Walk project directory, filter JS/JSX/TS/TSX, detect file type (component/hook/util/route) |
| **AST Parser** | Parse each file with Tree-sitter, extract nodes in one pass, discard AST |
| **Metadata Extractor** | Identify components, hooks, functions, imports, exports, state, context, API calls |
| **Chunker** | Split file into semantic chunks (function/component level), assign IDs |
| **Lexical Index Builder** | Write chunk text + symbols to SQLite FTS5 |
| **Embedding Generator** | Encode each chunk via tiny ONNX model, quantize to int8, store in SQLite BLOB |
| **Graph Builder** | Build import graph + call graph + state graph as edge rows in SQLite |
| **Intent Router** | Classify incoming query into one of 7 intent categories |
| **Hybrid Retriever** | Execute lexical + semantic + graph retrieval, fuse scores |
| **Context Builder** | Assemble compact evidence pack from retrieved chunks |
| **LLM Layer** | (Optional) Forward context + query to local/remote LLM |

---

## 2.3 Indexing Pipeline (Detailed)

```
Project Root
    │
    ▼
[File Scanner]
    │  outputs: list of {path, type, size, modified_at}
    ▼
[AST Parser]  ← Tree-sitter grammar for JS/JSX/TSX
    │  outputs: symbol_list, import_list, export_list, node_ranges
    │  (AST is DISCARDED after this step — not stored)
    ▼
[Metadata Extractor]
    │  outputs: components[], hooks[], functions[], routes[], api_calls[], state_usage[]
    ▼
[Chunker]
    │  outputs: chunks[] = {id, file_path, type, text, start_line, end_line, symbols[]}
    ▼
    ├──► [Lexical Index Builder] → INSERT INTO fts_chunks(chunk_id, text, symbols)
    ├──► [Embedding Generator]  → ONNX encode → int8 quantize → BLOB in embeddings table
    └──► [Graph Builder]        → INSERT INTO graph_edges(from_id, to_id, edge_type)
```

**Key constraint**: AST is never written to disk. Only extracted metadata and chunks are persisted.

---

## 2.4 Retrieval Pipeline (Detailed)

```
User Query: "Where is authentication handled?"
    │
    ▼
[Intent Router]
    │  detected: ARCHITECTURE_UNDERSTANDING
    │  strategy: boost graph_score weight
    ▼
[Hybrid Retriever]
    │
    ├── [Lexical Search]
    │       SELECT chunk_id, rank FROM fts_chunks
    │       WHERE fts_chunks MATCH 'authentication OR auth OR login OR token'
    │       → candidates: [(c_123, 0.9), (c_087, 0.7), ...]
    │
    ├── [Semantic Search]
    │       embed("Where is authentication handled?")
    │       → cosine similarity against embedding BLOBs (lazy loaded)
    │       → candidates: [(c_123, 0.85), (c_201, 0.72), ...]
    │
    └── [Graph Search]
            TRAVERSE graph from "auth"-tagged nodes
            → structurally connected chunks boosted
            → candidates: [(c_123, 1.0), (c_088, 0.6), ...]
    │
    ▼
[Score Fusion]
    score = 0.3 × lex + 0.3 × sem + 0.4 × graph  (architecture intent)
    → top-K chunks selected
    │
    ▼
[Context Builder]
    → fetch chunk texts
    → generate compact summary per chunk
    → assemble evidence pack (max 2000 tokens)
    │
    ▼
[LLM Layer (optional)]
    → prompt = system_context + evidence_pack + user_query
    → send to Ollama / llama.cpp / OpenAI
    │
    ▼
Final Answer
```

---

## 2.5 Reasoning Pipeline

```
Evidence Pack (retrieved chunks + summaries)
    │
    ▼
Prompt Construction:
    ┌─────────────────────────────────────────────┐
    │ SYSTEM: You are a code assistant. Answer    │
    │ based ONLY on the provided code context.   │
    │                                             │
    │ CONTEXT:                                    │
    │ [chunk_summary_1]                           │
    │ [chunk_summary_2]                           │
    │ [dependency_map]                            │
    │                                             │
    │ QUESTION: {user_query}                      │
    └─────────────────────────────────────────────┘
    │
    ▼
LLM Response → Streamed to User
```

If no LLM is configured, the system returns the raw retrieved chunks with their summaries directly.

---

## 2.6 Interaction Flow (API Level)

```
Client (CLI / VSCode Extension / Web UI)
    │
    │  POST /query  { "project_id": "...", "query": "..." }
    ▼
FastAPI Server
    │
    ├── GET /index  { "project_path": "..." }  ← triggers indexing
    ├── GET /status { "project_id": "..." }    ← indexing progress
    ├── POST /query { "project_id", "query" }  ← main retrieval
    └── GET /graph  { "project_id", "node" }   ← graph exploration
```
