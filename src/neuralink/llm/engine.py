"""LLM engines (README §8 llm): a real llama.cpp wrapper and a deterministic
offline engine. Both expose the same streaming interface and emit JSON that the
pipeline parses into a :class:`CopilotResponse`.

Engine selection (config ``llm.mock``):
  * ``mock: true``  -> :class:`MockEngine` (no GGUF, fully offline, deterministic).
  * ``mock: false`` -> :class:`LlamaCppEngine`; if the GGUF is missing it FAILS
    LOUDLY with instructions (README §1.2 — never fetch at runtime).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Protocol

from neuralink.config import LlmCfg, get_settings
from neuralink.llm.prompts import PLAYBOOKS
from neuralink.schemas import Alert, BlastRadius, EventType, Risk

# --------------------------------------------------------------------------- #
# Deterministic grounded-response builder (used by MockEngine)
# --------------------------------------------------------------------------- #
_ROOT_CAUSE = {
    EventType.BGP_SESSION_DOWN: (
        "Most probable: control-plane CPU exhaustion on {dev} delayed BGP keepalives, "
        "so neighbor {peer} dropped on hold-timer expiry. "
        "Secondary: an underlying link/interface flap breaking the TCP session."
    ),
    EventType.CPU_SPIKE: (
        "Most probable: a process (likely IP-Routing / punted traffic) is starving the "
        "CPU on {dev}, trending toward exhaustion. "
        "Secondary: routing churn causing repeated recomputation."
    ),
    EventType.LINK_DOWN: (
        "Most probable: a physical link/optic failure (fiber cut) on {dev} took the "
        "interface down, severing LSPs on that path. "
        "Secondary: upstream provider outage."
    ),
    EventType.INTERFACE_FLAP: (
        "Most probable: a degraded SFP/fiber on {dev} causing repeated up/down with "
        "rising CRC errors. Secondary: a duplex/speed mismatch."
    ),
    EventType.HARDWARE_FAULT: (
        "Most probable: a thermal/fan fault on {dev} driving temperature past threshold "
        "toward shutdown. Secondary: a failing line card or power module."
    ),
    EventType.TRAFFIC_BLACKHOLE: (
        "Most probable: a stale FIB/LFIB entry on {dev} silently dropping traffic while "
        "counters look healthy. Secondary: an erroneous ACL/null-route."
    ),
    EventType.MEM_PRESSURE: (
        "Most probable: a memory leak on {dev} approaching malloc failure. "
        "Secondary: an oversized cache/session table."
    ),
}
_DEFAULT_ROOT = "Cause uncertain from available signals; verify with the read-only steps below."
_IPV4 = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")


def _peer_ip(alert: Alert) -> str:
    m = _IPV4.search(alert.event.raw_message)
    return m.group(1) if m else "10.0.0.2"


def _fill(template: str, alert: Alert, blast: BlastRadius) -> str:
    prefix = blast.affected_services[0].id if blast.affected_services else "0.0.0.0/0"
    return template.format(
        dev=alert.event.source_device,
        peer=_peer_ip(alert),
        iface="GigabitEthernet0/1",
        prefix=prefix,
    )


def build_response_dict(alert: Alert, blast: BlastRadius, docs: list) -> dict:
    """Construct a grounded CopilotResponse-shaped dict from structured context."""
    ev = alert.event
    etype = ev.event_type
    playbook = PLAYBOOKS.get(
        etype, [("show logging | last 50", Risk.LOW, "review recent events", True)]
    )
    remediation = []
    for i, (cmd, risk, note, rec) in enumerate(playbook, start=1):
        remediation.append(
            {
                "step": i,
                "command": _fill(cmd, alert, blast),
                "risk": risk.value if isinstance(risk, Risk) else str(risk),
                "note": note,
                "recommended": rec,
            }
        )

    svc_names = [s.id for s in blast.affected_services]
    impact = (
        f"{len(svc_names)} service(s) at risk: {', '.join(svc_names)}"
        if svc_names
        else "no mapped downstream services"
    )
    explanation = (
        f"{ev.event_type.value} detected on {ev.source_device} ({ev.source_ip}) "
        f"with anomaly score {alert.anomaly_score}/100 and blast radius {blast.score}/100. "
        f"Affected LSPs: {', '.join(blast.affected_lsps) or 'none'}; {impact}. "
        "Operator confirmation is required before any remediation runs."
    )
    root_cause = _fill(_ROOT_CAUSE.get(etype, _DEFAULT_ROOT), alert, blast)

    top = docs[:3]
    citations = [d.title for d in top]
    base_conf = 0.55 + 0.4 * (top[0].score if top else 0.0)
    if etype in PLAYBOOKS:
        base_conf = min(0.95, base_conf + 0.1)
    confidence = round(min(0.97, base_conf), 2)

    return {
        "explanation": explanation,
        "root_cause": root_cause,
        "remediation": remediation,
        "confidence": confidence,
        "citations": citations,
    }


# --------------------------------------------------------------------------- #
# Engine interface + implementations
# --------------------------------------------------------------------------- #
class LLMEngine(Protocol):
    name: str

    def stream(self, prompt: str, context: dict | None = None) -> Iterator[str]: ...

    def generate(self, prompt: str, context: dict | None = None) -> str: ...


class MockEngine:
    """Deterministic, offline engine. Builds grounded JSON from structured context
    and streams it word-by-word so the UI's streaming path is exercised exactly
    like the real model."""

    name = "mock-deterministic-v1"

    def generate(self, prompt: str, context: dict | None = None) -> str:
        if not context:
            return json.dumps({"explanation": "", "root_cause": "", "remediation": [], "confidence": 0.0})
        payload = build_response_dict(context["alert"], context["blast"], context.get("docs", []))
        return json.dumps(payload)

    def stream(self, prompt: str, context: dict | None = None) -> Iterator[str]:
        text = self.generate(prompt, context)
        # Emit in small chunks for a realistic token stream.
        yield from re.findall(r"\S+\s*", text)


class LlamaCppEngine:
    """Real local GGUF engine via llama-cpp-python."""

    def __init__(self, cfg: LlmCfg | None = None) -> None:
        self.cfg = cfg or get_settings().llm
        model_path = get_settings().llm_model_path
        if not model_path.exists():
            raise FileNotFoundError(
                f"LLM model not found: {model_path}\n"
                "The air-gapped runtime never downloads models. Either:\n"
                "  1) place a GGUF at that path (see scripts/download_models.sh, offline-prep), or\n"
                "  2) set llm.mock: true in config/settings.yaml to use the offline engine."
            )
        try:
            from llama_cpp import Llama  # local import; optional dep
        except ImportError as exc:
            raise RuntimeError(
                "llama-cpp-python is not installed. Install the 'llm' extra "
                "(pip install -e '.[llm]') during offline-prep, or set llm.mock: true."
            ) from exc

        n_threads = self.cfg.n_threads or None
        self._llm = Llama(
            model_path=str(model_path),
            n_ctx=self.cfg.n_ctx,
            n_gpu_layers=self.cfg.n_gpu_layers,
            n_threads=n_threads,
            seed=get_settings().seed,
            verbose=False,
        )
        self.name = model_path.name

    def _messages(self, prompt: str):
        from neuralink.llm.prompts import SYSTEM_PROMPT

        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

    def stream(self, prompt: str, context: dict | None = None) -> Iterator[str]:
        from typing import Any, cast

        response = self._llm.create_chat_completion(
            messages=self._messages(prompt),
            temperature=self.cfg.temperature,
            max_tokens=self.cfg.max_tokens,
            stream=True,
            response_format={"type": "json_object"},
        )
        for chunk in cast(Iterator[Any], response):
            try:
                delta = chunk["choices"][0]["delta"]["content"]
                if delta:
                    yield str(delta)
            except (KeyError, IndexError):
                pass

    def generate(self, prompt: str, context: dict | None = None) -> str:
        from typing import Any, cast

        out = self._llm.create_chat_completion(
            messages=self._messages(prompt),
            temperature=self.cfg.temperature,
            max_tokens=self.cfg.max_tokens,
            response_format={"type": "json_object"},
        )
        out_dict = cast(dict[str, Any], out)
        try:
            return str(out_dict["choices"][0]["message"]["content"] or "")
        except (KeyError, IndexError):
            return ""


def get_engine(cfg: LlmCfg | None = None) -> LLMEngine:
    cfg = cfg or get_settings().llm
    if cfg.mock:
        return MockEngine()
    return LlamaCppEngine(cfg)
