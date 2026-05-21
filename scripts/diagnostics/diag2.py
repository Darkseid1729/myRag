"""Diagnose symbols table, WebcamScanner indexing, and graph edges."""
from src.storage.project_registry import ProjectRegistry

registry = ProjectRegistry()
db = registry.get_or_create(r"d:\backup(important)\myRag\testRepo2")

# 1. Symbols table state
sym_count = db.fetchall("SELECT COUNT(*) as cnt FROM symbols")[0]["cnt"]
print(f"Symbols table rows: {sym_count}")

sample_syms = db.fetchall("SELECT name, symbol_type, chunk_id FROM symbols LIMIT 10")
for r in sample_syms:
    print(f"  sym: {r['name']} [{r['symbol_type']}] -> chunk {r['chunk_id'][:8]}")

# 2. FTS symbols column filled?
fts_sample = db.fetchall("SELECT chunk_id, symbols FROM fts_chunks WHERE symbols != '' LIMIT 5")
print(f"\nFTS rows with non-empty symbols: {len(fts_sample)}")
for r in fts_sample:
    print(f"  symbols: {repr(r['symbols'][:80])}")

# 3. Is WebcamScanner indexed at all?
wc = db.fetchall(
    "SELECT c.id, c.name, c.chunk_type, c.start_line, f.path "
    "FROM chunks c JOIN files f ON c.file_id = f.id "
    "WHERE f.path LIKE '%WebcamScanner%' LIMIT 10"
)
print(f"\nWebcamScanner chunks: {len(wc)}")
for r in wc:
    print(f"  [{r['chunk_type']}] {r['name']} @ line {r['start_line']}")

# 4. What files are indexed?
files = db.fetchall("SELECT path FROM files ORDER BY path")
print(f"\nAll indexed files ({len(files)}):")
for f in files:
    print(f"  {f['path']}")

# 5. Graph edges summary
edges = db.fetchall("SELECT edge_type, COUNT(*) as cnt FROM graph_edges GROUP BY edge_type")
print(f"\nGraph edges by type:")
for r in edges:
    print(f"  {r['edge_type']}: {r['cnt']}")

# 6. DEFINES_ROUTE edges sample
routes = db.fetchall("SELECT from_id, to_id FROM graph_edges WHERE edge_type='DEFINES_ROUTE' LIMIT 5")
print(f"\nDEFINES_ROUTE edges: {len(routes)}")

db.close()
