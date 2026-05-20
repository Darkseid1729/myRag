# 07 — CHUNKING STRATEGY

## 7.1 Why Chunking Strategy Matters

The choice of what constitutes a "chunk" is the single most important architectural decision in the system. Poor chunking causes:

- **Too large**: Chunks contain multiple concepts → retrieval is imprecise, context is noisy
- **Too small**: Chunks lose surrounding context → retrievals are incomplete
- **Wrong boundaries**: Chunks split in the middle of functions → meaningless fragments

Our strategy: **semantic chunking at the natural code boundary level**.

> The natural unit of a React codebase is the **function/component/hook**.
> Every chunk should map to exactly ONE logical code unit.

---

## 7.2 Chunk Types

| Chunk Type | Description | Typical Size |
|------------|-------------|-------------|
| `COMPONENT` | Full React component (props to return) | 20–150 lines |
| `HOOK` | Full custom hook definition | 10–80 lines |
| `FUNCTION` | Utility/helper function | 5–50 lines |
| `ROUTE_BLOCK` | Route definition block | 5–30 lines |
| `IMPORT_BLOCK` | All imports at top of file | 5–20 lines |
| `CONTEXT_DEF` | Context + Provider definition | 10–60 lines |
| `STATE_BLOCK` | State initialization block | 3–15 lines |
| `MISC` | Everything else (fallback) | ≤60 lines |

---

## 7.3 Component-Level Chunking

```
Input file: UserProfile.jsx (200 lines)

Component detected: UserProfile (lines 1–200)
    │
    ├── IMPORT_BLOCK: lines 1–8
    │       → Chunk: {id: "...", type: IMPORT_BLOCK, text: "import React..."}
    │
    ├── FUNCTION: fetchUserData (lines 10–25)
    │       → Chunk: {id: "...", type: FUNCTION, name: "fetchUserData"}
    │
    ├── HOOK usage: useState, useEffect, useAuth (lines 28–45)
    │       → Chunk: {id: "...", type: STATE_BLOCK, name: "UserProfile_state"}
    │
    └── COMPONENT: UserProfile (lines 28–200)
            → Chunk: {id: "...", type: COMPONENT, name: "UserProfile"}
```

**Note**: The component chunk includes everything between `const UserProfile = () => {` and the closing `}`. State blocks are ALSO separately chunked for fine-grained retrieval.

---

## 7.4 Hook-Level Chunking

Custom hooks are always their own chunk, even if they appear inside a larger file:

```
Input: hooks/useAuth.js

Chunks produced:
    1. IMPORT_BLOCK: lines 1-4
    2. HOOK: useAuth (lines 6-89) — the entire hook body
    3. FUNCTION: tokenValidator (lines 91-110) — internal helper
```

---

## 7.5 Route-Level Chunking

React Router route definitions are detected and chunked separately:

```jsx
// Detected as ROUTE_BLOCK chunk:
<Route path="/dashboard" element={<Dashboard />} />
<Route path="/profile/:id" element={<UserProfile />} />
<Route path="/login" element={<LoginPage />} />
```

Each individual `<Route>` also gets a record in the `routes` table.

---

## 7.6 Utility Chunking

For utility files (`utils.js`, `helpers.ts`), each exported function is its own chunk:

```
utils/formatters.js → 5 functions
    → 5 FUNCTION chunks
    → 1 IMPORT_BLOCK chunk
    Total: 6 chunks
```

---

## 7.7 Fallback: Sliding Window

For files that cannot be semantically parsed (e.g., minified, or parse errors), use a sliding window with overlap:

```
window_size = 40 lines
overlap = 10 lines
stride = 30 lines

File: 120 lines
    → Chunk 1: lines 1-40
    → Chunk 2: lines 31-70
    → Chunk 3: lines 61-100
    → Chunk 4: lines 91-120
```

Sliding window chunks are tagged `MISC` and have lower retrieval priority.

---

## 7.8 Chunk Size Constraints

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Min chunk size | 3 lines | Avoid trivial fragments |
| Max chunk size | 150 lines | Embedding quality degrades |
| Target chunk size | 30–80 lines | Optimal for embedding + retrieval |
| Max chunks per file | 30 | Prevents explosion for large files |

If a component exceeds 150 lines, it is split at method/sub-function boundaries within the component.

---

## 7.9 Chunk Text Preprocessing

Before embedding and indexing, chunk text is preprocessed:

```python
def preprocess_chunk(text: str) -> str:
    # 1. Remove excessive blank lines (>2 consecutive)
    text = re.sub(r'\n{3,}', '\n\n', text)

    # 2. Normalize indentation (replace tabs with 2 spaces)
    text = text.replace('\t', '  ')

    # 3. Remove auto-generated comments (e.g., ESLint disable)
    text = re.sub(r'//\s*eslint-disable.*\n', '', text)

    # 4. Truncate to max 4096 characters for embedding
    if len(text) > 4096:
        text = text[:4096]

    return text.strip()
```

---

## 7.10 Chunk Metadata Enrichment

Every chunk is enriched with extracted metadata BEFORE storage:

```python
@dataclass
class ChunkMetadata:
    symbols: List[str]        # All identifiers defined in chunk
    imports: List[str]        # External identifiers referenced
    hooks_used: List[str]     # React hooks called (useState, useEffect, ...)
    has_jsx: bool
    has_state: bool
    has_api_call: bool
    has_context: bool
    complexity_score: int     # Simple metric: nested depth × function count
```

These flags are stored as a compact JSON metadata field in the `chunks` table and used for filtering during retrieval.

---

## 7.11 Chunk ID Generation

```python
def generate_chunk_id(file_path: str, start_line: int, name: str) -> str:
    raw = f"{file_path}:{start_line}:{name}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]  # 16-char hex
```

IDs are deterministic — re-indexing the same file produces the same chunk IDs, enabling incremental updates.

---

## 7.12 Retrieval Optimization via Chunking

The chunk granularity directly affects retrieval quality:

| Query Type | Optimal Chunk Type |
|------------|------------------|
| "Where is X defined?" | FUNCTION or COMPONENT |
| "How does auth work?" | HOOK + multiple FUNCTION |
| "Show me all routes" | ROUTE_BLOCK |
| "Why does X rerender?" | COMPONENT + STATE_BLOCK |
| "What API calls does Y make?" | FUNCTION with has_api_call=True |
| "Where is context used?" | CONTEXT_DEF + COMPONENT |
