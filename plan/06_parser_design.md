# 06 — PARSER DESIGN

## 6.1 File Scanning Strategy

Before parsing begins, the File Scanner builds a manifest:

```
scan(project_root)
    │
    ├── os.walk(project_root)
    ├── filter: include *.js, *.jsx, *.ts, *.tsx
    ├── exclude: node_modules/, dist/, .next/, coverage/, *.test.*, *.spec.*
    ├── classify each file → FileType
    └── compute content_hash (SHA-256 of file bytes)
```

The scanner returns a list of `FileInfo` objects, sorted by dependency order (leaves first) where possible.

---

## 6.2 Parser Architecture: Two-Layer Approach

The system uses **two complementary parsers**:

| Parser | Tech | Language Support | Speed | Memory |
|--------|------|-----------------|-------|--------|
| **Tree-sitter** (primary) | C binding via Python | JS, JSX, TS, TSX | Very fast (~2ms/file) | Low |
| **Babel Bridge** (fallback) | Node.js subprocess | JS, JSX, TS, TSX | Medium (~20ms/file) | Medium |

**Strategy**: Try Tree-sitter first. If it fails (e.g., very complex JSX), fall back to Babel via subprocess pipe.

---

## 6.3 Tree-sitter Parsing Pipeline

```python
# Pseudocode: tree_sitter_parser.py

def parse_file(file_path: str, file_content: str) -> ParseResult:
    # Step 1: Get language grammar
    language = get_grammar(file_path)  # JS or TSX grammar

    # Step 2: Parse — builds AST in C memory (NOT Python)
    tree = parser.parse(bytes(file_content, "utf8"))
    root_node = tree.root_node

    # Step 3: Extract all needed data in ONE traversal
    extractor = NodeExtractor(file_content)
    result = extractor.walk(root_node)  # Single-pass DFS

    # Step 4: IMMEDIATELY discard the AST
    del tree
    del root_node

    # Step 5: Return only the structured metadata
    return ParseResult(
        imports=result.imports,
        exports=result.exports,
        components=result.components,
        hooks=result.hooks,
        functions=result.functions,
        state_usages=result.state_usages,
        context_usages=result.context_usages,
        api_calls=result.api_calls,
        event_handlers=result.event_handlers,
        node_ranges=result.node_ranges  # {name: (start_line, end_line)}
    )
```

**Critical**: The AST (`tree`, `root_node`) is deleted immediately after extraction. Python's garbage collector will then free the C memory. This is why we never exceed ~500KB RAM during parsing despite processing complex files.

---

## 6.4 Node Extraction: Single-Pass DFS

```python
# Pseudocode: node_extractor.py

class NodeExtractor:
    def walk(self, node: Node) -> ExtractionResult:
        """Single-pass depth-first traversal"""
        result = ExtractionResult()

        def visit(node):
            node_type = node.type

            if node_type == "import_declaration":
                result.imports.append(self.extract_import(node))

            elif node_type == "export_statement":
                result.exports.append(self.extract_export(node))

            elif node_type == "function_declaration":
                func = self.extract_function(node)
                if self.is_react_component(func):
                    result.components.append(func)
                elif self.is_custom_hook(func):
                    result.hooks.append(func)
                else:
                    result.functions.append(func)

            elif node_type == "lexical_declaration":
                # Handle: const MyComp = () => <div />
                decl = self.extract_const_declaration(node)
                if decl:
                    result.components.append(decl)

            elif node_type == "call_expression":
                self.handle_call_expression(node, result)  # useState, useContext, fetch, etc.

            # Recurse into children
            for child in node.children:
                visit(child)

        visit(node)
        return result
```

---

## 6.5 React Component Detection

A function is classified as a **React component** if it satisfies ALL of:

```
1. Name starts with uppercase letter  (PascalCase)
2. Returns JSX:
   - Contains a jsx_element node
   - OR contains a return statement with < ... > content
3. Is either:
   - A named function declaration: function MyComp() { ... }
   - A const arrow: const MyComp = () => ...
   - A class extending React.Component or Component
```

```python
def is_react_component(func: ExtractedFunction) -> bool:
    return (
        func.name[0].isupper()
        and func.returns_jsx
        and not func.name.startswith("use")  # exclude hooks
    )
```

---

## 6.6 Custom Hook Detection

```python
def is_custom_hook(func: ExtractedFunction) -> bool:
    return (
        func.name.startswith("use")
        and len(func.name) > 3
        and func.name[3].isupper()  # e.g., useAuth, useTheme
    )
```

---

## 6.7 State Usage Extraction

The extractor detects all state-management call patterns:

```python
STATE_PATTERNS = {
    "useState":    r"const \[(\w+),\s*(\w+)\] = useState\((.+)?\)",
    "useReducer":  r"const \[(\w+),\s*(\w+)\] = useReducer\(",
    "useRef":      r"const (\w+) = useRef\(",
    "useSelector": r"const (\w+) = useSelector\(",  # Redux
    "useAtom":     r"const \[(\w+),\s*(\w+)\] = useAtom\(",  # Jotai
    "useStore":    r"const (\w+) = useStore\(",  # Zustand
}
```

Each match produces a `StateUsage` record with variable name, setter (if applicable), and type.

---

## 6.8 Import/Export Mapping

```python
# Input:  import { useAuth, AuthProvider } from '../hooks/useAuth'
# Output:
ImportRecord(
    source="'../hooks/useAuth'",
    specifiers=["useAuth", "AuthProvider"],
    is_default=False,
    resolved_path="/project/src/hooks/useAuth.jsx"  # resolved via path resolution
)
```

For import graph construction, all relative paths are resolved to absolute paths at parse time.

---

## 6.9 Context Provider/Consumer Detection

```python
CONTEXT_PATTERNS = [
    # Provider detection
    (r"<(\w+Context)\.Provider", "PROVIDER"),
    (r"createContext\(", "CREATE"),

    # Consumer detection
    (r"useContext\((\w+Context)\)", "CONSUMER"),
    (r"<(\w+Context)\.Consumer>", "CONSUMER"),
]
```

---

## 6.10 API Call Extraction

Detects all HTTP call patterns:

| Pattern | Detected As |
|---------|------------|
| `fetch('/api/...')` | FETCH |
| `axios.get('/api/...')` | AXIOS |
| `axios.post(...)` | AXIOS |
| `useQuery(['key'], () => fetch(...))` | REACT_QUERY |
| `useMutation(...)` | REACT_QUERY |
| Custom `apiClient.get(...)` | CUSTOM |

---

## 6.11 Event Handler Extraction

```python
EVENT_HANDLER_PATTERNS = [
    r"on[A-Z]\w+\s*=\s*\{",          # JSX prop: onClick={...}
    r"addEventListener\('(\w+)',",    # DOM: addEventListener
    r"on[A-Z]\w+\s*=\s*\(.*\)\s*=>", # Arrow handler
]
```

---

## 6.12 Parsing Pipeline Summary

```
File Content
    │
    ▼ Tree-sitter parse (2ms)
AST (C memory, ~300KB)
    │
    ▼ Single-pass DFS extraction (1ms)
ExtractedNodes: {imports, exports, components, hooks, functions, state, context, api, events}
    │
    ▼ del AST (memory freed)
    │
    ▼ Metadata classification
ParseResult: clean structured metadata (~3KB)
    │
    ▼ Pass to Chunker
```

Total parse time per file: ~3–8ms
Total parse memory peak per file: ~500KB (immediately freed)
