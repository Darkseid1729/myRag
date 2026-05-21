"""API call extractor: finds fetch/axios/useQuery calls in parsed source.

Populates the ``api_calls`` table so that queries like
"which endpoints does LoginPage call?" work correctly.

Supported patterns:
- fetch('/api/...', { method: 'POST' })
- axios.get('/api/...')
- axios.post / axios.put / axios.delete / axios.patch
- useQuery / useMutation (React Query)
- createApi (RTK Query base URLs)
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.utils import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# Generic fetch call
_FETCH_RE = re.compile(
    r"fetch\s*\(\s*[`'\"]([^`'\"]+)[`'\"]\s*(?:,\s*\{[^}]*method\s*:\s*['\"](\w+)['\"][^}]*)?\)",
    re.DOTALL,
)

# axios.METHOD(url)
_AXIOS_RE = re.compile(
    r"axios\s*\.\s*(get|post|put|patch|delete|head)\s*\(\s*[`'\"]([^`'\"]+)[`'\"]",
    re.IGNORECASE,
)

# fetch with template literal URLs (partial — captures prefix)
_FETCH_TEMPLATE_RE = re.compile(
    r"fetch\s*\(\s*`([^`$]+)(?:\$\{[^}]+\})?[^`]*`",
    re.DOTALL,
)

# useQuery / useMutation with query key + fetch
_USE_QUERY_RE = re.compile(
    r"use(?:Query|Mutation)\s*\([^)]*[`'\"]([/\w\-]+)[`'\"]",
    re.DOTALL,
)

# RTK createApi baseQuery
_RTK_BASE_URL_RE = re.compile(
    r"baseUrl\s*:\s*[`'\"]([^`'\"]+)[`'\"]"
)


@dataclass
class ExtractedApiCall:
    method: str       # GET, POST, PUT, DELETE, PATCH, UNKNOWN
    endpoint: str     # URL path or pattern
    client_type: str  # fetch | axios | useQuery | useMutation | rtk
    is_dynamic: bool  # True if URL contains template variables


def extract_api_calls(source: str) -> list[ExtractedApiCall]:
    """Extract all API call patterns from a source code string."""
    results: list[ExtractedApiCall] = []
    seen: set[tuple[str, str]] = set()

    def _add(method: str, endpoint: str, client_type: str, is_dynamic: bool) -> None:
        key = (method.upper(), endpoint)
        if key not in seen:
            seen.add(key)
            results.append(ExtractedApiCall(
                method=method.upper(),
                endpoint=endpoint,
                client_type=client_type,
                is_dynamic=is_dynamic,
            ))

    # fetch('...')
    for m in _FETCH_RE.finditer(source):
        url = m.group(1)
        method = (m.group(2) or "GET").upper()
        _add(method, url, "fetch", False)

    # fetch(`...${var}...`)
    for m in _FETCH_TEMPLATE_RE.finditer(source):
        url = m.group(1).strip()
        _add("GET", url + "*", "fetch", True)

    # axios.method('...')
    for m in _AXIOS_RE.finditer(source):
        method = m.group(1).upper()
        url = m.group(2)
        _add(method, url, "axios", False)

    # useQuery / useMutation
    for m in _USE_QUERY_RE.finditer(source):
        url = m.group(1)
        _add("GET", url, "useQuery", "}" in url or "${" in url)

    # RTK createApi baseUrl
    for m in _RTK_BASE_URL_RE.finditer(source):
        url = m.group(1)
        _add("GET", url + "/*", "rtk", True)

    return results
