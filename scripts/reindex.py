"""Force a full re-index of testRepo2 by wiping and rebuilding the DB."""
import sqlite3
from pathlib import Path
from src.utils import sha1_of_string
from src.storage.project_registry import ProjectRegistry
from src.embeddings.onnx_encoder import ONNXEncoder
from src.indexer.indexing_pipeline import index_project
from src.config import get_config

project_root = r"d:\backup(important)\myRag\testRepo2"

cfg = get_config()
data_dir = Path(cfg["_data_dir"]) / "projects"
project_id = sha1_of_string(str(Path(project_root).resolve()))
db_path = data_dir / f"{project_id}.db"
print(f"DB path: {db_path}")

# Wipe with FK off
conn = sqlite3.connect(str(db_path))
conn.execute("PRAGMA foreign_keys = OFF")
for tbl in ["api_calls", "fts_chunks", "embeddings", "symbols",
            "graph_edges", "routes", "chunks", "files",
            "retrieval_cache", "summaries", "indexing_metadata"]:
    try:
        conn.execute(f"DELETE FROM {tbl}")
        print(f"  cleared: {tbl}")
    except Exception as e:
        print(f"  skip {tbl}: {e}")
conn.commit()
conn.close()
print("DB wiped. Starting re-index...")

encoder = ONNXEncoder()
registry = ProjectRegistry()
db = registry.get_or_create(project_root)
stats = index_project(project_root, db, encoder)
db.commit()
db.close()
print("Re-index complete:", stats)
