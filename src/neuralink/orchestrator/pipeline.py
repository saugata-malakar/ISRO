"""Orchestrator: event -> detection -> blast -> RAG -> LLM -> UI -> audit (README §8).

UI-agnostic: callers pass a :class:`Hooks` bundle and the orchestrator invokes the
callbacks as each stage completes (telemetry, forecast, alert, streaming tokens,
final response, audit). The TUI, the demo runner, and the API all drive the same
core. Processing one event is self-contained, so a slow inference never blocks
ingestion of the next event when run on a worker thread.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from neuralink.config import get_settings
from neuralink.detection.anomaly import AnomalyDetector
from neuralink.detection.correlation import AlertCorrelator
from neuralink.detection.forecast import TrendForecaster
from neuralink.ingestion.normaliser import normalise_event
from neuralink.ingestion.store import EventStore
from neuralink.llm.pipeline import CopilotPipeline
from neuralink.schemas import (
    Alert,
    AuditEntry,
    BlastRadius,
    CopilotResponse,
    EventType,
    ForecastWarning,
    NetworkEvent,
)
from neuralink.security.audit import AuditLog
from neuralink.topology.blast_radius import compute_blast_radius
from neuralink.topology.graph import NetworkGraph


def _noop(*_a, **_k) -> None:  # default hook
    return None


@dataclass
class Hooks:
    on_telemetry: Callable[[NetworkEvent], None] = _noop
    on_forecast: Callable[[ForecastWarning], None] = _noop
    on_alert: Callable[[Alert, BlastRadius], None] = _noop
    on_token: Callable[[str], None] = _noop
    on_response: Callable[[Alert, BlastRadius, CopilotResponse], None] = _noop
    on_audit: Callable[[AuditEntry], None] = _noop


@dataclass
class ProcessResult:
    event: NetworkEvent
    forecast: ForecastWarning | None = None
    alert: Alert | None = None
    blast: BlastRadius | None = None
    response: CopilotResponse | None = None
    audit_entries: list[AuditEntry] = field(default_factory=list)


class Orchestrator:
    def __init__(
        self,
        detector: AnomalyDetector | None = None,
        correlator: AlertCorrelator | None = None,
        forecaster: TrendForecaster | None = None,
        graph: NetworkGraph | None = None,
        copilot: CopilotPipeline | None = None,
        audit: AuditLog | None = None,
        store: EventStore | None = None,
    ) -> None:
        self.settings = get_settings()
        self.detector = detector or AnomalyDetector()
        self.correlator = correlator or AlertCorrelator()
        self.forecaster = forecaster or TrendForecaster()
        self.graph = graph or NetworkGraph()
        self.copilot = copilot or CopilotPipeline()
        self.audit = audit or AuditLog()
        self.store = store
        self.actor = self.settings.audit.actor_default
        self.role = self.settings.audit.role_default

    # ------------------------------------------------------------------ #
    def _audit(self, action: str, payload: dict, hooks: Hooks, out: list[AuditEntry]) -> None:
        entry = self.audit.append(self.actor, self.role, action, payload)
        out.append(entry)
        hooks.on_audit(entry)

    def _blast_for(self, event: NetworkEvent) -> BlastRadius:
        return compute_blast_radius(event.source_device, graph=self.graph)

    # ------------------------------------------------------------------ #
    def process_event(self, event: NetworkEvent, hooks: Hooks | None = None) -> ProcessResult:
        """Run one event through the full pipeline, invoking hooks as it goes."""
        hooks = hooks or Hooks()
        result = ProcessResult(event=event)

        event = normalise_event(event)
        if self.store is not None:
            self.store.add_event(event)

        # Forecast / early warning (runs on every event).
        warning = self.forecaster.observe(event)
        if warning is not None:
            result.forecast = warning
            hooks.on_forecast(warning)
            self._audit("FORECAST_WARNING", warning.model_dump(), hooks, result.audit_entries)

        # Anomaly detection + correlation.
        alert = self.detector.evaluate(event)  # also sets event.anomaly_score
        hooks.on_telemetry(event)
        if alert is None or self.correlator.filter(alert) is None:
            return result

        # Blast radius.
        blast = self._blast_for(event)
        result.alert, result.blast = alert, blast
        hooks.on_alert(alert, blast)
        self._audit(
            "ALERT_RAISED",
            {"alert_id": alert.alert_id, "severity": alert.severity.value,
             "device": event.source_device, "event_type": event.event_type.value,
             "anomaly_score": alert.anomaly_score, "blast_score": blast.score},
            hooks, result.audit_entries,
        )

        # RAG + LLM (only for real alerts — keeps the pipeline cheap on normal traffic).
        response = self.copilot.run(alert, blast, on_token=hooks.on_token)
        result.response = response
        hooks.on_response(alert, blast, response)
        self._audit(
            "COPILOT_INFERENCE",
            {"alert_id": alert.alert_id, "model": response.model,
             "confidence": response.confidence,
             "recommended": next((s.command for s in response.remediation if s.recommended), None)},
            hooks, result.audit_entries,
        )
        return result

    # ------------------------------------------------------------------ #
    def record_action(
        self, action: str, payload: dict, actor: str | None = None, role: str | None = None
    ) -> AuditEntry:
        """Audit an operator action (EXECUTE_STEP / SKIP_STEP / ESCALATE).

        Executing a step is *simulated* (README §8 tui): we log the intended
        command; nothing touches real devices."""
        return self.audit.append(actor or self.actor, role or self.role, action, payload)

    def is_link_event(self, event: NetworkEvent) -> bool:
        return event.event_type in {EventType.LINK_DOWN, EventType.INTERFACE_FLAP}
