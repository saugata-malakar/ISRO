"""Anomaly scoring + alerting (README §8 detection).

Maps the model score to 0-100 and applies configurable thresholds:
``>warning_score`` => WARNING, ``>critical_score`` => CRITICAL.
"""

from __future__ import annotations

from neuralink.config import DetectionCfg, get_settings
from neuralink.detection.baseline import AnomalyModel, load
from neuralink.schemas import Alert, AlertSeverity, NetworkEvent


class AnomalyDetector:
    def __init__(self, model: AnomalyModel | None = None, cfg: DetectionCfg | None = None) -> None:
        self.cfg = cfg or get_settings().detection
        self.model = model or load()

    def score(self, event: NetworkEvent) -> float:
        """Score an event 0-100 and record it on the event in-place."""
        s = round(self.model.score_event(event), 2)
        event.anomaly_score = s
        return s

    def evaluate(self, event: NetworkEvent) -> Alert | None:
        """Score, then raise an Alert if it crosses a threshold."""
        score = self.score(event)
        if score >= self.cfg.critical_score:
            severity = AlertSeverity.CRITICAL
        elif score >= self.cfg.warning_score:
            severity = AlertSeverity.WARNING
        else:
            return None
        return Alert(event=event, severity=severity, anomaly_score=score)
