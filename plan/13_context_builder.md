# 13 — CONTEXT BUILDER

## 13.1 Role of the Context Builder

The Context Builder transforms a ranked list of code chunks into a **compact, LLM-ready evidence pack**. Its goals:
1. Select the most informative chunks within a token budget
2. Generate compact summaries for each chunk
3. Add structural context (dependency relationships)
4. Format everything for maximum LLM reasoning quality

---

## 13.2 Evidence Pack Structure

```python
@dataclass
class EvidencePack:
    query: str
    intent: Intent
    chunks: List[ChunkEvidence]          # Primary retrieved chunks
    dependency_summary: str              # Graph-derived relationship summary
    total_tokens: int
    confidence: float                    # 0–1, how well retrieval matched query

@dataclass
class ChunkEvidence:
    chunk: Chunk
    summary: str                         # Compact 1–3 sentence description
    relevance_score: float
    relationship_to_query: str           # e.g., "defines the requested function"
    dependencies: List[str]              # Names of what this chunk depends on
```

---

## 13.3 Chunk Summarization

Three-tier strategy based on chunk type:

### Tier 1: Rule-Based Summary (Free, Instant)

For most chunks, a readable summary can be generated deterministically:

```python
def rule_based_summary(chunk: Chunk) -> str:
    templates = {
        ChunkType.COMPONENT: (
            f"React component '{chunk.name}' in {basename(chunk.file_path)}. "
            f"Uses hooks: {', '.join(chunk.hooks_used[:3]) or 'none'}. "
            f"{'Has state.' if chunk.has_state else ''}"
            f"{'Makes API calls.' if chunk.has_api_call else ''}"
        ),
        ChunkType.HOOK: (
            f"Custom hook '{chunk.name}' in {basename(chunk.file_path)}. "
            f"Returns: {chunk.return_type or 'inferred'}. "
            f"{'Manages state.' if chunk.has_state else ''}"
        ),
        ChunkType.FUNCTION: (
            f"Function '{chunk.name}' in {basename(chunk.file_path)}. "
            f"{'Async.' if 'async' in chunk.text[:50] else ''}"
            f"{'Makes API calls.' if chunk.has_api_call else ''}"
        ),
        ChunkType.ROUTE_BLOCK: (
            f"Route definition block in {basename(chunk.file_path)}. "
            f"Defines {chunk.text.count('<Route')} route(s)."
        ),
    }
    return templates.get(chunk.chunk_type, f"Code in {basename(chunk.file_path)}, lines {chunk.start_line}–{chunk.end_line}.")
```

### Tier 2: Template-Injected Summary (Low Cost)

For complex chunks (>100 lines), augment with extracted metadata:

```python
def template_summary(chunk: Chunk, metadata: ChunkMetadata) -> str:
    parts = [rule_based_summary(chunk)]

    if metadata.symbols:
        parts.append(f"Defines: {', '.join(metadata.symbols[:5])}.")

    if metadata.imports:
        parts.append(f"References: {', '.join(metadata.imports[:3])}.")

    if metadata.hooks_used:
        parts.append(f"Uses: {', '.join(metadata.hooks_used[:3])}.")

    return " ".join(parts)
```

### Tier 3: LLM-Generated Summary (Optional, Expensive)

Only for chunks central to the query (top-3 ranked):

```python
async def llm_summary(chunk: Chunk, llm: BaseLLM) -> str:
    prompt = (
        f"Summarize this React code in 2 sentences. "
        f"Focus on what it does, not how:\n\n{chunk.text[:1000]}"
    )
    return await llm.generate(prompt, max_tokens=80)
```

---

## 13.4 Dependency Summary Generation

After chunk retrieval, generate a compact graph-derived relationship summary:

```python
def build_dependency_summary(ranked_chunks: List[RankedChunk], db) -> str:
    if not ranked_chunks:
        return ""

    top_chunk = ranked_chunks[0].chunk
    relationships = []

    # Outgoing: what does this depend on?
    deps = get_direct_deps(top_chunk.id, db)
    if deps:
        relationships.append(f"'{top_chunk.name}' imports/uses: {', '.join(deps[:4])}")

    # Incoming: what uses this?
    consumers = get_direct_consumers(top_chunk.id, db)
    if consumers:
        relationships.append(f"'{top_chunk.name}' is used by: {', '.join(consumers[:4])}")

    # Route connection if any
    route = get_connected_route(top_chunk.id, db)
    if route:
        relationships.append(f"Connected to route: {route}")

    return ". ".join(relationships) + "." if relationships else ""
```

---

## 13.5 Token Budget Management

The evidence pack must fit within a configurable token budget (default: 2000 tokens for context + 500 for query/prompt overhead).

```python
class TokenBudget:
    def __init__(self, max_tokens: int = 2000):
        self.remaining = max_tokens

    def estimate_tokens(self, text: str) -> int:
        """Fast estimate: 1 token ≈ 4 characters"""
        return len(text) // 4

    def can_fit(self, text: str) -> bool:
        return self.estimate_tokens(text) <= self.remaining

    def consume(self, text: str):
        self.remaining -= self.estimate_tokens(text)


def build_evidence_pack(
    ranked: List[RankedChunk],
    query: str,
    intent: Intent,
    max_tokens: int = 2000
) -> EvidencePack:
    budget = TokenBudget(max_tokens)
    selected = []

    for rc in ranked:
        # Try summary first (compact)
        summary = rule_based_summary(rc.chunk)
        chunk_text = rc.chunk.text

        # Decide what to include based on budget
        if budget.can_fit(chunk_text):
            selected.append(ChunkEvidence(
                chunk=rc.chunk,
                summary=summary,
                relevance_score=rc.final_score,
                relationship_to_query=infer_relationship(rc.chunk, query, intent),
                dependencies=get_direct_deps(rc.chunk.id, db)
            ))
            budget.consume(chunk_text)
        elif budget.can_fit(summary):
            # No space for full text, just include summary
            rc.chunk.text = summary
            selected.append(ChunkEvidence(chunk=rc.chunk, summary=summary, ...))
            budget.consume(summary)
        else:
            break  # Budget exhausted

    return EvidencePack(
        query=query,
        intent=intent,
        chunks=selected,
        dependency_summary=build_dependency_summary(ranked, db),
        total_tokens=max_tokens - budget.remaining,
        confidence=compute_confidence(ranked)
    )
```

---

## 13.6 Relationship Inference

```python
def infer_relationship(chunk: Chunk, query: str, intent: Intent) -> str:
    """Generate a human-readable description of why this chunk is relevant."""
    query_lower = query.lower()

    if chunk.name and chunk.name.lower() in query_lower:
        return f"Directly defines '{chunk.name}'"

    if intent == Intent.SYMBOL_LOOKUP:
        return f"Contains symbol definition in {basename(chunk.file_path)}"

    if intent == Intent.ARCHITECTURE:
        return f"Part of the architecture: {chunk.chunk_type.value} in {basename(chunk.file_path)}"

    if intent == Intent.RERENDER_ANALYSIS:
        if chunk.has_state:
            return "Contains state that may cause rerenders"
        return "Renders component affected by state changes"

    return f"Relevant code in {basename(chunk.file_path)}"
```

---

## 13.7 Minimizing Token Usage

Techniques to stay within token budget:

| Technique | Token Savings |
|-----------|--------------|
| Rule-based summaries instead of full text | 80–90% |
| Truncate chunk text at 800 chars if budget tight | Variable |
| Remove comments/blank lines from chunk text | 20–30% |
| Include only top-3 chunks in full, rest as summaries | 50–70% |
| Deduplicate repeated imports in context | 5–10% |

---

## 13.8 Improving Reasoning Quality

Beyond token efficiency, structure improves LLM reasoning:

```
Evidence Pack Format (for LLM):

=== RELEVANT CODE (3 chunks found) ===

[1] COMPONENT: LoginForm (src/components/LoginForm.jsx, lines 12-89)
Relevance: Directly defines the requested component
Dependencies: useAuth, useNavigate, FormInput
---
{chunk text or summary}

[2] HOOK: useAuth (src/hooks/useAuth.js, lines 1-65)
Relevance: Hook used by LoginForm for authentication
Dependencies: axios, localStorage
---
{chunk text or summary}

[3] FUNCTION: handleLogin (src/components/LoginForm.jsx, lines 45-67)
Relevance: Event handler that processes login submission
---
{chunk text or summary}

=== DEPENDENCY CONTEXT ===
'LoginForm' uses: useAuth, useNavigate.
'useAuth' is used by: LoginForm, Dashboard, PrivateRoute.
Connected to route: /login

=== QUESTION ===
{user_query}
```

This structured format helps the LLM understand context, relationships, and provenance of each piece.
