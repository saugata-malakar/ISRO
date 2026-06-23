"""Vector index with top-k retrieval, encrypted at rest (README §1.3, §8 rag).

Uses FAISS (IndexFlatIP) for search when available, else a numpy brute-force
fallback — identical results for cosine on normalised vectors. The persisted
artifact is our own pickled {vectors, metas} blob encrypted with AES-256-GCM, so
nothing readable touches disk; the FAISS structure is rebuilt in memory on load.
"""

from __future__ import annotations

import pickle
from pathlib import Path

import numpy as np

from neuralink.config import get_settings
from neuralink.rag.corpus import Chunk, load_corpus
from neuralink.rag.embed import Embedder, get_embedder
from neuralink.schemas import RetrievedDoc
from neuralink.security import crypto

try:  # optional acceleration; numpy fallback otherwise
    import faiss  # type: ignore

    _HAS_FAISS = True
except Exception:  # noqa: BLE001
    _HAS_FAISS = False


def _backend_choice() -> str:
    want = get_settings().rag.index.backend.lower()
    if want == "faiss":
        return "faiss" if _HAS_FAISS else "numpy"
    if want == "numpy":
        return "numpy"
    return "faiss" if _HAS_FAISS else "numpy"  # auto


class RagIndex:
    def __init__(self, embedder: Embedder | None = None) -> None:
        self.embedder = embedder or get_embedder()
        self.vectors: np.ndarray = np.zeros((0, self.embedder.dim), dtype=np.float32)
        self.metas: list[dict] = []
        self._faiss = None
        self.backend = _backend_choice()

    # ------------------------------------------------------------------ #
    def build(self, chunks: list[Chunk]) -> RagIndex:
        texts = [c.text for c in chunks]
        self.vectors = self.embedder.encode(texts)
        self.metas = [
            {"doc_id": c.doc_id, "source": c.source, "kind": c.kind, "title": c.title, "text": c.text}
            for c in chunks
        ]
        self._build_search()
        return self

    def _build_search(self) -> None:
        if self.backend == "faiss" and len(self.vectors):
            index = faiss.IndexFlatIP(self.vectors.shape[1])
            index.add(self.vectors)
            self._faiss = index
        else:
            self._faiss = None

    # ------------------------------------------------------------------ #
    def query(self, text: str, k: int | None = None) -> list[RetrievedDoc]:
        k = k or get_settings().rag.top_k
        if not self.metas:
            return []
        q = self.embedder.encode([text])  # (1, dim), normalised
        k = min(k, len(self.metas))
        if self._faiss is not None:
            scores, idx = self._faiss.search(q, k)
            pairs = list(zip(idx[0].tolist(), scores[0].tolist(), strict=False))
        else:
            sims = (self.vectors @ q[0]).astype(float)
            order = np.argsort(-sims)[:k]
            pairs = [(int(i), float(sims[i])) for i in order]

        out: list[RetrievedDoc] = []
        for i, score in pairs:
            if i < 0:
                continue
            m = self.metas[i]
            out.append(
                RetrievedDoc(
                    doc_id=m["doc_id"], source=m["source"], kind=m["kind"],
                    title=m["title"], text=m["text"], score=round(float(score), 4),
                )
            )
        return out

    # ------------------------------------------------------------------ #
    def save(self, path: str | Path | None = None) -> Path:
        p = Path(path) if path else get_settings().faiss_path
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = pickle.dumps(
            {"dim": self.embedder.dim, "vectors": self.vectors, "metas": self.metas,
             "embed_backend": self.embedder.backend}
        )
        p.write_bytes(crypto.encrypt(payload, aad=b"rag-index"))
        return p

    @classmethod
    def load(cls, path: str | Path | None = None, embedder: Embedder | None = None) -> RagIndex:
        p = Path(path) if path else get_settings().faiss_path
        if not p.exists():
            raise FileNotFoundError(
                f"RAG index not found at {p}. Run `make index` (scripts/build_index.py) first."
            )
        data = pickle.loads(crypto.decrypt(p.read_bytes(), aad=b"rag-index"))
        obj = cls(embedder=embedder)
        obj.vectors = np.asarray(data["vectors"], dtype=np.float32)
        obj.metas = data["metas"]
        obj._build_search()
        return obj

    def __len__(self) -> int:
        return len(self.metas)


def build_and_save(path: str | Path | None = None) -> tuple[RagIndex, Path, int]:
    """Build the index from the on-disk corpus and persist it encrypted."""
    chunks = load_corpus()
    if not chunks:
        raise RuntimeError(
            "Corpus is empty. Run `make seed` (scripts/seed_data.py) to generate runbooks/incidents."
        )
    idx = RagIndex().build(chunks)
    out = idx.save(path)
    return idx, out, len(chunks)
