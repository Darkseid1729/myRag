"""Check if symbols are visible during the graph pass and simulate _resolve_component."""
from src.storage.project_registry import ProjectRegistry
from src.graph.graph_builder import _resolve_component

registry = ProjectRegistry()
db = registry.get_or_create(r"d:\backup(important)\myRag\testRepo2")

# Simulate resolving the 3 route targets
for name in ["LoginSwitcher", "TeacherDashboard", "StudentDashboard"]:
    result = _resolve_component(db, name)
    print(f"_resolve_component('{name}') = {result[:8] if result else None}")

# Check if App COMPONENT chunk exists and has routes
app_comp = db.fetchone("SELECT id, text FROM chunks WHERE name='App' AND chunk_type='COMPONENT'")
if app_comp:
    import re
    _ROUTE_RE = re.compile(
        r"<Route[^>]*path=['\"]([^'\"]+)['\"][^>]*element=\{<([A-Z][A-Za-z0-9_]*)"
    )
    matches = _ROUTE_RE.findall(app_comp["text"])
    print(f"\nApp COMPONENT chunk id: {app_comp['id'][:8]}")
    print(f"Route matches in App chunk: {matches}")
else:
    print("App COMPONENT chunk not found!")

# Check graph_edges after rebuild
edges = db.fetchall("SELECT edge_type, COUNT(*) as cnt FROM graph_edges GROUP BY edge_type")
print("\nCurrent graph edges:")
for r in edges:
    print(f"  {r['edge_type']}: {r['cnt']}")

db.close()
