"""Alert correlation: sliding-window dedup / alert-storm suppression (README §8).

A flapping device can emit the same alert every tick. The correlator collapses
repeats of the same ``(device, event_type)`` within a rolling window (measured in
*simulated* seconds so demo time-compression behaves), letting the first through
and suppressing the rest until the window elapses. Escalation in severity always
passes (a WARNING that becomes CRITICAL is not a duplicate).
"""

from __future__ import annotations

from neuralink.config import get_settings
from neuralink.schemas import Alert, AlertSeverity


class AlertCorrelator:
    def __init__(self, window_s: float | None = None) -> None:
        self.window_s = window_s if window_s is not None else get_settings().detection.correlation_window_s
        # (device, event_type) -> (last_sim_time, last_severity)
        self._seen: dict[tuple[str, str], tuple[float, AlertSeverity]] = {}
        self.suppressed = 0

    def admit(self, alert: Alert) -> bool:
        """Return True if the alert should pass; False if it's a duplicate."""
        key = (alert.event.source_device, alert.event.event_type.value)
        now = alert.event.sim_time
        prev = self._seen.get(key)
        if prev is not None:
            last_t, last_sev = prev
            escalated = alert.severity == AlertSeverity.CRITICAL and last_sev != AlertSeverity.CRITICAL
            if (now - last_t) < self.window_s and not escalated:
                self.suppressed += 1
                return False
        self._seen[key] = (now, alert.severity)
        return True

    def filter(self, alert: Alert) -> Alert | None:
        return alert if self.admit(alert) else None
