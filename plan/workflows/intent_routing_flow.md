# Intent Detection Workflow

## Full Intent Routing Decision Tree

```
User Query Input
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│                    QUERY NORMALIZATION                          │
│  - strip(), lower()                                             │
│  - remove trailing punctuation                                  │
│  - normalize whitespace                                         │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│              RULE-BASED PATTERN MATCHING                        │
│                                                                 │
│  Pattern → Intent mapping (regex patterns):                    │
│                                                                 │
│  "where is X" ──────────────────────► SYMBOL_LOOKUP (0.9)     │
│  "find all X" ──────────────────────► SYMBOL_LOOKUP (0.9)     │
│  "show me X" ───────────────────────► SYMBOL_LOOKUP (0.8)     │
│  "locate X" ────────────────────────► SYMBOL_LOOKUP (0.8)     │
│                                                                 │
│  "how does X work" ─────────────────► ARCHITECTURE (0.9)      │
│  "explain X" ───────────────────────► ARCHITECTURE (0.85)     │
│  "walk me through" ─────────────────► ARCHITECTURE (0.85)     │
│  "overview of" ─────────────────────► ARCHITECTURE (0.8)      │
│                                                                 │
│  "where should I add" ──────────────► MODIFICATION (0.9)      │
│  "how do I implement" ──────────────► MODIFICATION (0.9)      │
│  "how can I add" ───────────────────► MODIFICATION (0.85)     │
│  "where to integrate" ──────────────► MODIFICATION (0.85)     │
│                                                                 │
│  "why is X not" ────────────────────► DEBUGGING (0.9)         │
│  "why does X fail" ─────────────────► DEBUGGING (0.9)         │
│  "what is wrong" ───────────────────► DEBUGGING (0.85)        │
│  "bug in" / "error in" ─────────────► DEBUGGING (0.8)         │
│                                                                 │
│  "why does X rerender" ─────────────► RERENDER (0.95)         │
│  "unnecessary renders" ─────────────► RERENDER (0.9)          │
│  "performance.*render" ─────────────► RERENDER (0.85)         │
│                                                                 │
│  URL pattern (/dashboard etc.) ─────► ROUTE_TRACING (0.9)    │
│  "routing flow" ────────────────────► ROUTE_TRACING (0.9)     │
│  "which files affect /X" ───────────► ROUTE_TRACING (0.95)    │
│  "route from" ──────────────────────► ROUTE_TRACING (0.85)    │
│                                                                 │
│  "what breaks if" ──────────────────► IMPACT (0.9)            │
│  "what depends on" ─────────────────► IMPACT (0.9)            │
│  "if I change X" ───────────────────► IMPACT (0.85)           │
│  "impact of" ───────────────────────► IMPACT (0.85)           │
│                                                                 │
└────────────────────────────┬────────────────────────────────────┘
                             │
                   ┌─────────┴──────────┐
                   │                    │
             Match found?          No match / Tie
                   │                    │
                   ▼                    ▼
          ┌────────────────┐   ┌──────────────────────────────┐
          │  RETURN INTENT │   │  EMBEDDING CLASSIFIER        │
          │  (fast path)   │   │                              │
          └────────────────┘   │  Encode query → (384,)       │
                               │  Compare to exemplar vecs    │
                               │                              │
                               │  SYMBOL_LOOKUP exemplars:    │
                               │  "where is X defined"        │
                               │  "find the useAuth hook"     │
                               │  "show me handleSubmit"      │
                               │  Max similarity → 0.84       │
                               │                              │
                               │  ARCHITECTURE exemplars:     │
                               │  "how does auth work"        │
                               │  "explain routing flow"      │
                               │  Max similarity → 0.71       │
                               │                              │
                               │  → Pick highest score        │
                               └──────────────┬───────────────┘
                                              │
                                              ▼
                                    RETURN INTENT + confidence
                                              │
                                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    QUERY EXPANSION                              │
│                                                                 │
│  Intent: ARCHITECTURE                                           │
│  Query:  "How does authentication work?"                        │
│                                                                 │
│  Token extraction: ["how", "authentication", "work"]           │
│                                                                 │
│  Expansion lookup:                                              │
│  "auth" → ["authentication", "login", "token", "JWT",          │
│             "session", "credentials", "useAuth", "AuthContext"] │
│                                                                 │
│  Expanded query:                                                │
│  "How does authentication work? authentication login token      │
│   JWT session credentials useAuth AuthContext"                  │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                   STRATEGY SELECTION                            │
│                                                                 │
│  Intent: ARCHITECTURE                                           │
│                                                                 │
│  Strategy:                                                      │
│    lexical_weight:  0.20  (less important — not exact lookup)  │
│    semantic_weight: 0.30  (conceptual match)                   │
│    graph_weight:    0.50  (structural relationships critical)   │
│    graph_depth:     3     (traverse deep into dependencies)     │
│    top_k:           10                                          │
│    edge_types:      ALL   (any relationship is relevant)        │
│    use_graph:       True                                        │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
                    RoutingDecision {
                        intent: ARCHITECTURE,
                        expanded_query: "...",
                        strategy: {...},
                        confidence: 0.84
                    }
                             │
                             ▼
                    → Pass to HybridRetriever
```

---

## Intent Confusion Matrix (Expected)

Shows where the classifier might confuse intents:

```
                    Predicted
              SYM  ARCH MOD  DBG  RER  RTE  IMP
Actual  SYM [ 0.92  0.03 0.02 0.01 0.00 0.00 0.02 ]
       ARCH [ 0.02  0.88 0.05 0.02 0.00 0.01 0.02 ]
        MOD [ 0.05  0.08 0.80 0.04 0.00 0.01 0.02 ]
        DBG [ 0.01  0.03 0.04 0.87 0.04 0.00 0.01 ]
        RER [ 0.00  0.02 0.01 0.06 0.89 0.00 0.02 ]
        RTE [ 0.01  0.02 0.02 0.00 0.00 0.94 0.01 ]
        IMP [ 0.02  0.03 0.05 0.03 0.02 0.02 0.83 ]
```

Main confusion points:
- MODIFICATION ↔ ARCHITECTURE: "How do I add dark mode?" can be both
- DEBUGGING ↔ RERENDER: "Why does X not render?" overlaps
- IMPACT ↔ ARCHITECTURE: "How does X work and what would change if..." overlaps

Mitigation: For ambiguous cases, use ensemble of the top-2 intents with averaged weights.
```
