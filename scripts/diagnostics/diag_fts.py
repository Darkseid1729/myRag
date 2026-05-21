from src.storage.project_registry import ProjectRegistry

registry = ProjectRegistry()
project_root = r"d:\backup(important)\myRag\testRepo2"
db = registry.get_or_create(project_root)

fts_count = db.fetchall("SELECT COUNT(*) as cnt FROM fts_chunks")
print("FTS rows:", fts_count[0]["cnt"])

chunk_count = db.fetchall("SELECT COUNT(*) as cnt FROM chunks")
print("Chunks:", chunk_count[0]["cnt"])

# Sample symbols stored
rows = db.fetchall("SELECT chunk_id, symbols FROM fts_chunks LIMIT 5")
for r in rows:
    print("symbols sample:", repr(r["symbols"][:120]))

# Raw FTS match test - logout
try:
    rows = db.fetchall("SELECT chunk_id, rank FROM fts_chunks WHERE fts_chunks MATCH ? LIMIT 5", ("logout",))
    print("FTS 'logout' match count:", len(rows))
    for r in rows:
        print("  rank:", r["rank"])
except Exception as e:
    print("FTS logout ERROR:", e)

# Raw FTS match test - useTheme
try:
    rows = db.fetchall("SELECT chunk_id, rank FROM fts_chunks WHERE fts_chunks MATCH ? LIMIT 5", ("useTheme",))
    print("FTS 'useTheme' match count:", len(rows))
    for r in rows:
        print("  rank:", r["rank"])
except Exception as e:
    print("FTS useTheme ERROR:", e)

# Raw FTS match test - use Theme (camel split)
try:
    rows = db.fetchall("SELECT chunk_id, rank FROM fts_chunks WHERE fts_chunks MATCH ? LIMIT 5", ("use Theme",))
    print("FTS 'use Theme' match count:", len(rows))
    for r in rows:
        print("  rank:", r["rank"])
except Exception as e:
    print("FTS 'use Theme' ERROR:", e)

# Check what the sanitized query becomes for our test queries
import re
stop_words = {"who", "what", "where", "why", "how", "is", "are", "the", "a", "an", "does", "did", "to", "in", "on", "at"}
def sanitize(query):
    clean = re.sub(r'[\?*()"\ [\]{}:]', ' ', query)
    tokens = [t for t in clean.split() if t.lower() not in stop_words]
    if not tokens:
        tokens = clean.split()
    return " ".join(tokens)

queries = [
    "Add a logout feature",
    "Where is authentication handled?",
    "Find all places using useTheme",
]
for q in queries:
    print(f"sanitized '{q}' => '{sanitize(q)}'")
    try:
        rows = db.fetchall("SELECT chunk_id, rank FROM fts_chunks WHERE fts_chunks MATCH ? LIMIT 5", (sanitize(q),))
        print(f"  => {len(rows)} FTS results")
    except Exception as e:
        print(f"  => FTS ERROR: {e}")

db.close()
