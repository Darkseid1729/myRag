"""LLM provider implementations for Ollama, llama.cpp, and OpenAI."""

from __future__ import annotations

import json
import os
from typing import Iterable

import httpx


def _iter_ollama_stream(resp: httpx.Response) -> Iterable[str]:
    for line in resp.iter_lines():
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        token = payload.get("response")
        if token:
            yield token


def ollama_generate(base_url: str, model: str, prompt: str, stream: bool) -> str | Iterable[str]:
    url = f"{base_url.rstrip('/')}/api/generate"
    payload = {"model": model, "prompt": prompt, "stream": stream}
    if stream:
        with httpx.stream("POST", url, json=payload, timeout=None) as resp:
            resp.raise_for_status()
            return _iter_ollama_stream(resp)
    resp = httpx.post(url, json=payload, timeout=300)
    resp.raise_for_status()
    return resp.json().get("response", "")


def _iter_llamacpp_stream(resp: httpx.Response) -> Iterable[str]:
    for line in resp.iter_lines():
        if not line:
            continue
        if line.startswith("data:"):
            line = line[5:].strip()
        if line == "[DONE]":
            break
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        token = payload.get("content") or payload.get("response")
        if token:
            yield token


def llamacpp_generate(base_url: str, prompt: str, stream: bool) -> str | Iterable[str]:
    url = f"{base_url.rstrip('/')}/completion"
    payload = {"prompt": prompt, "stream": stream}
    if stream:
        with httpx.stream("POST", url, json=payload, timeout=None) as resp:
            resp.raise_for_status()
            return _iter_llamacpp_stream(resp)
    resp = httpx.post(url, json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    return data.get("content") or data.get("response", "")


def openai_generate(model: str, prompt: str, stream: bool) -> str | Iterable[str]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")

    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}"}
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a helpful code assistant."},
            {"role": "user", "content": prompt},
        ],
        "stream": stream,
    }

    if stream:
        def _iter_openai() -> Iterable[str]:
            with httpx.stream("POST", url, headers=headers, json=payload, timeout=None) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        payload = json.loads(data)
                        delta = payload["choices"][0]["delta"].get("content")
                        if delta:
                            yield delta
                    except Exception:
                        continue
        return _iter_openai()

    resp = httpx.post(url, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]
