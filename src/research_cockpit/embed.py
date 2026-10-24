"""Local embedding wrappers. Embeddings never leave the machine.

`LocalEmbedder` wraps sentence-transformers (lazy import - torch is heavy).
`HashEmbedder` is a dependency-free bag-of-words hashing embedder used for
tests and offline smoke runs (select it with embeddings.model = "hash").
"""

from __future__ import annotations

import hashlib
import re
from typing import Protocol

import numpy as np


class Embedder(Protocol):
    dim: int

    def encode(self, texts: list[str]) -> np.ndarray: ...


class LocalEmbedder:
    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5"):
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(model_name)
        self.dim = self.model.get_sentence_embedding_dimension()

    def encode(self, texts: list[str]) -> np.ndarray:
        vecs = self.model.encode(
            texts, normalize_embeddings=True, show_progress_bar=False
        )
        return np.asarray(vecs, dtype=np.float32)


class HashEmbedder:
    """Deterministic hashed bag-of-words. Word overlap -> cosine similarity."""

    def __init__(self, dim: int = 256):
        self.dim = dim

    def encode(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, text in enumerate(texts):
            for word in re.findall(r"[a-z0-9]+", text.lower()):
                digest = hashlib.md5(word.encode()).digest()
                bucket = int.from_bytes(digest[:4], "little") % self.dim
                out[i, bucket] += 1.0
            norm = np.linalg.norm(out[i])
            if norm > 0:
                out[i] /= norm
        return out


def get_embedder(model_name: str) -> Embedder:
    if model_name == "hash":
        return HashEmbedder()
    return LocalEmbedder(model_name)
