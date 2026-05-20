"""ONNX embedding encoder with int8 scalar quantization and LRU cache."""

from __future__ import annotations

import struct
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import NamedTuple

import numpy as np
from src.utils import get_logger
from src.config import get_config

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Quantization helpers
# ---------------------------------------------------------------------------

class QuantizedVector(NamedTuple):
    data: bytes   # int8 packed bytes
    scale: float  # dequantization scale


def quantize(vec: np.ndarray) -> QuantizedVector:
    """Scalar quantize float32 (384,) → int8 bytes."""
    scale = float(np.max(np.abs(vec))) or 1.0
    quantized = np.clip(np.round(vec / scale * 127), -127, 127).astype(np.int8)
    return QuantizedVector(data=quantized.tobytes(), scale=scale)


def dequantize(qv: QuantizedVector) -> np.ndarray:
    """Restore int8 bytes → float32 (384,) array."""
    arr = np.frombuffer(qv.data, dtype=np.int8).astype(np.float32)
    return arr * (qv.scale / 127.0)


# ---------------------------------------------------------------------------
# LRU cache for dequantized vectors
# ---------------------------------------------------------------------------

class VectorLRUCache:
    """Thread-safe LRU cache with byte-level capacity limit."""

    def __init__(self, max_bytes: int = 1_048_576) -> None:  # 1 MB default
        self._cache: OrderedDict[str, np.ndarray] = OrderedDict()
        self._sizes: dict[str, int] = {}
        self._total = 0
        self._max = max_bytes
        self._lock = threading.Lock()

    def get(self, key: str) -> np.ndarray | None:
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        return None

    def put(self, key: str, vec: np.ndarray) -> None:
        nbytes = vec.nbytes
        with self._lock:
            if key in self._cache:
                self._total -= self._sizes[key]
                del self._sizes[key]
                del self._cache[key]
            while self._total + nbytes > self._max and self._cache:
                oldest_key, _ = self._cache.popitem(last=False)
                self._total -= self._sizes.pop(oldest_key)
            self._cache[key] = vec
            self._sizes[key] = nbytes
            self._total += nbytes


# ---------------------------------------------------------------------------
# ONNX Encoder
# ---------------------------------------------------------------------------

class ONNXEncoder:
    """Wraps an ONNX Runtime inference session for sentence embeddings."""

    def __init__(self) -> None:
        cfg = get_config()
        model_name = cfg["embedding"]["model"]
        models_dir = Path(cfg["_models_dir"])
        self._model_dir = models_dir / model_name
        self._session = None
        self._tokenizer = None
        self._dims = cfg["embedding"]["dims"]
        self._cache = VectorLRUCache(
            max_bytes=cfg["memory"]["vector_lru_cache_kb"] * 1024
        )
        self._model_id = f"{model_name}-int8"
        self._lock = threading.Lock()

    def _ensure_loaded(self) -> None:
        if self._session is not None:
            return
        with self._lock:
            if self._session is not None:
                return
            self._download_if_needed()
            self._load_model()

    def _download_if_needed(self) -> None:
        model_file = self._model_dir / "model.onnx"
        if model_file.exists():
            return

        logger.info("Downloading embedding model (first run)…")
        self._model_dir.mkdir(parents=True, exist_ok=True)

        try:
            from huggingface_hub import snapshot_download
            snapshot_download(
                repo_id=f"sentence-transformers/{self._model_dir.name}",
                local_dir=str(self._model_dir),
                allow_patterns=["*.onnx", "tokenizer.json", "vocab.txt",
                                 "tokenizer_config.json", "special_tokens_map.json"],
            )
        except Exception as exc:
            logger.warning(f"HuggingFace download failed: {exc}. Trying optimum…")
            # Fallback: export via optimum
            import subprocess, sys
            subprocess.run([
                sys.executable, "-m", "optimum.exporters.onnx",
                "--model", f"sentence-transformers/{self._model_dir.name}",
                str(self._model_dir),
            ], check=True)

    def _load_model(self) -> None:
        import onnxruntime as ort
        from tokenizers import Tokenizer

        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 2
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

        onnx_candidates = list(self._model_dir.glob("*.onnx"))
        if not onnx_candidates:
            raise FileNotFoundError(f"No .onnx file found in {self._model_dir}")

        self._session = ort.InferenceSession(
            str(onnx_candidates[0]),
            sess_options=opts,
            providers=["CPUExecutionProvider"],
        )

        tok_file = self._model_dir / "tokenizer.json"
        if tok_file.exists():
            self._tokenizer = Tokenizer.from_file(str(tok_file))
            self._tokenizer.enable_padding(length=128)
            self._tokenizer.enable_truncation(max_length=128)

        logger.info(f"Embedding model loaded: {self._model_dir.name}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def encode(self, texts: list[str]) -> np.ndarray:
        """Encode a list of texts into float32 embeddings (N, dims)."""
        self._ensure_loaded()

        if self._tokenizer:
            encodings = self._tokenizer.encode_batch(texts)
            input_ids = np.array([e.ids for e in encodings], dtype=np.int64)
            attention_mask = np.array([e.attention_mask for e in encodings], dtype=np.int64)
            token_type_ids = np.zeros_like(input_ids, dtype=np.int64)
            inputs = {
                "input_ids": input_ids,
                "attention_mask": attention_mask,
                "token_type_ids": token_type_ids,
            }
            outputs = self._session.run(None, inputs)
            # Mean-pool over sequence dimension
            vecs = outputs[0].mean(axis=1)
        else:
            raise RuntimeError("Tokenizer not loaded")

        # L2 normalise
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1.0, norms)
        return (vecs / norms).astype(np.float32)

    def encode_and_quantize(self, text: str) -> QuantizedVector:
        vec = self.encode([text])[0]
        return quantize(vec)

    def cosine_similarity_batch(
        self,
        query_vec: np.ndarray,
        candidate_blobs: list[tuple[str, bytes, float]],
    ) -> list[tuple[str, float]]:
        """
        Compute cosine similarity between query_vec and a list of
        (chunk_id, blob_bytes, scale) tuples using the LRU cache.
        Returns list of (chunk_id, score) sorted descending.
        """
        results = []
        for chunk_id, blob, scale in candidate_blobs:
            cached = self._cache.get(chunk_id)
            if cached is None:
                qv = QuantizedVector(data=blob, scale=scale)
                cached = dequantize(qv)
                self._cache.put(chunk_id, cached)
            score = float(np.dot(query_vec, cached))
            results.append((chunk_id, score))
        results.sort(key=lambda x: x[1], reverse=True)
        return results
