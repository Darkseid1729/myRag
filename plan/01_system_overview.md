# 01 — SYSTEM OVERVIEW

## 1.1 What This System Is

A **lightweight, fully offline RAG (Retrieval-Augmented Generation) pipeline** designed specifically for Vite + React codebases. It does NOT attempt to be a general-purpose LLM assistant. Instead, it acts as a **precision code retrieval engine** that:

- Understands the *structure* of a React codebase (components, hooks, routes, state, context)
- Retrieves only the *most relevant* code chunks for a given developer query
- Optionally passes those chunks to a local LLM for final reasoning

The system is designed to answer developer questions like:
- *"Where is authentication handled?"*
- *"Why does Dashboard rerender?"*
- *"Which files affect the /profile route?"*

---

## 1.2 Why This Architecture is Memory Efficient

### The Core Insight: Never Load What You Don't Need

Traditional RAG systems suffer from memory bloat because they:
1. Load all embeddings into RAM (e.g., FAISS index)
2. Keep transformer models loaded continuously
3. Store raw file contents alongside metadata

This system avoids all three by:

| Problem | Our Solution | Memory Saved |
|---------|-------------|-------------|
| Full embedding matrix in RAM | SQLite BLOB + lazy load only queried chunks | ~60% |
| Large transformer (BERT 400MB) | Tiny ONNX (all-MiniLM-L6: 22MB) | ~380MB |
| Full AST in memory | AST parsed on-demand, not stored | ~100% of AST size |
| Full file text in RAM | Only chunk text stored in SQLite | ~70% |

### Memory Architecture Pattern

```
Disk (SQLite DB)          RAM (Working Set)
┌──────────────┐          ┌──────────────────────┐
│ chunks       │ ──────►  │ Active chunks: 5-10  │
│ embeddings   │ (lazy)   │ Embedding cache: LRU │
│ graph edges  │          │ Graph cache: partial │
│ symbols      │          │ Query working memory │
└──────────────┘          └──────────────────────┘
```

All persistent data lives in SQLite. RAM holds only what the current query needs.

---

## 1.3 Retrieval Philosophy

### Three-Signal Fusion

No single signal is sufficient for code search:

| Signal | Good At | Bad At |
|--------|---------|--------|
| **Lexical** (BM25) | Exact names, imports, symbol lookup | Conceptual/intent queries |
| **Semantic** (embeddings) | Conceptual similarity | Exact identifier matching |
| **Graph** (AST/imports) | Structural relationships | Semantic meaning |

The system **fuses all three signals** into a single ranked result list. The weights are dynamically adjusted based on detected query intent.

### Retrieval-First Reasoning

The LLM (if used) is **never** given raw file content. It always receives:
1. Pre-retrieved, ranked code chunks
2. Compact structural summaries
3. Dependency context

This ensures the LLM focuses on *reasoning*, not *searching*.

---

## 1.4 Symbolic + Semantic Understanding

### Symbolic Layer (Tree-sitter + Graph)

The symbolic layer understands the *structure* of code:
- What components exist and what they render
- What hooks are defined and where they're called
- What the import graph looks like
- Which functions call which functions

This is **deterministic** and **accurate** — it doesn't need ML.

### Semantic Layer (ONNX Embeddings)

The semantic layer understands the *meaning* of code:
- "login form component" ≈ `LoginForm.jsx`
- "token validation" ≈ `verifyJWT()` in `auth.js`
- "dark mode preference" ≈ `useTheme` + localStorage logic

This captures **intent** that lexical search misses.

### Fusion

```
Symbol score (S)  ×  0.3
Semantic score (V) ×  0.4    → Weighted Sum → Ranked Chunks
Graph score (G)   ×  0.3
```

Weights shift based on intent: *symbol lookup* boosts S, *architecture* boosts G, *debugging* boosts V.

---

## 1.5 Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Language | Python (backend) + JS (parser) | Tree-sitter JS bindings + ONNX Python mature |
| Storage | SQLite only | Zero-dependency, file-portable, FTS5 built-in |
| Embeddings | `all-MiniLM-L6-v2` via ONNX | 22MB, 384-dim, excellent code understanding |
| Chunking | Function/component level | Natural code units, avoids mid-function splits |
| API | FastAPI REST | Simple, async, easy to extend |
| Indexing | On-demand per project | No background daemon needed |
