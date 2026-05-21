"""Embeddings module — ONNX encoder with int8 quantisation and LRU cache."""

from src.embeddings.onnx_encoder import ONNXEncoder, QuantizedVector, quantize, dequantize

__all__ = ["ONNXEncoder", "QuantizedVector", "quantize", "dequantize"]
