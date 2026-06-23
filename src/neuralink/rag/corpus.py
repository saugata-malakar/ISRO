"""Load + chunk the runbook/incident corpus for RAG (README §8 rag)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from neuralink.config import get_settings


@dataclass
class Chunk:
    doc_id: str
    source: str
    kind: str  # "runbook" | "incident"
    title: str
    text: str


def chunk_text(text: str, size: int, overlap: int) -> list[str]:
    """Character-window chunking with overlap; splits on paragraph boundaries
    where possible to keep chunks coherent."""
    text = text.strip()
    if len(text) <= size:
        return [text] if text else []
    chunks: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + size, n)
        # Prefer to break on a paragraph/sentence boundary near the window end.
        if end < n:
            for sep in ("\n\n", "\n", ". "):
                cut = text.rfind(sep, start + size // 2, end)
                if cut != -1:
                    end = cut + len(sep)
                    break
        chunks.append(text[start:end].strip())
        if end >= n:
            break
        start = max(0, end - overlap)
    return [c for c in chunks if c]


def _incident_to_text(inc: dict) -> str:
    parts = [
        f"Incident {inc.get('id', '')}: {inc.get('title', '')}",
        f"Event type: {inc.get('event_type', '')}  Device: {inc.get('device', '')}",
        f"Summary: {inc.get('summary', '')}",
        f"Root cause: {inc.get('root_cause', '')}",
        f"Resolution: {inc.get('resolution', '')}",
        f"Impacted services: {', '.join(inc.get('impact_services', []) or ['none'])}",
        f"Duration: {inc.get('duration_min', 0)} min",
    ]
    return "\n".join(parts)


def load_corpus(
    runbooks_dir: Path | None = None,
    incidents_dir: Path | None = None,
    chunk_size: int | None = None,
    overlap: int | None = None,
) -> list[Chunk]:
    """Load runbooks (.md) + incidents (.json) and chunk them."""
    s = get_settings()
    rb_dir = runbooks_dir or s.runbooks_dir
    inc_dir = incidents_dir or s.incidents_dir
    size = chunk_size or s.rag.chunk_size
    ov = overlap if overlap is not None else s.rag.chunk_overlap

    chunks: list[Chunk] = []

    for md in sorted(rb_dir.glob("*.md")):
        raw = md.read_text(encoding="utf-8")
        first = next((ln for ln in raw.splitlines() if ln.strip()), md.stem)
        title = first.lstrip("# ").strip()
        for i, piece in enumerate(chunk_text(raw, size, ov)):
            chunks.append(
                Chunk(doc_id=f"{md.stem}#{i}", source=str(md), kind="runbook",
                      title=title, text=piece)
            )

    for js in sorted(inc_dir.glob("*.json")):
        try:
            inc = json.loads(js.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        text = _incident_to_text(inc)
        title = f"{inc.get('id', js.stem)}: {inc.get('title', '')}"
        for i, piece in enumerate(chunk_text(text, size, ov)):
            chunks.append(
                Chunk(doc_id=f"{js.stem}#{i}", source=str(js), kind="incident",
                      title=title, text=piece)
            )

    return chunks
