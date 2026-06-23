"""LLM pipeline: context -> model -> structured CopilotResponse (README §8 llm).

Assembles {alert, blast_radius, retrieved_docs}, streams the model output to an
optional token callback, then parses JSON and validates it against
:class:`CopilotResponse`. Retries once on parse failure, then falls back to a
safe grounded response built from the playbooks (the demo must never hard-fail).
"""

from __future__ import annotations

import json
from collections.abc import Callable

from neuralink.config import get_settings
from neuralink.llm.engine import LLMEngine, build_response_dict, get_engine
from neuralink.llm.prompts import build_user_prompt
from neuralink.rag.index import RagIndex
from neuralink.schemas import Alert, BlastRadius, CopilotResponse, RetrievedDoc
from neuralink.simulator.topology_loader import load_topology

TokenCallback = Callable[[str], None]


def _extract_json(text: str) -> dict:
    """Parse a JSON object out of model output (tolerates surrounding prose)."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(text[start : end + 1])
    raise ValueError("No JSON object found in model output.")


class CopilotPipeline:
    def __init__(self, engine: LLMEngine | None = None, index: RagIndex | None = None) -> None:
        self.engine = engine or get_engine()
        self._index = index
        self._index_tried = index is not None
        self._allowed = [n.id for n in load_topology().nodes]

    @property
    def index(self) -> RagIndex | None:
        if self._index is None and not self._index_tried:
            self._index_tried = True
            try:
                self._index = RagIndex.load()
            except Exception as exc:  # noqa: BLE001 — missing OR unreadable (wrong key)
                # Degrade gracefully: run without RAG grounding rather than fail.
                print(f"[rag] index unavailable ({exc}); proceeding without retrieval.")
                self._index = None
        return self._index

    def retrieve(self, alert: Alert, blast: BlastRadius) -> list[RetrievedDoc]:
        if self.index is None:
            return []
        query = (
            f"{alert.event.event_type.value} on {alert.event.source_device}: "
            f"{alert.event.raw_message}. Affected services "
            f"{', '.join(s.id for s in blast.affected_services)}. Remediation runbook."
        )
        return self.index.query(query)

    def run(
        self,
        alert: Alert,
        blast: BlastRadius,
        on_token: TokenCallback | None = None,
    ) -> CopilotResponse:
        docs = self.retrieve(alert, blast)
        prompt = build_user_prompt(alert, blast, docs, self._allowed)
        context = {"alert": alert, "blast": blast, "docs": docs}

        cfg = get_settings().llm
        attempts = cfg.json_retries + 1
        last_err: Exception | None = None
        for attempt in range(attempts):
            buf: list[str] = []
            stream_cb = on_token if attempt == 0 else None  # only stream the first try to UI
            for tok in self.engine.stream(prompt, context=context):
                buf.append(tok)
                if stream_cb:
                    stream_cb(tok)
            raw = "".join(buf)
            try:
                data = _extract_json(raw)
                resp = CopilotResponse.model_validate(data)
                if not resp.citations:
                    resp.citations = [d.title for d in docs[:3]]
                resp.model = getattr(self.engine, "name", "unknown")
                return resp
            except Exception as exc:  # noqa: BLE001
                last_err = exc

        # Safe fallback (never hard-fail the demo).
        data = build_response_dict(alert, blast, docs)
        resp = CopilotResponse.model_validate(data)
        resp.model = f"{getattr(self.engine, 'name', 'unknown')}+fallback"
        if last_err:
            resp.explanation = f"[fallback: model output unparseable ({last_err})] " + resp.explanation
        return resp
