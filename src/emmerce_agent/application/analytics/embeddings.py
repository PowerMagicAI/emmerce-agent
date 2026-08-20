"""Hashed bag-of-tokens vectors — demo stand-in for Qdrant embeddings."""

from __future__ import annotations

import hashlib
import math

from emmerce_agent.infrastructure.memory.stores import _tokenize

DIM = 64
METHOD = "hashed_bow_v1"


def embed(text: str, *, dim: int = DIM) -> list[float]:
    vec = [0.0] * dim
    for tok in _tokenize(text or ""):
        digest = hashlib.md5(tok.encode("utf-8")).hexdigest()
        vec[int(digest, 16) % dim] += 1.0
    norm = math.sqrt(sum(x * x for x in vec))
    if norm <= 0:
        return vec
    return [x / norm for x in vec]


def cosine(a: list[float], b: list[float]) -> float:
    n = min(len(a), len(b))
    if n == 0:
        return 0.0
    return sum(a[i] * b[i] for i in range(n))
