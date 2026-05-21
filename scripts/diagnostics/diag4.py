"""Check why route regex fails on App.jsx."""
import re
from src.storage.project_registry import ProjectRegistry

_ROUTE_RE = re.compile(
    r"<Route[^>]*path=['\"]([^'\"]+)['\"][^>]*element=\{<([A-Z][A-Za-z0-9_]*)"
)

registry = ProjectRegistry()
db = registry.get_or_create(r"d:\backup(important)\myRag\testRepo2")

# Get all App.jsx chunks including COMPONENT
app_chunks = db.fetchall(
    "SELECT c.id, c.name, c.chunk_type, c.text FROM chunks c "
    "JOIN files f ON c.file_id = f.id WHERE f.path LIKE '%App.jsx'"
)
print(f"App.jsx total chunks: {len(app_chunks)}")
for c in app_chunks:
    print(f"\n  [{c['chunk_type']}] {c['name']}:")
    print(f"  {repr(c['text'][:300])}")
    matches = _ROUTE_RE.findall(c['text'])
    print(f"  Route regex matches: {matches}")

db.close()
