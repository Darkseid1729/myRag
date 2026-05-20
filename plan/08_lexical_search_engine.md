# 08 — LEXICAL SEARCH ENGINE

## 8.1 Why Lexical Search is Critical for Codebases

Unlike natural language text, code has unique lexical properties:
- **Exact identifier names matter**: `useAuth` ≠ `useAuthentication` semantically in code
- **Symbol names are meaningful**: `fetchUserData`, `handleSubmit`, `isLoading`
- **Import paths are structural facts**: `from '../hooks/useAuth'`
- **API routes are literal strings**: `/api/users`, `/auth/login`

A developer querying *"where is handleSubmit defined"* should get an exact match on `handleSubmit`, not a fuzzy semantic result.

**Conclusion**: Lexical search MUST be the first retrieval layer. Semantic search complements it.

---

## 8.2 SQLite FTS5 Architecture

SQLite FTS5 provides:
- Built-in BM25 ranking (better than simple TF-IDF)
- Porter stemmer tokenizer
- Unicode support
- Full-text inverted index
- Zero external dependencies

### Columns Indexed

```sql
CREATE VIRTUAL TABLE fts_chunks USING fts5(
    chunk_id UNINDEXED,   -- Not searchable, just stored for lookup
    text,                 -- Full source code of chunk (weighted × 1.0)
    symbols,              -- Space-separated identifier names (weighted × 2.0)
    summary,              -- Auto-generated description (weighted × 1.5)
    tokenize = "porter unicode61"
);
```

**Column Weights** (via `bm25()` function):
```sql
SELECT chunk_id, bm25(fts_chunks, 0, 2.0, 1.5) AS rank
FROM fts_chunks
WHERE fts_chunks MATCH ?
ORDER BY rank;
```

Symbol matches get 2× weight because exact symbol lookup is usually the most precise signal.

---

## 8.3 Token Normalization Pipeline

Before inserting into FTS5, chunk text is normalized:

```
Raw chunk text
    │
    ▼ Camel case splitting
"handleUserLogin" → "handle user login"
"useAuthToken" → "use auth token"

    ▼ Snake case splitting
"get_user_data" → "get user data"

    ▼ Remove punctuation (keep alphanumeric + underscore)

    ▼ Lowercase

    ▼ Porter stemmer (applied by FTS5 automatically)
"authentication" → "authent"
"rendering" → "render"
"components" → "compon"
```

**CamelCase splitting** is critical for code search — it allows `handleLogin` to match a query for `login`.

Implementation:
```python
def split_camel_case(text: str) -> str:
    """Convert camelCase and PascalCase to space-separated tokens"""
    # Insert space before uppercase letters
    result = re.sub(r'([a-z])([A-Z])', r'\1 \2', text)
    result = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1 \2', result)
    return result.lower()

def normalize_for_fts(text: str) -> str:
    text = split_camel_case(text)
    text = text.replace('_', ' ').replace('-', ' ')
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()
```

---

## 8.4 FTS5 Query Construction

### Basic Query
```sql
SELECT chunk_id, bm25(fts_chunks, 0, 2.0, 1.5) AS rank
FROM fts_chunks
WHERE fts_chunks MATCH 'authentication OR auth OR login'
ORDER BY rank
LIMIT 20;
```

### Phrase Query (exact match)
```sql
WHERE fts_chunks MATCH '"handle submit"'
```

### Prefix Query (fuzzy prefix)
```sql
WHERE fts_chunks MATCH 'auth*'
-- Matches: auth, authentication, authorize, authToken
```

### Column-Specific Boost Query
```sql
WHERE fts_chunks MATCH 'symbols:useAuth OR text:useAuth'
```

---

## 8.5 Query Preprocessing for Lexical Search

Before executing FTS5 queries, the user's query is preprocessed:

```python
def build_fts_query(user_query: str) -> str:
    # 1. Extract potential identifiers (camelCase/PascalCase patterns)
    identifiers = re.findall(r'\b[a-zA-Z][a-zA-Z0-9]*\b', user_query)

    # 2. Split camelCase identifiers
    tokens = []
    for ident in identifiers:
        tokens.extend(split_camel_case(ident).split())

    # 3. Add prefix variants for potentially partial names
    prefix_terms = [f"{t}*" for t in tokens if len(t) > 3]

    # 4. Combine with OR
    all_terms = list(set(tokens + prefix_terms))
    return " OR ".join(all_terms)

# Example:
# Input:  "Where is handleUserLogin defined?"
# Output: "handle OR user OR login OR handleuserlogin OR handle* OR user* OR login*"
```

---

## 8.6 Keyword Boosting for Code Concepts

Certain code keywords are boosted to improve precision:

```python
REACT_KEYWORD_BOOST = {
    "useState": 3.0,
    "useEffect": 3.0,
    "useContext": 3.0,
    "useCallback": 2.5,
    "useMemo": 2.5,
    "useRef": 2.5,
    "Provider": 2.0,
    "Router": 2.0,
    "Route": 2.0,
    "reducer": 2.0,
    "dispatch": 2.0,
    "selector": 2.0,
    "middleware": 1.5,
}
```

When these terms appear in the query or in results, their BM25 score is multiplied by the boost factor.

---

## 8.7 Fuzzy Matching

FTS5 supports prefix matching (`term*`) but not true fuzzy matching (edit distance). For fuzzy needs:

**Option 1**: FTS5 prefix matching (cheap)
```sql
WHERE fts_chunks MATCH 'auth*'  -- matches auth, authenticate, authorization
```

**Option 2**: SQLite LIKE for edit distance (moderate cost)
```sql
WHERE symbols LIKE '%auth%'  -- substring match, not indexed
-- Only used as fallback when FTS5 returns 0 results
```

**Option 3**: Pre-compute phonetic tokens (Soundex/Metaphone) at index time
- Only for symbol names
- Stored in a separate `symbol_phonetic` column
- Enables `useTheme` → `usThm` phonetic match

---

## 8.8 Scoring Strategy

Final lexical score is normalized to [0, 1]:

```python
def normalize_bm25_score(raw_scores: List[float]) -> List[float]:
    """SQLite BM25 returns negative values (lower = better). Normalize to [0,1]."""
    if not raw_scores:
        return []
    min_s = min(raw_scores)
    max_s = max(raw_scores)
    if min_s == max_s:
        return [1.0] * len(raw_scores)
    return [(s - min_s) / (max_s - min_s) for s in raw_scores]
```

---

## 8.9 Memory-Efficient Indexing

| Technique | Description | Savings |
|-----------|-------------|---------|
| **FTS5 in-process** | Runs inside SQLite, no separate server | Full external server RAM |
| **Normalized text only** | Don't store raw duplicates in FTS table | ~50% storage |
| **Page cache limit** | `PRAGMA cache_size=-4096` (4MB max) | Controls RAM ceiling |
| **Column weighting at query time** | Not at index time — flexibility at zero cost | 0 extra storage |
| **Batch INSERT** | 50 chunks per transaction | 10× faster indexing |

---

## 8.10 Lexical Search Result Model

```python
@dataclass
class LexicalResult:
    chunk_id: str
    raw_bm25: float        # Raw negative BM25 score from SQLite
    normalized_score: float  # Normalized to [0, 1]
    matched_terms: List[str]  # Which tokens matched
    snippet: str            # Auto-generated snippet showing match context
```

Snippet generation:
```sql
SELECT snippet(fts_chunks, 1, '[', ']', '...', 10) FROM fts_chunks
WHERE fts_chunks MATCH ?
```
