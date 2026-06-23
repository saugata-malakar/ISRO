"""Local embedding model wrapper (README §8 rag).

Default backend is a stateless **hashing** embedder (scikit-learn
``HashingVectorizer``): fully offline, deterministic, zero downloads — ideal for
an air-gapped build. An optional local ``sentence-transformers`` backend can be
enabled in config if a model is present on disk (still offline). All embedders
return L2-normalised float32 vectors so cosine similarity == dot product.
"""

from __future__ import annotations

from typing import Protocol

import numpy as np
from sklearn.feature_extraction.text import HashingVectorizer

from neuralink.config import EmbeddingCfg, get_settings


class Embedder(Protocol):
    backend: str
    dim: int

    def encode(self, texts: list[str]) -> np.ndarray: ...

    def state(self) -> bytes | None: ...


class HashingEmbedder:
    """Stateless hashing embedder — no fit, no vocabulary, no network."""

    backend = "hashing"

    def __init__(self, dim: int = 384) -> None:
        self.dim = dim
        self._vec = HashingVectorizer(
            n_features=dim, alternate_sign=False, norm="l2", ngram_range=(1, 2)
        )

    def encode(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        X = self._vec.transform(texts)
        return np.asarray(X.todense(), dtype=np.float32)

    def state(self) -> bytes | None:
        return None  # nothing to persist; reconstructable from dim


class SentenceTransformerEmbedder:
    """Optional local sentence-transformers backend (loaded from a local path)."""

    backend = "sentence-transformers"

    def __init__(self, model_path: str, dim: int = 384) -> None:
        from sentence_transformers import SentenceTransformer  # local import; optional dep

        self._model = SentenceTransformer(model_path, device="cpu")
        self.dim = self._model.get_sentence_embedding_dimension() or dim

    def encode(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        vecs = self._model.encode(texts, normalize_embeddings=True, convert_to_numpy=True)
        return np.asarray(vecs, dtype=np.float32)

    def state(self) -> bytes | None:
        return None


def get_embedder(cfg: EmbeddingCfg | None = None) -> Embedder:
    """Factory. Falls back to the offline hashing embedder when a richer backend
    is requested but unavailable (no model file / library)."""
    cfg = cfg or get_settings().rag.embedding
    backend = cfg.backend.lower()
    if backend in {"sentence-transformers", "st", "minilm"}:
        import os

        model_path = os.environ.get("NEURALINK_EMBED_MODEL_PATH", "").strip()
        if model_path:
            try:
                return SentenceTransformerEmbedder(model_path, dim=cfg.dim)
            except Exception as exc:  # noqa: BLE001 — degrade gracefully, never fetch
                print(f"[rag] sentence-transformers unavailable ({exc}); using hashing embedder.")
        else:
            print("[rag] NEURALINK_EMBED_MODEL_PATH not set; using offline hashing embedder.")
    # "hashing" (default) and "tfidf" both map to the stateless hashing embedder.
    return HashingEmbedder(dim=cfg.dim)
