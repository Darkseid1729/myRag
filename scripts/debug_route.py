from __future__ import annotations

import re
from src.storage.project_registry import ProjectRegistry

project_root = r"d:\backup(important)\myRag\testRepo2\teacher-portal"
reg = ProjectRegistry()
db = reg.get_or_create(project_root)

row = db.fetchone("SELECT id, text FROM chunks WHERE name='App' LIMIT 1")
route_re = re.compile(r"<Route[^>]*path=['\"]([^'\"]+)['\"][^>]*element=\{<([A-Z][A-Za-z0-9_]*)")
if row:
    matches = route_re.findall(row["text"])
    print("Matches:", matches)
    for path, comp in matches:
        sym = db.fetchone("SELECT chunk_id, symbol_type FROM symbols WHERE name=?", (comp,))
        print(f"Symbol {comp}:", dict(sym) if sym else None)
else:
    print("No App chunk found")

db.close()
