"""Embeddings for retrieval and duplicate checks (plan 2.2, 2.8).

"Embedding model goes through the gateway, local by default." With no
LLM_EMBED_MODEL configured, the built-in LocalHashEmbedder is used: feature
hashing of words and word pairs with sublinear term weights. It runs offline,
is deterministic, sends nothing anywhere, and is good at "same topic, same
words" retrieval within one course. Set LLM_EMBED_MODEL (e.g. Ollama
`nomic-embed-text`, or Gemini `gemini-embedding-001`) for semantic embeddings.

Vectors from different models are not comparable, so every stored vector
carries its model name and retrieval only compares like with like.
"""

from __future__ import annotations

import hashlib
import math
import re
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import httpx

from .gateway import CallRecord, post_with_retry

_STOP = set(["a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "have", "in", "into", "is", "it", "its", "of", "on", "or", "that", "the", "this", "to", "was", "were", "will", "with", "which", "can", "using", "use", "used", "their", "these", "those", "than", "then", "there", "such", "not", "but", "also", "may", "each", "other", "more", "most"])


class Embedder(Protocol):
    name: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class LocalHashEmbedder:
    """Offline, deterministic bag-of-words embedding (feature hashing)."""

    def __init__(self, dims: int = 1024) -> None:
        self.dims = dims
        self.name = f"local-hash-{dims}-v1"

    def _features(self, text: str) -> Counter:
        words = [w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 1 and w not in _STOP]
        stems = [w[:7] for w in words]  # crude stemming: 'regression' ~ 'regressions'
        return Counter(stems + [f"{a}_{b}" for a, b in zip(stems, stems[1:])])

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            v = [0.0] * self.dims
            for feat, tf in self._features(t).items():
                h = hashlib.blake2b(feat.encode(), digest_size=8).digest()
                idx = int.from_bytes(h[:4], "little") % self.dims
                sign = 1.0 if h[4] & 1 else -1.0
                v[idx] += sign * (1.0 + math.log(tf))
            norm = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / norm for x in v])
        return out


@dataclass
class RemoteEmbedder:
    """Provider embedding endpoint (Ollama /api/embed or OpenAI-compatible /embeddings)."""

    name: str
    kind: str  # ollama | openai
    base_url: str
    api_key: str | None
    on_call: Callable[[CallRecord], None] | None = None

    def embed(self, texts: list[str]) -> list[list[float]]:
        t0 = time.perf_counter()
        model = self.name.split(":", 1)[1]
        digest = hashlib.sha256("\n".join(texts).encode()).hexdigest()
        try:
            if self.kind == "ollama":
                r = post_with_retry(f"{self.base_url}/api/embed", json={"model": model, "input": texts}, timeout=120)
                vecs = r.json()["embeddings"]
            else:
                headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
                r = post_with_retry(f"{self.base_url}/embeddings", headers=headers,
                                    json={"model": model, "input": texts}, timeout=120)
                vecs = [d["embedding"] for d in sorted(r.json()["data"], key=lambda d: d["index"])]
            self._log(t0, digest, True)
            return vecs
        except (httpx.HTTPError, KeyError) as e:
            self._log(t0, digest, False, str(e)[:500])
            raise

    def _log(self, t0: float, digest: str, ok: bool, error: str | None = None) -> None:
        if self.on_call:
            self.on_call(CallRecord(provider=self.kind, model=self.name, prompt_id="embed", prompt_version="1",
                                    input_sha256=digest, latency_ms=int((time.perf_counter() - t0) * 1000),
                                    ok=ok, error=error))


def get_embedder(on_call: Callable[[CallRecord], None] | None = None) -> Embedder:
    from app.config import get_settings

    s = get_settings()
    model = s.llm_embed_model
    if not model:
        return LocalHashEmbedder()
    p = (s.llm_provider or "").lower()
    if p == "ollama":
        return RemoteEmbedder(f"ollama:{model}", "ollama", (s.llm_base_url or "http://localhost:11434").rstrip("/"),
                              None, on_call)
    defaults = {"groq": "https://api.groq.com/openai/v1", "openrouter": "https://openrouter.ai/api/v1",
                "gemini": "https://generativelanguage.googleapis.com/v1beta/openai"}
    base = (s.llm_base_url or defaults.get(p) or "").rstrip("/")
    if not base:
        return LocalHashEmbedder()
    return RemoteEmbedder(f"{p}:{model}", "openai", base, s.llm_api_key, on_call)


def cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0
