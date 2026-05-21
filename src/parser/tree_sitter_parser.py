"""Tree-sitter based AST parser for JS/JSX/TS/TSX files."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.utils import get_logger

logger = get_logger(__name__)

# We attempt to import tree_sitter; fall back gracefully
try:
    import tree_sitter
    from tree_sitter import Language, Parser
    import tree_sitter_javascript as tsjs

    JS_LANGUAGE = Language(tsjs.language())
    _PARSER = Parser(JS_LANGUAGE)
    _TS_AVAILABLE = True
except Exception as exc:
    _TS_AVAILABLE = False
    logger.warning(f"tree-sitter unavailable ({exc}). Using regex fallback parser.")


@dataclass
class ParsedChunk:
    chunk_type: str          # COMPONENT | HOOK | FUNCTION | ROUTE | IMPORT_BLOCK | MISC
    name: str | None
    text: str
    start_line: int
    end_line: int
    symbols: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    exports: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Tree-sitter extraction helpers
# ---------------------------------------------------------------------------

def _node_text(node: Any, src: bytes) -> str:
    return src[node.start_byte:node.end_byte].decode(errors="replace")


# Keywords that should never be treated as meaningful symbols
_NOISE_KEYWORDS = frozenset({
    "import", "export", "default", "from", "as", "const", "let", "var",
    "function", "return", "class", "extends", "new", "this", "super",
    "if", "else", "for", "while", "do", "switch", "case", "break",
    "async", "await", "try", "catch", "finally", "throw",
    "true", "false", "null", "undefined",
    "React", "props", "children", "state",
})
_MIN_SYMBOL_LEN = 3

# Patterns for rich symbol extraction (module-level, always available)
_HOOK_CALL_PAT = re.compile(r"\b(use[A-Z][a-zA-Z0-9]+)\b")
_JSX_COMP_PAT  = re.compile(r"<([A-Z][a-zA-Z0-9_]*)\b")


def _rich_symbols(name: str | None, raw: str) -> list[str]:
    """Extract all meaningful identifiers from a chunk as symbols.

    Includes: the chunk's own name, all custom hook calls (useXxx),
    all PascalCase JSX component references, and camelCase identifiers
    longer than 4 chars that are called as functions.
    Filters out noise keywords and very short tokens.
    """
    seen: dict[str, None] = {}  # ordered set

    def _add(token: str) -> None:
        if token and len(token) >= _MIN_SYMBOL_LEN and token not in _NOISE_KEYWORDS:
            seen[token] = None

    if name:
        _add(name)

    # All hook calls (useXxx)
    for m in _HOOK_CALL_PAT.finditer(raw):
        _add(m.group(1))

    # All JSX component tags (<ComponentName)
    for m in _JSX_COMP_PAT.finditer(raw):
        _add(m.group(1))

    # Function-call-like camelCase identifiers (myFunc(  or  myFunc.)
    for m in re.finditer(r"\b([a-z][a-zA-Z]{3,})\s*[\.\(]", raw):
        token = m.group(1)
        if any(c.isupper() for c in token[1:]):  # must have at least one uppercase
            _add(token)

    return list(seen.keys())


def _extract_ts(src: bytes) -> list[ParsedChunk]:
    tree = _PARSER.parse(src)
    chunks: list[ParsedChunk] = []
    text = src.decode(errors="replace")

    def _lineno(byte_offset: int) -> int:
        return text[:byte_offset].count("\n") + 1

    def walk(node: Any) -> None:
        kind = node.type

        # Function / arrow function declarations
        if kind in ("function_declaration", "function_expression",
                     "arrow_function", "lexical_declaration"):
            raw = _node_text(node, src)
            name_match = re.search(r"(?:function\s+|const\s+)(\w+)", raw)
            name = name_match.group(1) if name_match else None
            chunk_type = "HOOK" if (name and name.startswith("use")) else "FUNCTION"

            if name and name[0].isupper() and "<" in raw:
                chunk_type = "COMPONENT"

            chunks.append(ParsedChunk(
                chunk_type=chunk_type,
                name=name,
                text=raw,
                start_line=_lineno(node.start_byte),
                end_line=_lineno(node.end_byte),
                symbols=_rich_symbols(name, raw),
            ))
            return

        # Import declarations
        if kind in ("import_declaration", "import_statement"):
            raw = _node_text(node, src)
            # Extract meaningful imported identifiers (filter noise keywords)
            imported = [
                t for t in re.findall(r"\b([A-Za-z_$][a-zA-Z0-9_$]+)\b", raw)
                if t not in _NOISE_KEYWORDS and len(t) >= _MIN_SYMBOL_LEN
            ]
            chunks.append(ParsedChunk(
                chunk_type="IMPORT_BLOCK",
                name=None,
                text=raw,
                start_line=_lineno(node.start_byte),
                end_line=_lineno(node.end_byte),
                symbols=list(dict.fromkeys(imported)),
            ))
            return

        for child in node.children:
            walk(child)

    walk(tree.root_node)
    return chunks


# ---------------------------------------------------------------------------
# Regex fallback parser
# ---------------------------------------------------------------------------

_FUNC_RE = re.compile(
    r"(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+(\w+)\s*\(",
    re.MULTILINE,
)
_ARROW_RE = re.compile(
    r"(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\(",
    re.MULTILINE,
)
_IMPORT_RE = re.compile(r"^import\s+.+from\s+['\"].+['\"];?$", re.MULTILINE)


def _extract_regex(source: str) -> list[ParsedChunk]:
    chunks: list[ParsedChunk] = []
    lines = source.splitlines()

    for m in list(_FUNC_RE.finditer(source)) + list(_ARROW_RE.finditer(source)):
        name = m.group(1)
        start_char = m.start()
        start_line = source[:start_char].count("\n") + 1

        end_line = min(start_line + 60, len(lines))
        text = "\n".join(lines[start_line - 1 : end_line])

        chunk_type = "HOOK" if name.startswith("use") else (
            "COMPONENT" if name[0].isupper() else "FUNCTION"
        )
        chunks.append(ParsedChunk(
            chunk_type=chunk_type,
            name=name,
            text=text,
            start_line=start_line,
            end_line=end_line,
            symbols=_rich_symbols(name, text),
        ))

    # Collect contiguous import lines
    import_lines = [i + 1 for i, l in enumerate(lines) if l.strip().startswith("import ")]
    if import_lines:
        import_text = "\n".join(lines[import_lines[0] - 1 : import_lines[-1]])
        imported = re.findall(r"\b([A-Za-z_$][a-zA-Z0-9_$]+)\b", import_text)
        chunks.append(ParsedChunk(
            chunk_type="IMPORT_BLOCK",
            name=None,
            text=import_text,
            start_line=import_lines[0],
            end_line=import_lines[-1],
            symbols=list(dict.fromkeys(imported)),
        ))

    return chunks


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def parse_file(path: str | Path) -> list[ParsedChunk]:
    """Parse a source file and return a list of structured code chunks."""
    source_bytes = Path(path).read_bytes()
    try:
        if _TS_AVAILABLE:
            chunks = _extract_ts(source_bytes)
        else:
            chunks = _extract_regex(source_bytes.decode(errors="replace"))
    except Exception as exc:
        logger.error(f"Parse error for {path}: {exc}")
        # Return whole file as MISC chunk
        source_text = source_bytes.decode(errors="replace")
        chunks = [ParsedChunk(
            chunk_type="MISC",
            name=None,
            text=source_text,
            start_line=1,
            end_line=source_text.count("\n") + 1,
        )]

    # Drop empty chunks
    return [c for c in chunks if c.text.strip()]
