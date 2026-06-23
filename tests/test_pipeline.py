"""LLM pipeline structured output (README §3 M5 DoD)."""

from __future__ import annotations

from neuralink.llm.engine import MockEngine
from neuralink.llm.pipeline import CopilotPipeline
from neuralink.schemas import (
    Alert,
    AlertSeverity,
    EventType,
    Metrics,
    NetworkEvent,
    SeverityRaw,
)
from neuralink.topology.blast_radius import compute_blast_radius


def _bgp_alert():
    ev = NetworkEvent(
        source_device="PE-Router-03",
        source_ip="10.0.0.3",
        event_type=EventType.BGP_SESSION_DOWN,
        severity_raw=SeverityRaw.CRITICAL,
        metrics=Metrics(cpu_pct=99, bgp_peers_up=1, bgp_peers_total=4),
        raw_message="%BGP-5-ADJCHANGE: neighbor 10.0.0.2 Down hold time expired",
        anomaly_score=95.0,
    )
    return Alert(event=ev, severity=AlertSeverity.CRITICAL, anomaly_score=95.0)


def test_structured_response_for_bgp():
    alert = _bgp_alert()
    blast = compute_blast_radius("PE-Router-03")
    tokens: list[str] = []
    resp = CopilotPipeline(engine=MockEngine()).run(alert, blast, on_token=tokens.append)

    assert tokens, "no tokens were streamed"
    assert "PE-Router-03" in resp.explanation
    assert resp.remediation, "no remediation steps"
    # The soft reset must be the recommended step (README §8 llm DoD).
    rec = [s for s in resp.remediation if s.recommended]
    assert len(rec) == 1
    assert "clear ip bgp" in rec[0].command and "soft" in rec[0].command
    assert 0.0 <= resp.confidence <= 1.0


def test_no_invented_devices():
    alert = _bgp_alert()
    blast = compute_blast_radius("PE-Router-03")
    resp = CopilotPipeline(engine=MockEngine()).run(alert, blast)
    # The grounded response must not name devices outside the topology.
    assert "PE-Router-99" not in resp.explanation
    assert "Router-42" not in resp.root_cause
