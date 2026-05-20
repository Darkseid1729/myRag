# 16 — QUERY EXECUTION WALKTHROUGH

## 16.1 Query: "Where is authentication handled?"

**Intent detected**: `ARCHITECTURE_UNDERSTANDING`
**Strategy**: graph_weight=0.5, semantic_weight=0.3, lexical_weight=0.2

---

```
Step 1 — Intent Detection (0.5ms)
    Rule match: "where is" → partially SYMBOL_LOOKUP
    Rule match: "how does" → no
    Keyword: "authentication" → signals ARCHITECTURE context
    Tie-break: embedding classifier → ARCHITECTURE (0.84 confidence)
    → Intent: ARCHITECTURE_UNDERSTANDING

Step 2 — Query Expansion (0.1ms)
    Original: "Where is authentication handled?"
    Expanded: "Where is authentication handled? auth login token JWT
               session credentials useAuth AuthContext verifyToken"

Step 3 — Lexical Retrieval (8ms)
    FTS5 MATCH: 'auth* OR login OR token OR session OR credential*'
    Results (top-50):
        c_045: useAuth.js (hook)          BM25: 0.91
        c_023: AuthContext.jsx (context)  BM25: 0.88
        c_112: LoginForm.jsx (component)  BM25: 0.75
        c_098: api.js (auth endpoints)   BM25: 0.70
        c_067: PrivateRoute.jsx          BM25: 0.62
        ... (45 more)

Step 4 — Semantic Retrieval on candidates (12ms)
    Query embed: "Where is authentication handled?"
    Compare against top-50 candidate embeddings:
        c_045: useAuth.js               cosine: 0.89
        c_023: AuthContext.jsx          cosine: 0.87
        c_112: LoginForm.jsx            cosine: 0.71
        c_101: jwtHelper.js             cosine: 0.69  ← NEW: not in lex top-5
        c_098: api.js                   cosine: 0.65

Step 5 — Graph Retrieval (10ms)
    Seeds: [c_045, c_023] (top lexical)
    BFS from c_045 (useAuth), depth=3, all edge types:
        depth 1: c_023 (AuthContext), c_112 (LoginForm), c_067 (PrivateRoute)
        depth 2: c_078 (Dashboard uses PrivateRoute), c_034 (App.jsx imports AuthProvider)
        depth 3: c_056 (UserProfile behind PrivateRoute)
    Graph scores: {c_023: 1.0, c_112: 0.7, c_067: 0.7, c_078: 0.4, c_034: 0.4}

Step 6 — Score Fusion (0.5ms)
    Weights: lex=0.2, sem=0.3, graph=0.5

    Chunk        LEX   SEM   GRAPH  FINAL
    c_045        0.91  0.89  0.0    0.182+0.267+0.0 = 0.449  ← seed itself = 0 graph
    c_023        0.88  0.87  1.0    0.176+0.261+0.5 = 0.937  ← HIGH (all three)
    c_112        0.75  0.71  0.7    0.150+0.213+0.35 = 0.713
    c_067        0.62  0.60  0.7    0.124+0.180+0.35 = 0.654
    c_101        0.40  0.69  0.0    0.080+0.207+0.0 = 0.287
    c_034        0.30  0.45  0.4    0.060+0.135+0.2 = 0.395

    Sorted: c_023 (0.937) > c_112 (0.713) > c_067 (0.654) > c_045 (0.449) > ...

Step 7 — Context Builder (3ms)
    Top-5 selected chunks:
    [1] c_023: AuthContext.jsx — "Directly defines authentication context and Provider"
    [2] c_112: LoginForm.jsx  — "Component that handles login form submission"
    [3] c_067: PrivateRoute.jsx — "Route guard that requires authentication"
    [4] c_045: useAuth.js     — "Hook that exposes authentication state and actions"
    [5] c_034: App.jsx        — "Wraps app in AuthProvider"
    Dependency summary: "AuthContext provides to LoginForm, PrivateRoute, Dashboard"

Step 8 — LLM Response (if enabled, ~500ms)
    Answer: "Authentication is handled across several files:
    1. **AuthContext.jsx** (lines 1-65): defines the auth context and AuthProvider
    2. **useAuth.js** (lines 1-85): hook that exposes isLoggedIn, login(), logout()
    3. **LoginForm.jsx** (lines 12-89): handles credential submission
    4. **PrivateRoute.jsx** (lines 1-35): guards protected routes
    AuthProvider wraps the entire app in App.jsx, making auth available everywhere."

Total: ~34ms (without LLM)
```

---

## 16.2 Query: "Find all places using useTheme"

**Intent detected**: `SYMBOL_LOOKUP`
**Strategy**: lexical_weight=0.7, semantic_weight=0.2, graph_weight=0.1

```
Step 1 — Intent: SYMBOL_LOOKUP (rule match: "find all")
Step 2 — Query unchanged (no expansion for exact symbol lookup)

Step 3 — Lexical: FTS5 MATCH 'symbols:useTheme OR text:useTheme'
    Results:
        c_089: ThemeContext.jsx — defines useTheme    BM25: 0.99
        c_112: LoginForm.jsx — uses useTheme          BM25: 0.92
        c_034: App.jsx — uses useTheme                BM25: 0.88
        c_078: Dashboard.jsx — uses useTheme          BM25: 0.88
        c_056: Navbar.jsx — uses useTheme             BM25: 0.85
        c_045: UserProfile.jsx — uses useTheme        BM25: 0.83

Step 4 — Graph: CONSUMES_CONTEXT edges from ThemeContext
    → confirms all consumers already found by lexical

Step 5 — Fusion (heavy lex weight = 0.7)
    All 6 chunks ranked, sorted by lexical score

Step 6 — Context Builder
    Evidence: 6 chunks with usages shown
    Summary: "useTheme is defined in ThemeContext.jsx and used in 5 components"

Answer: "useTheme is used in:
- ThemeContext.jsx:12 (definition)
- LoginForm.jsx:3
- App.jsx:5
- Dashboard.jsx:8
- Navbar.jsx:2
- UserProfile.jsx:14"

Total: ~12ms (fast lexical path)
```

---

## 16.3 Query: "How does routing flow from App.jsx?"

**Intent detected**: `ROUTE_TRACING`
**Strategy**: graph_weight=0.6, semantic_weight=0.2, lexical_weight=0.2

```
Step 1 — Intent: ROUTE_TRACING (rule match: "routing flow")
Step 2 — Query expansion: + "React Router Route Link navigate path"

Step 3 — Lexical: finds App.jsx chunk, Router, Route definitions

Step 4 — Graph Traversal from App.jsx chunk (depth=4, RENDERS + DEFINES_ROUTE edges):
    App.jsx
    ├──RENDERS──► Router component
    │   ├──DEFINES_ROUTE──► Route("/") → HomePage
    │   ├──DEFINES_ROUTE──► Route("/login") → LoginPage
    │   ├──DEFINES_ROUTE──► Route("/dashboard") → PrivateRoute
    │   │   └──RENDERS──► Dashboard
    │   │       ├──RENDERS──► Sidebar
    │   │       └──RENDERS──► MainContent
    │   └──DEFINES_ROUTE──► Route("/profile/:id") → UserProfile

Step 5 — All route-connected chunks extracted:
    App, Router, LoginPage, HomePage, PrivateRoute, Dashboard, Sidebar, UserProfile

Step 6 — Context: sorted by graph depth (nearest first)
Step 7 — Answer: full route tree visualization

Total: ~25ms
```

---

## 16.4 Query: "Why does Dashboard rerender?"

**Intent detected**: `RERENDER_ANALYSIS`
**Strategy**: graph uses STATE + RENDERS edges, semantic focuses on useEffect/useMemo

```
Step 1 — Intent: RERENDER_ANALYSIS (rule match: "rerender")
Step 2 — Expansion: + "useState useEffect useMemo useCallback memo re-render"

Step 3 — Lexical: finds Dashboard.jsx chunks with state + effect usage

Step 4 — Graph: MANAGES_STATE edges from Dashboard chunk
    Dashboard
    ├──MANAGES_STATE──► isLoading (useState)
    ├──MANAGES_STATE──► userData (useState)
    ├──USES_HOOK──► useUserData
    │   └──USES_API──► /api/users/me
    └──RENDERS──► DashboardContent (re-renders when parent does)

Step 5 — Semantic: finds useMemo opportunities, missing deps in useEffect

Step 6 — Context includes:
    - Dashboard component state declarations
    - useUserData hook (what it returns)
    - All useEffect dependencies in Dashboard

Step 7 — Answer:
    "Dashboard rerenders because:
    1. userData state updates on every API call in useUserData (no caching)
    2. useEffect in line 34 has incomplete dependency array [userId] but also reads
       from currentFilter state, causing extra renders
    3. DashboardContent receives a new object reference each render
       → Consider: useMemo for userData, useCallback for handlers"

Total: ~35ms
```

---

## 16.5 Query: "Where should I add dark mode?"

**Intent detected**: `MODIFICATION_GUIDANCE`
**Strategy**: semantic_weight=0.5, lexical_weight=0.3, graph_weight=0.2

```
Step 1 — Intent: MODIFICATION_GUIDANCE ("where should I")
Step 2 — Expansion: + "theme colors CSS variables ThemeProvider useTheme palette"

Step 3 — Lexical: finds any existing theme/color related code

Step 4 — Semantic: finds closest conceptual matches
    - ThemeContext.jsx (0.82 similarity to "dark mode theme")
    - index.css (0.71 — has CSS variables)
    - App.jsx (0.65 — top-level wrapper)

Step 5 — Graph: from ThemeContext, show what would be affected

Step 6 — Context: existing theme infrastructure + App.jsx structure

Step 7 — Answer:
    "Add dark mode in 3 places:
    1. **ThemeContext.jsx** (line 8): Add 'dark' to the theme state toggle
       → Already has ThemeProvider, just extend the context value
    2. **index.css** (line 1): Add CSS variables for dark mode
       → Use prefers-color-scheme or data-theme='dark' attribute
    3. **Navbar.jsx** (line 23): Add toggle button using useTheme hook
       → ThemeContext already exports setTheme, just call it

    5 components already consume useTheme and will auto-update."

Total: ~28ms
```
