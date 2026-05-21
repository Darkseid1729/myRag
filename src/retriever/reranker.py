"""Optional cross-encoder reranker.

The CrossEncoder model is cached as a module-level singleton keyed by model
name so it is only loaded once per process (not once per query).

If ``sentence-transformers`` is not installed, this module silently falls back
to the input ordering (no reranking applied).
"""

from __future__ import annotations

from src.utils import get_logger

logger = get_logger(__name__)

# Module-level singleton cache: model_name → CrossEncoder instance
_RERANKER_CACHE: dict[str, object] = {}


def _get_cross_encoder(model_name: str) -> object | None:
    """Load or return the cached CrossEncoder for a model name."""
    if model_name in _RERANKER_CACHE:
        return _RERANKER_CACHE[model_name]
    try:
        from sentence_transformers import CrossEncoder  # type: ignore
        logger.info(f"Loading cross-encoder: {model_name}")
        model = CrossEncoder(model_name)
        _RERANKER_CACHE[model_name] = model
        return model
    except Exception as exc:
        logger.info(f"Cross-encoder not available ({exc}); skipping rerank.")
        # Cache None so we don't keep retrying
        _RERANKER_CACHE[model_name] = None
        return None


def maybe_rerank(query: str, chunks: list, model_name: str, top_k: int) -> list:
    """Rerank ``chunks`` with a cross-encoder if available.

    Args:
        query: The original user query.
        chunks: List of RankedChunk objects (or any object with a .text attribute).
        model_name: HuggingFace model identifier for the cross-encoder.
        top_k: Maximum number of results to return after reranking.

    Returns:
        Reranked slice of ``chunks`` sorted by cross-encoder score descending.
        If the cross-encoder is unavailable, returns the original ``chunks``.
    """
    if not chunks:
        return chunks

    model = _get_cross_encoder(model_name)
    if model is None:
        return chunks[:top_k]

    pairs = [(query, c.text) for c in chunks]
    try:
        scores = model.predict(pairs)  # type: ignore[union-attr]
    except Exception as exc:
        logger.warning(f"Cross-encoder predict failed: {exc}")
        return chunks[:top_k]

    for c, s in zip(chunks, scores):
        c.final_score = float(s)

    chunks.sort(key=lambda c: c.final_score, reverse=True)
    return chunks[:top_k]
