# Indexing Pipeline

## Overview

The indexing pipeline transforms source files into a queryable knowledge base stored in SQLite. It runs on demand (`myrag index`) and incrementally (via the file watcher or the `/index` API endpoint).

---

## Pipeline Stages

```
Stage 1: SCAN
    FileScanner.scan_project(root)
    → ScannedFile[] with path, hash, line_count, file_type

Stage 2: DIFF (incremental)
    detect_changed_files(scanned, db_hashes)
    → Only files whose SHA256 hash has changed

Stage 3: CLEAN
    _delete_old_data(db, file_id)
    → Removes: chunks, fts_chunks, symbols, embeddings, api_calls, graph edges
    → Note: FTS5 rows must be deleted explicitly (no FK cascade on virtual tables)

Stage 4: PARSE
    parse_file(abs_path)
    → ParsedChunk[] from tree-sitter AST (or regex fallback)

Stage 5: CHUNK
    chunk_all(parsed_chunks)
    → Chunk[] with overlap-aware splitting

Stage 6: STORE
    for each Chunk:
        _store_chunk(db, chunk, encoder)  → chunk_id
        _store_api_calls(db, chunk_id, text)

Stage 7: GRAPH (second pass after all files)
    extract_graph_edges(db, file_id, stored_chunks)
    → Inserts IMPORTS, USES_HOOK, RENDERS, DEFINES_ROUTE, CONSUMES_CONTEXT edges

Stage 8: FINALISE
    db.invalidate_cache()  ← wipes stale retrieval cache
    db.set_meta(...)       ← updates indexing stats
    db.commit()
```

---

## File Scanner

**File:** `src/scanner/file_scanner.py`

### File Classification

Files are classified by path and name heuristics:

| Path contains | Classification |
|---------------|---------------|
| `hook` | HOOK |
| `context` | CONTEXT |
| `store` / `reducer` | STORE |
| `route` | ROUTE |
| `page` / `pages` | PAGE |
| `component` | COMPONENT |
| Filename starts with `use` | HOOK |
| Everything else | UTIL |

### Excluded Directories

Configured in `config/default.yaml`:
```yaml
exclude_dirs: ["node_modules", ".git", "dist", "build", ".next", "coverage"]
```

### Supported Extensions

```yaml
file_extensions: [".js", ".jsx", ".ts", ".tsx"]
```

---

## AST Parser

**File:** `src/parser/tree_sitter_parser.py`

### Tree-sitter Path

Uses the `tree-sitter-javascript` grammar, which handles JS, JSX, TS, and TSX.

**Node types extracted:**
- `function_declaration` → FUNCTION or HOOK
- `function_expression` → FUNCTION or HOOK
- `arrow_function` → FUNCTION, HOOK, or COMPONENT
- `lexical_declaration` (const/let) → FUNCTION, HOOK, or COMPONENT
- `import_declaration` → IMPORT_BLOCK

**Classification rules:**
```
name starts with "use"          → HOOK
name is PascalCase + text has < → COMPONENT
everything else                 → FUNCTION
```

### Regex Fallback

If tree-sitter is unavailable, a simpler regex-based parser extracts:
- `function NAME(` patterns
- `const NAME = (` arrow functions
- Contiguous `import` lines grouped as IMPORT_BLOCK

---

## Chunker

**File:** `src/chunker/chunker.py`

### Token Budget

Configuration:
```yaml
indexer:
  max_chunk_tokens: 300      # ~1200 chars
  min_chunk_tokens: 20       # ~80 chars (tiny chunks are dropped)
  overlap_tokens: 30         # ~120 chars kept as overlap between windows
```

### Split Algorithm

```
For a ParsedChunk with N tokens:
  if N <= max_chunk_tokens:
    return [Chunk(entire text)]  ← fast path

  else:
    windows = []
    i = 0
    while i < len(lines):
      window = []
      tokens = 0
      while tokens < max_chunk_tokens:
        window.append(lines[i])
        i++
      windows.append(window)

      # Back up by overlap_tokens lines
      i -= overlap_lines_count

    return [Chunk(w) for w in windows]
```

### Why Overlap?

Without overlap, splitting a 400-token function at token 300 creates two chunks:
- Window 1: tokens 1–300
- Window 2: tokens 301–400

The embedding model sees them as independent. The function name and signature appear only in window 1, so window 2 has no semantic context about what function it belongs to.

With 30-token overlap:
- Window 1: tokens 1–300
- Window 2: tokens 270–400 (includes the last 30 tokens of window 1)

Window 2's embedding now includes context from the overlapping region.

### Shard Metadata

Multi-shard chunks get metadata:
```python
chunk.metadata = {"shard_index": 0, "shard_total": 3}
chunk.name = "BigComponent[1]"  # Second shard
```

---

## Embedding Storage

### Format

Each chunk's text is embedded as a float32 vector of dimension 384 (for `all-MiniLM-L6-v2`), then scalar quantized to int8:

```python
# float32[384] → 384 bytes (int8) + 1 float (scale)
scale = max(abs(vec))
quantized = round(vec / scale * 127).astype(int8)
```

**Storage cost per chunk:**
- float32: 384 × 4 = 1,536 bytes
- int8 quantized: 384 × 1 + 8 = 392 bytes
- Compression ratio: ~3.9×

### Quality Impact

Scalar quantization introduces a worst-case error of `±0.5/127 ≈ 0.4%` per dimension. In practice, cosine similarity retrieval quality degrades by less than 1% compared to float32.

---

## FTS5 Indexing

Each chunk is inserted into the `fts_chunks` virtual table:

```sql
INSERT INTO fts_chunks(chunk_id, text, symbols, summary)
VALUES (?, ?, ?, ?)
```

- **text**: the raw source code
- **symbols**: space-separated symbol names + camelCase-expanded versions
  - e.g., `useAuthContext useauth context` — allows searching by part of the name
- **summary**: rule-based one-liner: `HOOK \`useAuth\` — export const useAuth ...`
- **tokenize**: `porter unicode61` — stemming for better recall

### CamelCase Expansion

`LoginForm` → `login form loginform` is added to the symbols field so that searching for `login` or `form` finds the component without requiring exact case match.

---

## Graph Edge Extraction

**File:** `src/graph/graph_builder.py`

### Edge Types

| Type | Source → Target | Extracted From |
|------|----------------|----------------|
| IMPORTS | file → imported_file | `from './path'` in import blocks |
| USES_HOOK | chunk → hook chunk | `useXxx()` call sites |
| RENDERS | chunk → component | `<ComponentName>` JSX tags |
| DEFINES_ROUTE | chunk → component | `<Route element={<Comp>}` |
| CONSUMES_CONTEXT | chunk → context | `useContext(CtxName)` |
| MANAGES_STATE | chunk → chunk (self) | `useState`/`useReducer` presence |

### Deduplication

The `graph_edges` table has a `UNIQUE INDEX(from_id, to_id, edge_type)`. All edge inserts use `INSERT OR IGNORE` to silently discard duplicates.

### Second-Pass Extraction

Graph edges are extracted in a **second pass** after all chunks for a file are stored. This ensures that `_resolve_symbol(db, "useAuth", "HOOK")` can find the chunk because it was already inserted in the store phase.

---

## Incremental Indexing

### How It Works

1. On each `index_project()` call, all current file hashes are loaded from the DB.
2. The scanner re-hashes all files on disk.
3. Only files where `disk_hash != db_hash` are re-indexed.
4. For unchanged files: zero work done (no parse, no embed, no DB write).

### Cache Invalidation

After any re-indexing run (even if 0 files changed), `db.invalidate_cache()` is called to wipe the retrieval cache. This prevents serving stale results after code changes.

---

## Configuration Reference

```yaml
indexer:
  max_chunk_tokens: 300         # Maximum tokens per chunk before splitting
  min_chunk_tokens: 20          # Minimum tokens; smaller chunks are dropped
  overlap_tokens: 30            # Tokens shared between adjacent windows
  file_extensions: [...]        # Which file types to index
  exclude_dirs: [...]           # Directory names to skip
```

---

## Performance Notes

- **Parsing**: Tree-sitter is ~10× faster than Babel/esprima for large files.
- **Embedding**: `all-MiniLM-L6-v2` runs ~1ms per chunk on CPU (batch mode).
- **FTS5 insertion**: ~0.1ms per chunk (bulk insert with deferred commit).
- **Target throughput**: 50 files, ~300 chunks/file → ~15,000 chunks indexed in <10 seconds.
- **Commit strategy**: A single `db.commit()` at the end of the pipeline (not per-chunk) is ~100× faster than per-chunk commits.
