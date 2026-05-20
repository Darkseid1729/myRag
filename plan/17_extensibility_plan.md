# 17 — EXTENSIBILITY PLAN

## 17.1 Plugin Architecture

The system uses a **hook-based plugin system** that allows extending behavior without modifying core code.

### Plugin Base Class

```python
# src/plugins/plugin_base.py

from abc import ABC, abstractmethod
from typing import List, Optional

class Plugin(ABC):
    """Base class for all system plugins"""

    name: str = "unnamed_plugin"
    version: str = "0.1.0"
    enabled: bool = True

    # Hooks available to plugins:

    def on_file_scanned(self, file_info: FileInfo) -> Optional[FileInfo]:
        """Called after each file is scanned. Return None to skip the file."""
        return file_info

    def on_chunk_created(self, chunk: Chunk) -> Optional[Chunk]:
        """Called after each chunk is created. Return None to drop the chunk."""
        return chunk

    def on_before_index(self, chunks: List[Chunk]) -> List[Chunk]:
        """Called before indexing. Can add/remove/modify chunks."""
        return chunks

    def on_query_received(self, query: str) -> str:
        """Called when a query arrives. Can rewrite query."""
        return query

    def on_intent_detected(self, query: str, intent: Intent) -> Intent:
        """Can override detected intent."""
        return intent

    def on_chunks_retrieved(self, chunks: List[RankedChunk]) -> List[RankedChunk]:
        """Called after retrieval. Can filter or reorder results."""
        return chunks

    def on_evidence_built(self, evidence: EvidencePack) -> EvidencePack:
        """Called before LLM. Can modify the evidence pack."""
        return evidence

    def on_response_generated(self, response: QueryResponse) -> QueryResponse:
        """Final hook before response is returned to user."""
        return response
```

### Plugin Registry

```python
class PluginRegistry:
    def __init__(self):
        self.plugins: List[Plugin] = []

    def register(self, plugin: Plugin):
        self.plugins.append(plugin)

    def run_hook(self, hook_name: str, *args, **kwargs):
        result = args[0] if args else None
        for plugin in self.plugins:
            if plugin.enabled:
                hook = getattr(plugin, hook_name, None)
                if hook:
                    result = hook(result, **kwargs)
        return result
```

---

## 17.2 Built-In Plugin Examples

### TypeScript Plugin

```python
# plugins/typescript_plugin/ts_extractor.py

class TypeScriptPlugin(Plugin):
    name = "typescript"

    def on_chunk_created(self, chunk: Chunk) -> Optional[Chunk]:
        if chunk.file_path.endswith(('.ts', '.tsx')):
            # Extract TypeScript-specific metadata
            chunk.metadata['type_annotations'] = self.extract_types(chunk.text)
            chunk.metadata['interfaces'] = self.extract_interfaces(chunk.text)
            chunk.metadata['generics'] = self.extract_generics(chunk.text)
        return chunk

    def extract_types(self, text: str) -> List[str]:
        # Match TypeScript type annotations
        return re.findall(r':\s*([A-Z][a-zA-Z<>,\s]+)', text)
```

### Test Coverage Plugin

```python
class TestCoveragePlugin(Plugin):
    name = "test_coverage"

    def on_chunks_retrieved(self, chunks: List[RankedChunk]) -> List[RankedChunk]:
        # Add test file information to each retrieved chunk
        for rc in chunks:
            test_file = self.find_test_file(rc.chunk.file_path)
            if test_file:
                rc.chunk.metadata['test_file'] = test_file
                rc.chunk.metadata['has_tests'] = True
        return chunks
```

---

## 17.3 Multi-Language Support

The architecture is language-agnostic. To add a new language:

1. Add a new Tree-sitter grammar: `pip install tree-sitter-python`
2. Create a language-specific extractor: `src/extractor/python_extractor.py`
3. Register in `file_classifier.py`
4. Update FTS5 normalization for language idioms

Language support roadmap:

| Language | Status | Effort |
|----------|--------|--------|
| JavaScript/JSX | ✅ Core | — |
| TypeScript/TSX | ✅ Plugin | Low |
| Vue SFC | Planned | Medium |
| Svelte | Planned | Medium |
| Python | Extensible | Low |
| Go | Extensible | Low |

---

## 17.4 TypeScript Support Details

TypeScript requires special handling:

```python
# Key additions for TypeScript:

# 1. Interface extraction
TYPESCRIPT_PATTERNS = {
    "interface": r"interface\s+(\w+)\s*\{",
    "type_alias": r"type\s+(\w+)\s*=",
    "generic": r"<([A-Z]\w*(?:,\s*[A-Z]\w*)*)>",
    "decorator": r"@(\w+)",
    "enum": r"enum\s+(\w+)\s*\{",
}

# 2. Stricter component detection (React.FC<Props>)
def is_ts_component(node: ExtractedNode) -> bool:
    return (
        is_react_component(node) or
        "React.FC" in node.text or
        "React.Component<" in node.text
    )

# 3. Type-aware dependency tracing
# Props interface → all callers who pass those props
```

---

## 17.5 Incremental Indexing

The `change_detector.py` enables incremental updates:

```python
def incremental_reindex(project_id: str, project_path: str):
    """Only reindex changed files"""

    # 1. Scan current state
    current_files = file_scanner.scan(project_path)

    # 2. Compare with stored state
    changes = change_detector.detect(current_files, project_id)

    # 3. Remove deleted file chunks from all indexes
    for deleted_path in changes.deleted:
        delete_file_data(deleted_path, db)

    # 4. Reindex new and modified files
    for file_info in changes.new + changes.modified:
        reindex_single_file(file_info, project_id)

    # 5. Rebuild affected graph edges
    rebuild_graph_for_files(changes.new + changes.modified, db)

    return IndexingReport(
        new_files=len(changes.new),
        modified_files=len(changes.modified),
        deleted_files=len(changes.deleted),
        time_ms=elapsed_ms
    )
```

---

## 17.6 Live File Watching

```python
# Uses watchdog (cross-platform file system events)

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class ProjectWatcher(FileSystemEventHandler):
    def __init__(self, project_id: str, indexing_pipeline):
        self.project_id = project_id
        self.pipeline = indexing_pipeline
        self.debounce_timer = None

    def on_modified(self, event):
        if event.src_path.endswith(('.js', '.jsx', '.ts', '.tsx')):
            self._debounced_reindex(event.src_path)

    def on_created(self, event):
        if not event.is_directory:
            self._debounced_reindex(event.src_path)

    def on_deleted(self, event):
        self.pipeline.delete_file(event.src_path, self.project_id)

    def _debounced_reindex(self, path: str, delay_ms: int = 500):
        """Wait 500ms after last change before reindexing (handles rapid saves)"""
        if self.debounce_timer:
            self.debounce_timer.cancel()
        self.debounce_timer = Timer(delay_ms/1000, self.pipeline.reindex_file, args=[path])
        self.debounce_timer.start()
```

---

## 17.7 VSCode Extension Plan

A VSCode extension provides in-editor access to the system.

### Extension Architecture

```
VSCode Extension (TypeScript)
├── extension.js          — Extension entry point
├── commands/
│   ├── queryCommand.js   — "Ask RAG" command
│   ├── explainCommand.js — "Explain this code" command
│   └── findCommand.js    — "Find all usages" command
├── providers/
│   ├── hoverProvider.js  — Hover to get summary of symbol
│   └── lensProvider.js   — Code lens showing dependency count
└── ui/
    └── queryPanel.js     — Webview panel for query interface
```

### Extension → Backend Communication

```javascript
// extension.js
const response = await fetch('http://localhost:8420/query', {
    method: 'POST',
    body: JSON.stringify({
        project_id: getProjectId(),
        query: userQuery,
        context_file: editor.document.fileName,
        context_line: editor.selection.active.line
    })
});
```

### Key VSCode Features

1. **"Ask about this code"** — Right-click any selection
2. **"Find all components using X"** — Right-click a hook/context
3. **Hover provider** — Show file summary when hovering over imports
4. **Inline code lens** — Show "Used by N components" above exports
5. **Command palette** — `Ctrl+Shift+P → "RAG: Ask"`

---

## 17.8 Editor Integration Beyond VSCode

| Editor | Integration Method | Effort |
|--------|-------------------|--------|
| VSCode | Native Extension API | ✅ Planned |
| Neovim | LSP-like plugin (Lua) | Medium |
| JetBrains | Plugin via REST API | Medium |
| Emacs | HTTP client + display | Low |
| Web UI | Bundled HTML + WebSocket | ✅ Included |
| CLI | `myrag ask "query"` | ✅ Included |

---

## 17.9 CLI Interface Plan

```bash
# Index a project
myrag index ./my-react-app

# Query the index
myrag ask "where is authentication handled?"

# Show dependency graph
myrag graph --from useAuth --depth 2

# List all components
myrag list components

# Watch mode (auto-reindex on changes)
myrag watch ./my-react-app

# Export index as JSON
myrag export ./my-react-app --format json
```
