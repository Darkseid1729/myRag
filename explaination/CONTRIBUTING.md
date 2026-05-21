# Contributing to MyRAG

Thank you for your interest in contributing!

---

## Development Setup

```bash
git clone <repo-url> myrag
cd myrag
python -m venv .venv
.venv\Scripts\Activate.ps1       # Windows
# source .venv/bin/activate      # Linux/macOS
pip install -e ".[dev]"
```

---

## Code Standards

### Python Style

- Follow **PEP 8** for formatting.
- Use **type annotations** on all public functions and class attributes.
- Maximum line length: **100 characters**.
- Docstrings on all public modules, classes, and functions.

```python
# Good
def count_tokens_approx(text: str) -> int:
    """Rough token count: ~4 chars per token."""
    return max(1, len(text) // 4)

# Bad (no type hints, no docstring)
def count_tokens(text):
    return len(text) // 4
```

### Import Order

Follow `isort` conventions (stdlib → third-party → local):

```python
from __future__ import annotations  # always first if present

import os
import time
from pathlib import Path

import numpy as np
from fastapi import FastAPI

from src.config import get_config
from src.utils import get_logger
```

### Logging

Use `get_logger(__name__)` from `src.utils`. Do **not** call `logging.basicConfig()` in modules — call `setup_logging()` only at app entry points (`cli.py`, `server.py`).

```python
from src.utils import get_logger
logger = get_logger(__name__)

logger.debug("Detailed trace info")
logger.info("Normal operation")
logger.warning("Recoverable issue")
logger.error("Something failed", exc_info=True)
```

### Error Handling

- **Don't swallow exceptions silently.** At minimum, log at WARNING level.
- Use specific exception types, not bare `except Exception`.
- In pipeline stages, catch exceptions per-file and continue — don't abort the entire index run for one bad file.

```python
# Good — logs and continues
for sf in changed_files:
    try:
        index_file(sf)
    except Exception as exc:
        logger.error(f"Failed to index {sf.path}: {exc}", exc_info=True)

# Bad — one bad file kills the entire run
for sf in changed_files:
    index_file(sf)  # raises on first error
```

---

## Writing Tests

All new features require tests. Tests live in:
- `tests/unit/` — fast, no I/O, no model loading
- `tests/integration/` — creates temp files, uses DBManager, mocks encoder

### Rules

1. **No network calls in tests.** Mock the ONNX encoder:
   ```python
   from unittest.mock import MagicMock, patch

   @patch("src.indexer.indexing_pipeline.ONNXEncoder")
   def test_index(MockEncoder, ...):
       mock = MagicMock()
       mock.encode_and_quantize.return_value = MagicMock(data=b'\x00'*384, scale=1.0)
       mock._model_id = "test"
       ...
   ```

2. **Use `tmp_path` fixture** (pytest built-in) for file system operations.
3. **Use `temp_db` fixture** from `conftest.py` for DB operations.
4. **Name test functions descriptively**: `test_chunker_splits_oversized_chunk`, not `test_chunker_1`.

### Running Tests

```bash
# Fast unit tests (recommended during development)
pytest tests/unit/ -v

# Full test suite
pytest tests/ -v

# Specific test file
pytest tests/unit/test_chunker.py -v

# With coverage
pytest tests/ --cov=src --cov-report=html
open htmlcov/index.html
```

---

## Adding a New Module

### Location

Follow the existing module structure:

| What you're adding | Where to put it |
|--------------------|----------------|
| New retrieval strategy | `src/retriever/` |
| New LLM provider | `src/llm/providers.py` |
| New file type support | `src/parser/` |
| New intent type | `src/intent/intent_router.py` |
| New API endpoint | `src/api/server.py` |
| New CLI command | `src/cli.py` |

### New Module Checklist

- [ ] Add `__init__.py` with public exports
- [ ] Add docstring to the module explaining purpose, design decisions, and usage
- [ ] Add type annotations to all public functions
- [ ] Add unit tests in `tests/unit/test_<module_name>.py`
- [ ] Update `PROJECT_STRUCTURE.md` with the new file
- [ ] Update `pyproject.toml` if adding a new dependency

---

## Adding a New Intent

1. Add the enum value to `Intent` in `src/intent/intent_router.py`
2. Add regex patterns to `_RULES`
3. Add exemplars to `_EXEMPLARS`
4. Add a `RetrievalStrategy` to `_STRATEGIES`
5. Add a unit test in `tests/unit/test_intent.py`

Example:
```python
class Intent(str, Enum):
    ...
    DEPENDENCY_GRAPH = "dependency_graph"   # ← new

_RULES = {
    ...
    Intent.DEPENDENCY_GRAPH: [
        re.compile(r"\bdependency\b.{0,20}\bgraph\b"),
        re.compile(r"\bwhat depends on\b"),
    ],
}

_EXEMPLARS = {
    ...
    Intent.DEPENDENCY_GRAPH: [
        "show me the dependency graph for useAuth",
        "what depends on the ThemeContext",
    ],
}
```

---

## Database Schema Changes

1. Edit `_SCHEMA_SQL` in `src/storage/db_manager.py`.
2. Add a migration in the `_MIGRATIONS` list for the change (so existing DBs are upgraded).
3. Update `ARCHITECTURE.md` schema section.
4. Update `tests/unit/test_db.py` to test the new table/column.

Migrations must be idempotent (`CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`).

---

## Pull Request Process

1. Create a branch: `git checkout -b feature/my-feature`
2. Make changes, write tests, run `pytest tests/ -v`
3. Ensure no regressions: all existing tests pass
4. Commit with a clear message:
   ```
   feat(retriever): add keyword density scoring to lexical results
   
   FTS5 BM25 rank was already being used, but normalisation was broken for
   very long chunks. Added a length-penalty factor to improve recall@5.
   ```
5. Open a PR with a description of what changed and why
6. Address review comments

---

## Commit Message Convention

```
<type>(<scope>): <short description>

<longer explanation if needed>
```

Types: `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `chore`

Scopes: `indexer`, `retriever`, `parser`, `db`, `api`, `cli`, `config`, `llm`, `graph`
