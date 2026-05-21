"""Check why DEFINES_ROUTE is 0 and verify symbol quality."""
from src.storage.project_registry import ProjectRegistry

registry = ProjectRegistry()
db = registry.get_or_create(r"d:\backup(important)\myRag\testRepo2")

# Check what the App chunk looks like
app_chunks = db.fetchall(
    "SELECT c.id, c.name, c.chunk_type, c.text FROM chunks c "
    "JOIN files f ON c.file_id = f.id WHERE f.path LIKE '%App.jsx' LIMIT 5"
)
print("App.jsx chunks:")
for c in app_chunks:
    print(f"  [{c['chunk_type']}] {c['name']}: {repr(c['text'][:120])}")

# Try to find LoginSwitcher in symbols
ls = db.fetchall("SELECT name, symbol_type, chunk_id FROM symbols WHERE name='LoginSwitcher' LIMIT 5")
print(f"\nLoginSwitcher in symbols: {len(ls)}")
for r in ls:
    print(f"  {r['name']} [{r['symbol_type']}] -> {r['chunk_id'][:8]}")

# Try to find TeacherDashboard
td = db.fetchall("SELECT name, symbol_type, chunk_id FROM symbols WHERE name='TeacherDashboard' LIMIT 5")
print(f"TeacherDashboard in symbols: {len(td)}")
for r in td:
    print(f"  {r['name']} [{r['symbol_type']}] -> {r['chunk_id'][:8]}")

# Check chunks by name
td2 = db.fetchall("SELECT id, name, chunk_type FROM chunks WHERE name='TeacherDashboard' LIMIT 5")
print(f"TeacherDashboard chunks by name: {len(td2)}")
for r in td2:
    print(f"  {r['id'][:8]} [{r['chunk_type']}] {r['name']}")

# Check FTS symbols quality - are they noisy?
noise = db.fetchall(
    "SELECT name, COUNT(*) as cnt FROM symbols WHERE LENGTH(name) < 4 GROUP BY name ORDER BY cnt DESC LIMIT 10"
)
print("\nShort/noisy symbols (len < 4):")
for r in noise:
    print(f"  '{r['name']}': {r['cnt']} rows")

# loginTeacher specifically
lt = db.fetchall("SELECT name, symbol_type, chunk_id FROM symbols WHERE name='loginTeacher' LIMIT 3")
print(f"\nloginTeacher in symbols: {len(lt)}")
for r in lt:
    print(f"  {r['name']} [{r['symbol_type']}] -> {r['chunk_id'][:8]}")

# scanBiometric
sb = db.fetchall("SELECT name, symbol_type, chunk_id FROM symbols WHERE name='scanBiometric' LIMIT 3")
print(f"scanBiometric in symbols: {len(sb)}")

db.close()
