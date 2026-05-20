# 11 — INTENT ROUTER

## 11.1 Why Intent Routing Matters

The same retrieval system produces very different quality results depending on query type:

| Query | Best Strategy |
|-------|--------------|
| "Where is handleLogin defined?" | Pure lexical symbol lookup |
| "How does authentication work?" | Semantic + graph architecture traversal |
| "Why does Dashboard rerender?" | Semantic + state dependency graph |
| "Which files affect /profile?" | Graph traversal from route node |
| "Where should I add dark mode?" | Semantic similarity to theme-related chunks |

Without intent detection, we'd use the same weights for all queries — producing mediocre results for all of them.

---

## 11.2 Intent Taxonomy

```python
class Intent(Enum):
    SYMBOL_LOOKUP         = "symbol_lookup"          # "where is X", "find X"
    ARCHITECTURE          = "architecture"           # "how does X work", "explain X flow"
    MODIFICATION_GUIDANCE = "modification_guidance"  # "where should I add X", "how to implement X"
    DEBUGGING             = "debugging"              # "why is X broken", "what's wrong with X"
    RERENDER_ANALYSIS     = "rerender_analysis"      # "why does X rerender", "unnecessary renders"
    ROUTE_TRACING         = "route_tracing"          # "which files affect /route", "route flow"
    IMPACT_ANALYSIS       = "impact_analysis"        # "what breaks if I change X", "what depends on X"
```

---

## 11.3 Rule-Based Classification (Primary)

Fast, zero-cost pattern matching:

```python
INTENT_RULES = {
    Intent.SYMBOL_LOOKUP: [
        r"\bwhere is\b",
        r"\bfind\b.{0,30}\b(function|component|hook|file|class)\b",
        r"\bshow me\b.{0,30}\b(definition|code|impl)\b",
        r"\bwhere (is|are|does)\b.{0,30}\bdefined\b",
        r"\blocate\b",
    ],
    Intent.ARCHITECTURE: [
        r"\bhow does\b",
        r"\bexplain\b",
        r"\bwhat is the flow\b",
        r"\barchitecture\b",
        r"\bwalk me through\b",
        r"\boverview\b",
    ],
    Intent.MODIFICATION_GUIDANCE: [
        r"\bwhere should I\b",
        r"\bhow (do I|can I|to)\b",
        r"\bwhere (to|would I)\b.{0,20}\badd\b",
        r"\bimplement\b",
        r"\bintegrate\b",
        r"\badd\b.{0,20}\bfeature\b",
    ],
    Intent.DEBUGGING: [
        r"\bwhy (is|does|did)\b.{0,30}\b(not|fail|broken|error)\b",
        r"\bwhat.{0,10}wrong\b",
        r"\bdebug\b",
        r"\bissue\b",
        r"\bfix\b",
        r"\bbug\b",
    ],
    Intent.RERENDER_ANALYSIS: [
        r"\brerender\b",
        r"\bre-render\b",
        r"\bunecessary render\b",
        r"\bwhy.{0,20}render\b",
        r"\bperformance.{0,20}render\b",
        r"\bmemo\b.*\brender\b",
    ],
    Intent.ROUTE_TRACING: [
        r"\broute\b",
        r"\b\/[a-z\-\/]+\b",   # URL-like pattern: /dashboard
        r"\bpage\b.{0,20}\bflow\b",
        r"\bnavigat\b",
        r"\bwhich files.{0,20}route\b",
    ],
    Intent.IMPACT_ANALYSIS: [
        r"\bwhat (breaks|changes)\b",
        r"\bwhat depends on\b",
        r"\bimpact\b",
        r"\baffect\b",
        r"\bif I (change|remove|modify)\b",
        r"\bdependencies of\b",
    ],
}

def classify_by_rules(query: str) -> Optional[Intent]:
    query_lower = query.lower()
    scores = {}
    for intent, patterns in INTENT_RULES.items():
        match_count = sum(1 for p in patterns if re.search(p, query_lower))
        if match_count > 0:
            scores[intent] = match_count

    if not scores:
        return None
    return max(scores, key=scores.get)
```

---

## 11.4 Embedding-Assisted Classification (Fallback)

When rules produce no match or ambiguous result (tie), use embedding similarity against intent exemplars:

```python
INTENT_EXEMPLARS = {
    Intent.SYMBOL_LOOKUP: [
        "where is the login function",
        "find the useAuth hook",
        "show me the handleSubmit definition",
    ],
    Intent.ARCHITECTURE: [
        "how does authentication work in this project",
        "explain the routing flow",
        "walk me through how data fetching works",
    ],
    # ... etc
}

class EmbeddingIntentClassifier:
    def __init__(self, encoder: ONNXEncoder):
        # Pre-compute exemplar embeddings at startup (tiny overhead)
        self.exemplar_matrix = {}  # intent → np.ndarray (N, 384)
        for intent, examples in INTENT_EXEMPLARS.items():
            self.exemplar_matrix[intent] = encoder.encode(examples)

    def classify(self, query: str) -> Intent:
        query_vec = encoder.encode([query])[0]  # (384,)

        best_intent = Intent.ARCHITECTURE
        best_score = -1.0

        for intent, exemplar_vecs in self.exemplar_matrix.items():
            # Max similarity against any exemplar
            scores = exemplar_vecs @ query_vec  # (N,)
            score = float(np.max(scores))
            if score > best_score:
                best_score = score
                best_intent = intent

        return best_intent
```

Fallback exemplar embeddings: 7 intents × 3 exemplars × 384 dim = ~8KB total in RAM.

---

## 11.5 Query Expansion

After intent is detected, the query is expanded with domain-specific synonyms:

```python
QUERY_EXPANSIONS = {
    "auth": ["authentication", "login", "token", "JWT", "session", "credentials"],
    "theme": ["dark mode", "light mode", "colors", "palette", "useTheme", "ThemeProvider"],
    "state": ["useState", "useReducer", "store", "Redux", "Zustand", "atoms"],
    "routing": ["Route", "useNavigate", "useLocation", "Link", "history", "path"],
    "fetch": ["API", "axios", "useQuery", "fetch", "REST", "HTTP", "endpoint"],
    "render": ["JSX", "return", "component", "DOM", "virtual DOM", "React.createElement"],
}

def expand_query(query: str, intent: Intent) -> str:
    tokens = query.lower().split()
    expansions = []
    for token in tokens:
        if token in QUERY_EXPANSIONS:
            expansions.extend(QUERY_EXPANSIONS[token])
    return query + " " + " ".join(set(expansions))
```

---

## 11.6 Retrieval Strategy Selection

The intent directly determines retrieval weights and strategy:

```python
STRATEGY_MAP = {
    Intent.SYMBOL_LOOKUP: RetrievalStrategy(
        lexical_weight=0.7,
        semantic_weight=0.2,
        graph_weight=0.1,
        graph_depth=1,           # Only direct neighbors
        top_k=5,
        use_graph=False          # Lexical is sufficient
    ),
    Intent.ARCHITECTURE: RetrievalStrategy(
        lexical_weight=0.2,
        semantic_weight=0.3,
        graph_weight=0.5,        # Heavy graph traversal
        graph_depth=3,
        top_k=10,
        use_graph=True
    ),
    Intent.MODIFICATION_GUIDANCE: RetrievalStrategy(
        lexical_weight=0.3,
        semantic_weight=0.5,
        graph_weight=0.2,
        graph_depth=2,
        top_k=8,
        use_graph=True
    ),
    Intent.DEBUGGING: RetrievalStrategy(
        lexical_weight=0.4,
        semantic_weight=0.4,
        graph_weight=0.2,
        graph_depth=2,
        top_k=10,
        use_graph=True
    ),
    Intent.RERENDER_ANALYSIS: RetrievalStrategy(
        lexical_weight=0.3,
        semantic_weight=0.4,
        graph_weight=0.3,
        graph_depth=2,
        edge_types=["MANAGES_STATE", "USES_HOOK", "RENDERS"],
        top_k=8,
        use_graph=True
    ),
    Intent.ROUTE_TRACING: RetrievalStrategy(
        lexical_weight=0.2,
        semantic_weight=0.2,
        graph_weight=0.6,        # Graph is primary for routes
        graph_depth=4,
        edge_types=["DEFINES_ROUTE", "RENDERS", "IMPORTS"],
        top_k=10,
        use_graph=True
    ),
    Intent.IMPACT_ANALYSIS: RetrievalStrategy(
        lexical_weight=0.2,
        semantic_weight=0.2,
        graph_weight=0.6,
        graph_depth=3,
        reverse=True,            # Use reverse BFS
        top_k=10,
        use_graph=True
    ),
}
```

---

## 11.7 Full Intent Router Pipeline

```python
class IntentRouter:
    def route(self, query: str) -> RoutingDecision:
        # 1. Normalize query
        normalized = query.strip().lower()

        # 2. Rule-based classification (fast, free)
        intent = classify_by_rules(normalized)

        # 3. If ambiguous, use embedding classifier
        if intent is None:
            intent = self.embedding_classifier.classify(query)

        # 4. Expand query for better retrieval
        expanded_query = expand_query(query, intent)

        # 5. Select retrieval strategy
        strategy = STRATEGY_MAP[intent]

        return RoutingDecision(
            original_query=query,
            expanded_query=expanded_query,
            intent=intent,
            strategy=strategy,
            confidence=self.compute_confidence(intent, normalized)
        )
```

---

## 11.8 Intent Router Memory

| Component | Memory |
|-----------|--------|
| Rule patterns (compiled regex) | ~50KB |
| Exemplar embeddings | ~8KB (7 × 3 × 384B) |
| Strategy map (static dict) | ~1KB |
| **Total** | **~60KB** |
