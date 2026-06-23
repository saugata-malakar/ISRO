"""Embed the corpus into an encrypted vector index (M4).

Offline + deterministic. Produces ``data/runtime/rag.index.enc``.
"""

from __future__ import annotations

import time

from neuralink.config import get_settings
from neuralink.rag.index import build_and_save


def main() -> int:
    get_settings().ensure_runtime_dirs()
    t0 = time.perf_counter()
    idx, path, n_chunks = build_and_save()
    dt = (time.perf_counter() - t0) * 1000
    print(f"[index] embedded {n_chunks} chunks ({idx.backend} backend, dim={idx.embedder.dim}) "
          f"in {dt:.0f} ms")
    print(f"[index] saved encrypted index -> {path}")

    # Quick retrieval sanity check.
    t1 = time.perf_counter()
    hits = idx.query("BGP neighbor down hold timer expired on PE-Router-03", k=3)
    qt = (time.perf_counter() - t1) * 1000
    print(f"[index] sample query in {qt:.1f} ms; top hits:")
    for h in hits:
        print(f"    {h.score:.3f}  [{h.kind}] {h.title}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
