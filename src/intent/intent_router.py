"""Intent router: rule-based + embedding-assisted query classification."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from src.utils import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Intent taxonomy
# ---------------------------------------------------------------------------

class Intent(str, Enum):
    SYMBOL_LOOKUP         = "symbol_lookup"
    ARCHITECTURE          = "architecture"
    MODIFICATION_GUIDANCE = "modification_guidance"
    DEBUGGING             = "debugging"
    RERENDER_ANALYSIS     = "rerender_analysis"
    ROUTE_TRACING         = "route_tracing"
    IMPACT_ANALYSIS       = "impact_analysis"


@dataclass
class RetrievalStrategy:
    lexical_weight: float
    semantic_weight: float
    graph_weight: float
    graph_depth: int
    top_k: int
    use_graph: bool
    reverse: bool = False
    edge_types: list[str] = field(default_factory=list)


@dataclass
class RoutingDecision:
    original_query: str
    expanded_query: str
    intent: Intent
    strategy: RetrievalStrategy
    confidence: float


# ---------------------------------------------------------------------------
# Rule patterns
# ---------------------------------------------------------------------------

_INTENT_RULES: dict[Intent, list[str]] = {
    Intent.SYMBOL_LOOKUP: [
        r"\bwhere is\b",
        r"\bfind\b.{0,50}\b(function|component|hook|file|class|places|all)\b",
        r"\bshow me\b.{0,30}\b(definition|code|impl)\b",
        r"\bwhere (is|are|does)\b.{0,30}\bdefined\b",
        r"\blocate\b",
        r"\ball places\b",
        r"\ball (files|components|uses)\b",
        r"\busing\b.{0,20}\b[a-z][a-zA-Z]{3,}\b",  # "using useTheme"
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
        r"\bwhere (to|would I).{0,20}\badd\b",
        r"\bimplement\b",
        r"\bintegrate\b",
        r"\badd\b.{0,30}\b(feature|component|page|button|calendar|logout|login)\b",
        r"\bcreate\b.{0,20}\b(feature|component|page)\b",
    ],
    Intent.DEBUGGING: [
        r"\bwhy (is|does|did|might|would|could)\b.{0,40}\b(not|fail|broken|error|missing|wrong|never)\b",
        r"\bwhat.{0,10}wrong\b",
        r"\bdebug\b",
        r"\bissue\b",
        r"\bfix\b",
        r"\bbug\b",
        r"\bnot (get|being|work|show|fire|trigger|mark|run)\b",
        r"\bfail(s|ed|ing)?\b",
        r"\bnever (fires?|runs?|works?|triggers?|marks?)\b",
        r"\bwhy might\b",
        r"\bnot getting\b",
        r"\bwon't\b",
        r"\bdoesn't\b.{0,20}\b(work|fire|run|trigger)\b",
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
        r"\b\/[a-z\-\/]+\b",
        r"\bpage\b.{0,20}\bflow\b",
        r"\bnavigat\b",
        r"\bwhich files.{0,20}(route|affect)\b",
        r"\bfiles affect\b",
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

# Pre-compile all patterns
_COMPILED_RULES: dict[Intent, list[re.Pattern]] = {
    intent: [re.compile(p, re.IGNORECASE) for p in patterns]
    for intent, patterns in _INTENT_RULES.items()
}

# Strategy map
_STRATEGY_MAP: dict[Intent, RetrievalStrategy] = {
    Intent.SYMBOL_LOOKUP: RetrievalStrategy(
        lexical_weight=0.7, semantic_weight=0.2, graph_weight=0.1,
        graph_depth=1, top_k=5, use_graph=False,
    ),
    Intent.ARCHITECTURE: RetrievalStrategy(
        lexical_weight=0.2, semantic_weight=0.3, graph_weight=0.5,
        graph_depth=3, top_k=10, use_graph=True,
    ),
    Intent.MODIFICATION_GUIDANCE: RetrievalStrategy(
        lexical_weight=0.3, semantic_weight=0.5, graph_weight=0.2,
        graph_depth=2, top_k=8, use_graph=True,
    ),
    Intent.DEBUGGING: RetrievalStrategy(
        lexical_weight=0.4, semantic_weight=0.4, graph_weight=0.2,
        graph_depth=2, top_k=10, use_graph=True,
    ),
    Intent.RERENDER_ANALYSIS: RetrievalStrategy(
        lexical_weight=0.3, semantic_weight=0.4, graph_weight=0.3,
        graph_depth=2, top_k=8, use_graph=True,
        edge_types=["MANAGES_STATE", "USES_HOOK", "RENDERS"],
    ),
    Intent.ROUTE_TRACING: RetrievalStrategy(
        lexical_weight=0.2, semantic_weight=0.2, graph_weight=0.6,
        graph_depth=4, top_k=10, use_graph=True,
        edge_types=["DEFINES_ROUTE", "RENDERS", "IMPORTS"],
    ),
    Intent.IMPACT_ANALYSIS: RetrievalStrategy(
        lexical_weight=0.2, semantic_weight=0.2, graph_weight=0.6,
        graph_depth=3, top_k=10, use_graph=True, reverse=True,
    ),
}

# Query expansion dictionary
_QUERY_EXPANSIONS: dict[str, list[str]] = {
    "auth": ["authentication", "login", "token", "JWT", "session", "credentials", "LoginSwitcher"],
    "theme": ["useTheme", "ThemeProvider", "darkmode", "lightmode", "palette", "colors"],
    "state": ["useState", "useReducer", "store", "Redux", "Zustand", "atoms"],
    "routing": ["Route", "useNavigate", "useLocation", "Link", "history", "path"],
    "fetch": ["API", "axios", "useQuery", "fetch", "REST", "HTTP", "endpoint"],
    "render": ["JSX", "return", "component", "DOM", "React"],
    "logout": ["signout", "deauthenticate", "logout", "session", "clearToken"],
    "login": ["signin", "authenticate", "LoginSwitcher", "credentials"],
    "sidebar": ["Sidebar", "nav", "navigation", "drawer"],
    "calendar": ["Calendar", "schedule", "date", "DatePicker"],
    "dashboard": ["Dashboard", "DashboardContent", "TeacherDashboard"],
}

# Keyword-level confidence boosters per intent
_CONFIDENCE_KEYWORDS: dict[Intent, list[str]] = {
    Intent.SYMBOL_LOOKUP: ["find", "where", "locate", "show", "all places", "using", "which"],
    Intent.ARCHITECTURE: ["how", "explain", "flow", "architecture", "overview"],
    Intent.MODIFICATION_GUIDANCE: ["add", "implement", "create", "integrate", "build"],
    Intent.DEBUGGING: ["why", "broken", "fail", "debug", "fix", "issue", "not get", "not mark", "never", "doesn't", "won't", "missing"],
    Intent.RERENDER_ANALYSIS: ["rerender", "render", "performance", "memo"],
    Intent.ROUTE_TRACING: ["route", "files affect", "page", "navigate", "which files"],
    Intent.IMPACT_ANALYSIS: ["impact", "affect", "depends", "breaks", "change"],
}


# ---------------------------------------------------------------------------
# Classifier functions
# ---------------------------------------------------------------------------

def _classify_by_rules(query: str) -> Optional[Intent]:
    scores: dict[Intent, int] = {}
    for intent, patterns in _COMPILED_RULES.items():
        match_count = sum(1 for p in patterns if p.search(query))
        if match_count > 0:
            scores[intent] = match_count
    if not scores:
        return None
    return max(scores, key=lambda i: scores[i])


def _expand_query(query: str) -> str:
    """Expand query with synonyms and camelCase identifier variants."""
    tokens = query.lower().split()
    expansions: list[str] = []
    for token in tokens:
        if token in _QUERY_EXPANSIONS:
            expansions.extend(_QUERY_EXPANSIONS[token])
    # Also extract camelCase identifiers from the original query and add their splits
    identifiers = re.findall(r"\b[a-z][a-zA-Z0-9]+[A-Z][a-zA-Z0-9]*\b|\b[A-Z][a-zA-Z0-9]+\b", query)
    for ident in identifiers:
        # Add both the identifier and its camelCase-split parts
        parts = re.sub(r"([a-z])([A-Z])", r"\1 \2", ident).lower()
        if parts != ident.lower():
            expansions.append(parts)
    if expansions:
        return query + " " + " ".join(dict.fromkeys(expansions))  # deduplicated
    return query


def _compute_confidence(intent: Intent, query: str) -> float:
    """Compute confidence using pattern matches + keyword boosting."""
    patterns = _COMPILED_RULES[intent]
    matched = sum(1 for p in patterns if p.search(query))
    # Base confidence from pattern ratio
    base = matched / max(1, len(patterns))

    # Keyword boost: check for high-signal words
    kw_list = _CONFIDENCE_KEYWORDS.get(intent, [])
    kw_matches = sum(1 for kw in kw_list if kw.lower() in query.lower())
    kw_boost = min(0.4, kw_matches * 0.15)

    # Pattern match absolute boost: each match adds 0.2
    pattern_boost = min(0.4, matched * 0.2)

    return min(1.0, base + kw_boost + pattern_boost)


# ---------------------------------------------------------------------------
# IntentRouter class
# ---------------------------------------------------------------------------

class IntentRouter:
    def __init__(self, encoder=None) -> None:
        # encoder is optional; used as embedding-based fallback
        self._encoder = encoder

    def route(self, query: str) -> RoutingDecision:
        intent = _classify_by_rules(query)

        if intent is None:
            if self._encoder:
                intent = self._embedding_classify(query)
            else:
                intent = Intent.ARCHITECTURE  # safe default

        expanded = _expand_query(query)
        strategy = _STRATEGY_MAP[intent]
        confidence = _compute_confidence(intent, query)

        logger.debug(f"Intent: {intent.value} (conf={confidence:.2f}) | query='{query[:60]}'")

        return RoutingDecision(
            original_query=query,
            expanded_query=expanded,
            intent=intent,
            strategy=strategy,
            confidence=confidence,
        )

    def _embedding_classify(self, query: str) -> Intent:
        """Embedding-based fallback; returns best intent via cosine similarity."""
        import numpy as np
        EXEMPLARS = {
            Intent.SYMBOL_LOOKUP: ["where is the login function", "find the useAuth hook"],
            Intent.ARCHITECTURE: ["how does authentication work", "explain the routing flow"],
            Intent.MODIFICATION_GUIDANCE: ["where should I add dark mode", "how to add a feature"],
            Intent.DEBUGGING: ["why is the login broken", "fix the state issue"],
            Intent.RERENDER_ANALYSIS: ["why does Dashboard rerender", "unnecessary render"],
            Intent.ROUTE_TRACING: ["which files affect /profile route", "route flow"],
            Intent.IMPACT_ANALYSIS: ["what breaks if I change useAuth", "impact of removing store"],
        }
        q_vec = self._encoder.encode([query])[0]
        best_intent = Intent.ARCHITECTURE
        best_score = -1.0
        for intent, texts in EXEMPLARS.items():
            exemplar_vecs = self._encoder.encode(texts)
            score = float(np.max(exemplar_vecs @ q_vec))
            if score > best_score:
                best_score = score
                best_intent = intent
        return best_intent
