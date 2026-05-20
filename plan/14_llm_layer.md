# 14 — OPTIONAL LLM LAYER

## 14.1 Design Philosophy: Retrieval-First

The LLM layer is **optional and late-stage**. The system is fully functional without it:
- Pure retrieval mode: returns ranked chunks + summaries
- With LLM: passes compact evidence pack to local/remote model for reasoning

The LLM never has access to raw files — it only sees:
1. Pre-retrieved, pre-ranked code chunks
2. A compact dependency summary
3. The user's question

This prevents hallucination about non-existent code and reduces token costs by 10–100×.

---

## 14.2 Abstract LLM Interface

All backends implement the same interface:

```python
# src/llm/base_llm.py

from abc import ABC, abstractmethod
from typing import Iterator

class BaseLLM(ABC):

    @abstractmethod
    def generate(self, prompt: str, max_tokens: int = 500) -> str:
        """Synchronous full-response generation"""
        pass

    @abstractmethod
    def stream(self, prompt: str, max_tokens: int = 500) -> Iterator[str]:
        """Streaming token-by-token generation"""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if the backend is reachable"""
        pass

    @abstractmethod
    def get_model_name(self) -> str:
        """Return the model identifier string"""
        pass

    @property
    def supports_streaming(self) -> bool:
        return True
```

---

## 14.3 Ollama Integration

Ollama is the **recommended local LLM backend**. It runs as a separate process and manages models independently.

```python
# src/llm/ollama_client.py

import httpx

class OllamaClient(BaseLLM):
    def __init__(self, model: str = "deepseek-coder:1.3b", base_url: str = "http://localhost:11434"):
        self.model = model
        self.base_url = base_url
        self.client = httpx.Client(timeout=60.0)

    def generate(self, prompt: str, max_tokens: int = 500) -> str:
        response = self.client.post(
            f"{self.base_url}/api/generate",
            json={
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "num_predict": max_tokens,
                    "temperature": 0.1,    # Low temp for precise code answers
                    "top_p": 0.9,
                }
            }
        )
        return response.json()["response"]

    def stream(self, prompt: str, max_tokens: int = 500) -> Iterator[str]:
        with self.client.stream("POST", f"{self.base_url}/api/generate",
            json={"model": self.model, "prompt": prompt, "stream": True}) as r:
            for line in r.iter_lines():
                if line:
                    data = json.loads(line)
                    if not data.get("done"):
                        yield data["response"]

    def is_available(self) -> bool:
        try:
            self.client.get(f"{self.base_url}/api/tags", timeout=2.0)
            return True
        except:
            return False

    def get_model_name(self) -> str:
        return f"ollama/{self.model}"
```

### Recommended Ollama Models

| Model | RAM | Speed | Quality |
|-------|-----|-------|---------|
| `deepseek-coder:1.3b` | ~1GB | Fast | ★★★☆☆ |
| `deepseek-coder:6.7b-q4` | ~4GB | Medium | ★★★★☆ |
| `codellama:7b-q4` | ~4GB | Medium | ★★★★☆ |
| `mistral:7b-q4` | ~4GB | Medium | ★★★★☆ |

---

## 14.4 llama.cpp Integration

For maximum control and minimum RAM usage, llama.cpp via subprocess:

```python
# src/llm/llamacpp_client.py

import subprocess
import tempfile

class LlamaCppClient(BaseLLM):
    def __init__(self, model_path: str, n_ctx: int = 2048, n_threads: int = 4):
        self.model_path = model_path
        self.n_ctx = n_ctx
        self.n_threads = n_threads
        self.executable = self._find_executable()

    def generate(self, prompt: str, max_tokens: int = 500) -> str:
        # Write prompt to temp file (avoids shell escaping issues)
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write(prompt)
            prompt_file = f.name

        result = subprocess.run([
            self.executable,
            "--model", self.model_path,
            "--file", prompt_file,
            "--n-predict", str(max_tokens),
            "--ctx-size", str(self.n_ctx),
            "--threads", str(self.n_threads),
            "--temp", "0.1",
            "--silent-prompt",
            "--no-display-prompt",
        ], capture_output=True, text=True, timeout=120)

        os.unlink(prompt_file)
        return result.stdout.strip()

    def is_available(self) -> bool:
        return (self.executable is not None and
                os.path.exists(self.model_path))
```

---

## 14.5 OpenAI API Integration

For users who prefer cloud inference with superior quality:

```python
# src/llm/openai_client.py

import openai

class OpenAIClient(BaseLLM):
    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        self.client = openai.OpenAI(api_key=api_key)
        self.model = model

    def generate(self, prompt: str, max_tokens: int = 500) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=0.1
        )
        return response.choices[0].message.content

    def stream(self, prompt: str, max_tokens: int = 500) -> Iterator[str]:
        stream = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=0.1,
            stream=True
        )
        for chunk in stream:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    def is_available(self) -> bool:
        return bool(self.client.api_key)
```

---

## 14.6 Prompt Construction Strategy

```python
# src/llm/prompt_builder.py

SYSTEM_PROMPT = """You are a precise code intelligence assistant.
Answer the developer's question using ONLY the code context provided.
Do not invent code that is not shown. If unsure, say so.
Be concise. Use code references (file name + line numbers) when possible."""

def build_prompt(evidence: EvidencePack, llm_type: str = "chat") -> str:
    sections = [SYSTEM_PROMPT, "\n\n=== CODE CONTEXT ===\n"]

    for i, ce in enumerate(evidence.chunks, 1):
        sections.append(
            f"\n[{i}] {ce.chunk.chunk_type.value}: {ce.chunk.name} "
            f"({basename(ce.chunk.file_path)}, lines {ce.chunk.start_line}–{ce.chunk.end_line})\n"
            f"Note: {ce.relationship_to_query}\n"
            f"```\n{ce.chunk.text[:800]}\n```\n"
        )

    if evidence.dependency_summary:
        sections.append(f"\n=== RELATIONSHIPS ===\n{evidence.dependency_summary}\n")

    sections.append(f"\n=== QUESTION ===\n{evidence.query}\n")
    sections.append("\n=== ANSWER ===\n")

    return "".join(sections)
```

---

## 14.7 Local-Only Operation

The system can run fully without the LLM layer. In no-LLM mode:
- Return ranked chunks directly
- Include rule-based summaries
- Include dependency summary
- Format as structured JSON or markdown

```python
def no_llm_response(evidence: EvidencePack) -> QueryResponse:
    return QueryResponse(
        query=evidence.query,
        intent=evidence.intent.value,
        answer=None,  # No LLM answer
        retrieved_chunks=[
            {
                "file": ce.chunk.file_path,
                "name": ce.chunk.name,
                "lines": f"{ce.chunk.start_line}–{ce.chunk.end_line}",
                "summary": ce.summary,
                "relevance": round(ce.relevance_score, 3),
                "code": ce.chunk.text
            }
            for ce in evidence.chunks
        ],
        relationships=evidence.dependency_summary,
        confidence=evidence.confidence
    )
```

---

## 14.8 LLM Backend Selection Logic

```python
def get_llm_backend(config: Config) -> BaseLLM:
    """Auto-select best available LLM backend"""

    if config.openai_api_key and config.prefer_cloud:
        return OpenAIClient(config.openai_api_key, config.openai_model)

    if config.ollama_enabled:
        client = OllamaClient(config.ollama_model, config.ollama_url)
        if client.is_available():
            return client

    if config.llamacpp_model_path:
        client = LlamaCppClient(config.llamacpp_model_path)
        if client.is_available():
            return client

    # No LLM available — run in retrieval-only mode
    return None
```
