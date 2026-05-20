# 10 — GRAPH ENGINE

## 10.1 Why a Graph Matters for Code Intelligence

Code is inherently a graph:
- Files import other files (import graph)
- Functions call other functions (call graph)
- Components render other components (render tree)
- Hooks share state (state dependency graph)
- Context providers wrap consumers (context graph)

Without graph awareness, retrieval is purely text-based and misses structural relationships like:
- *"AuthProvider is used by 12 components"*
- *"Changing useAuth would affect 8 components"*
- *"The /dashboard route chains through 4 files"*

---

## 10.2 Graph Storage Design

No external graph database needed. All edges stored in SQLite:

```sql
CREATE TABLE graph_edges (
    from_id   TEXT NOT NULL,   -- Source node (chunk_id or file_id)
    to_id     TEXT NOT NULL,   -- Target node
    edge_type TEXT NOT NULL,   -- See enum below
    weight    REAL DEFAULT 1.0
);

CREATE INDEX idx_edges_from ON graph_edges(from_id, edge_type);
CREATE INDEX idx_edges_to   ON graph_edges(to_id,   edge_type);
```

### Edge Type Enum

| Edge Type | Meaning |
|-----------|---------|
| `IMPORTS` | File A imports from File B |
| `CALLS` | Function A calls Function B |
| `USES_HOOK` | Component A uses Hook B |
| `RENDERS` | Component A renders Component B |
| `PROVIDES_CONTEXT` | Component A provides Context B |
| `CONSUMES_CONTEXT` | Component A consumes Context B |
| `MANAGES_STATE` | Component A manages State B |
| `DEFINES_ROUTE` | File A defines Route B |
| `USES_API` | Function A calls API endpoint B |

---

## 10.3 Import Graph

The import graph maps file-to-file dependencies.

### Construction

```python
# For each file, for each import statement:
# "import { useAuth } from '../hooks/useAuth'"
# → edge: (current_file_id) --IMPORTS--> (useAuth.jsx file_id)

def build_import_edges(file_id: str, imports: List[ImportRecord]) -> List[GraphEdge]:
    edges = []
    for imp in imports:
        if imp.resolved_path:  # Only internal imports
            target_file_id = get_or_create_file_id(imp.resolved_path)
            edges.append(GraphEdge(
                from_id=file_id,
                to_id=target_file_id,
                edge_type="IMPORTS",
                weight=1.0
            ))
    return edges
```

### Use Cases

| Query | Graph Operation |
|-------|----------------|
| "What files does AuthContext depend on?" | Outgoing IMPORTS from AuthContext |
| "What files depend on useAuth?" | Incoming IMPORTS to useAuth |
| "Find all transitive deps of App.jsx" | BFS with IMPORTS edges from App.jsx |

---

## 10.4 Function-Call Graph

Maps which functions call which other functions.

### Detection Strategy

Tree-sitter identifies all `call_expression` nodes. We check if the called function is defined in the same project:

```python
def build_call_edges(chunk: Chunk, defined_functions: Set[str]) -> List[GraphEdge]:
    edges = []
    # Extract all function call names from chunk text via AST
    for call_name in chunk.function_calls:
        if call_name in defined_functions:
            target_chunk_id = function_to_chunk[call_name]
            edges.append(GraphEdge(
                from_id=chunk.id,
                to_id=target_chunk_id,
                edge_type="CALLS"
            ))
    return edges
```

### Use Cases

| Query | Graph Operation |
|-------|----------------|
| "What does handleLogin call?" | Outgoing CALLS from handleLogin chunk |
| "What calls validateToken?" | Incoming CALLS to validateToken chunk |
| "Show call chain for submitForm" | DFS from submitForm, max depth 4 |

---

## 10.5 State Dependency Graph

Maps which components own which state variables.

```python
# Each useState creates an edge:
# Component --MANAGES_STATE--> "isLoading" (virtual node)
# Other components that read that state also get edges
```

This enables queries like:
- *"Which components are affected by the auth loading state?"*
- *"Where is user data stored?"*

---

## 10.6 Route Dependency Graph

Maps routes to their rendering components:

```
Route: /dashboard
    └──DEFINES_ROUTE──► Dashboard.jsx (component chunk)
        └──RENDERS──► Sidebar.jsx
        └──RENDERS──► DashboardContent.jsx
            └──USES_HOOK──► useUserData
                └──USES_API──► /api/users/me
```

Query: *"Which files affect the /dashboard route?"*
→ Graph traversal starting from Route(/dashboard) node, following all edge types

---

## 10.7 Context/Provider Graph

```
AuthProvider (in App.jsx)
    └──PROVIDES_CONTEXT──► AuthContext
        ├──CONSUMES_CONTEXT──► LoginForm (can use auth)
        ├──CONSUMES_CONTEXT──► Dashboard
        └──CONSUMES_CONTEXT──► UserProfile
```

Query: *"Which components depend on AuthProvider?"*
→ Find all CONSUMES_CONTEXT edges for AuthContext → return component chunks

---

## 10.8 Graph Traversal Algorithms

### BFS for Reachability

```python
def bfs(start_id: str, edge_types: List[str], max_depth: int, db) -> List[TraversalNode]:
    visited = {start_id}
    queue = deque([(start_id, 0, [start_id])])
    results = []

    while queue:
        node_id, depth, path = queue.popleft()

        if depth >= max_depth:
            continue

        placeholders = ','.join('?' * len(edge_types))
        neighbors = db.execute(
            f"SELECT to_id FROM graph_edges WHERE from_id=? AND edge_type IN ({placeholders})",
            [node_id] + edge_types
        ).fetchall()

        for (neighbor_id,) in neighbors:
            if neighbor_id not in visited:
                visited.add(neighbor_id)
                results.append(TraversalNode(
                    node_id=neighbor_id,
                    depth=depth+1,
                    path=path+[neighbor_id]
                ))
                queue.append((neighbor_id, depth+1, path+[neighbor_id]))

    return results
```

### Reverse BFS for Impact Analysis

Same algorithm but using `to_id` → `from_id` direction (incoming edges).

---

## 10.9 Dependency Tracing

```python
def trace_dependencies(chunk_id: str, max_depth: int = 3) -> DependencyReport:
    """Answer: 'What does chunk_id depend on?'"""
    return DependencyReport(
        direct_imports=bfs(chunk_id, ["IMPORTS", "CALLS"], depth=1),
        hooks_used=bfs(chunk_id, ["USES_HOOK"], depth=1),
        context_consumed=bfs(chunk_id, ["CONSUMES_CONTEXT"], depth=1),
        state_managed=bfs(chunk_id, ["MANAGES_STATE"], depth=1),
        transitive_deps=bfs(chunk_id, ["IMPORTS", "CALLS"], depth=max_depth)
    )
```

---

## 10.10 Impact Analysis

```python
def analyze_impact(chunk_id: str, max_depth: int = 3) -> ImpactReport:
    """Answer: 'What would be affected if chunk_id changed?'"""
    # Use REVERSE traversal (to_id → from_id direction)
    return ImpactReport(
        direct_dependents=reverse_bfs(chunk_id, ["IMPORTS", "CALLS", "USES_HOOK"], depth=1),
        context_consumers=reverse_bfs(chunk_id, ["CONSUMES_CONTEXT"], depth=1),
        all_affected=reverse_bfs(chunk_id, all_edge_types, depth=max_depth)
    )
```

---

## 10.11 Graph Scoring for Retrieval

Graph score for a candidate chunk given a query context:

```python
def graph_score(candidate_chunk_id: str, seed_chunk_ids: List[str], db) -> float:
    """
    Score based on graph proximity to seed chunks (from lexical/semantic results).
    Higher score = closer in graph to already-identified relevant chunks.
    """
    if not seed_chunk_ids:
        return 0.0

    min_distances = []
    for seed_id in seed_chunk_ids:
        dist = shortest_path_length(seed_id, candidate_chunk_id, db)
        min_distances.append(dist if dist is not None else 999)

    min_dist = min(min_distances)

    # Convert distance to score: distance 0 = 1.0, distance 1 = 0.7, distance 2 = 0.4, etc.
    score_map = {0: 1.0, 1: 0.7, 2: 0.4, 3: 0.2}
    return score_map.get(min_dist, 0.0)
```

---

## 10.12 Graph Memory Footprint

For a 50-file project:
- Average edges per file: ~15 (imports + calls + hooks + renders)
- Total edges: ~750
- Per edge: ~80 bytes (two 16-char IDs + type + weight)
- Total: **750 × 80 = 60KB**

Graph lives entirely on disk (SQLite). Only the active traversal frontier is in RAM:
- BFS frontier at depth 3: ~50 nodes × 80B = 4KB

**Graph RAM footprint: <10KB during traversal.**
