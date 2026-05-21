"""Context builder: turns ranked chunks into a compact prompt context.

Token budget management:
- The header (user question) is always included.
- Chunks are added in score order until the budget is exhausted.
- If a chunk won't fully fit, it is truncated to fill the remaining budget.
- The final prompt ends with a clear instruction line for the LLM.

Format:
    User question:
    <query>

    Evidence:
    [1] src/auth/useAuth.ts:12-45
    Type: HOOK  Name: useAuth
    Score: 0.923
    <code>

    [2] ...

    Answer the user's question using only the evidence above.
    Be concise and cite file paths when relevant.
"""

from __future__ import annotations

from typing import Iterable, Any

from src.utils import count_tokens_approx, truncate_to_tokens


_INSTRUCTION = (
    "\nAnswer the user's question using only the evidence above. "
    "Be concise and cite file paths and line numbers when relevant."
)


def build_context(query: str, chunks: Iterable[Any], max_tokens: int = 4096) -> str:
    """Build a prompt string from a query and ranked code chunks.

    Args:
        query: The original user question.
        chunks: Iterable of objects with attributes:
                file_path, start_line, end_line, chunk_type, name,
                final_score, text.
        max_tokens: Maximum approximate token budget for the full prompt.

    Returns:
        A formatted string suitable for passing to an LLM.
    """
    header = (
        f"User question:\n{query.strip()}\n\n"
        "Evidence:\n"
    )
    footer = _INSTRUCTION
    overhead = count_tokens_approx(header) + count_tokens_approx(footer)
    budget = max_tokens - overhead

    if budget <= 0:
        return header + footer

    parts: list[str] = [header]
    used = 0
    chunk_list = list(chunks)

    for i, c in enumerate(chunk_list, 1):
        file_path = getattr(c, "file_path", "unknown")
        start = getattr(c, "start_line", 0)
        end = getattr(c, "end_line", 0)
        chunk_type = getattr(c, "chunk_type", "")
        name = getattr(c, "name", None)
        score = getattr(c, "final_score", 0.0)
        text = getattr(c, "text", "").strip()

        # Format the code block with language hint based on file extension
        ext = file_path.rsplit(".", 1)[-1] if "." in file_path else "js"
        lang = {"ts": "typescript", "tsx": "typescript", "js": "javascript",
                "jsx": "javascript"}.get(ext, ext)

        block = (
            f"\n[{i}] {file_path}:{start}-{end}\n"
            f"Type: {chunk_type}  Name: {name or 'n/a'}  Score: {score:.3f}\n"
            f"```{lang}\n{text}\n```\n"
        )
        block_tokens = count_tokens_approx(block)

        if used + block_tokens > budget:
            remaining = budget - used
            if remaining > 50:  # Only add if meaningful content fits
                parts.append(truncate_to_tokens(block, remaining))
            break

        parts.append(block)
        used += block_tokens

    parts.append(footer)
    return "".join(parts).strip() + "\n"