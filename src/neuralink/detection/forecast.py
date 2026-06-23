"""Trend-based early warning (README feature #8, §8 detection).

Keeps a short rolling history of a metric per device, fits a least-squares slope,
and projects it ``horizon_s`` seconds ahead. If the projection crosses the warn
threshold with a real upward trend, it emits a :class:`ForecastWarning` *before*
the hard failure — the demo's "BGP instability likely in ~90 s" moment.
"""

from __future__ import annotations

from collections import deque

import numpy as np

from neuralink.config import ForecastCfg, get_settings
from neuralink.schemas import ForecastWarning, NetworkEvent


class TrendForecaster:
    def __init__(self, cfg: ForecastCfg | None = None) -> None:
        self.cfg = cfg or get_settings().detection.forecast
        self._hist: dict[tuple[str, str], deque[tuple[float, float]]] = {}
        self._warned: set[tuple[str, str]] = set()

    def _slope(self, samples: deque[tuple[float, float]]) -> tuple[float, float]:
        t = np.array([s[0] for s in samples], dtype=float)
        y = np.array([s[1] for s in samples], dtype=float)
        # Guard against a degenerate (zero-variance) time axis.
        if np.ptp(t) < 1e-9:
            return 0.0, float(y[-1])
        slope, intercept = np.polyfit(t, y, 1)
        return float(slope), float(intercept)

    def observe(self, event: NetworkEvent, metric: str | None = None) -> ForecastWarning | None:
        """Feed an event; return an early-warning if a dangerous trend projects."""
        if metric is not None:
            return self._observe_one(event, metric)

        for m in ("cpu_pct", "temp_c", "if_errors"):
            warning = self._observe_one(event, m)
            if warning is not None:
                return warning
        return None

    def _observe_one(self, event: NetworkEvent, metric: str) -> ForecastWarning | None:
        device = event.source_device
        # Extract metrics value, handling nested attributes
        val_attr = getattr(event.metrics, metric, None)
        if val_attr is None:
            # Fallback for if_errors if it's not a direct field
            if metric == "if_errors":
                value = float(event.metrics.if_in_errors + event.metrics.if_out_errors)
            else:
                return None
        else:
            value = float(val_attr)

        key = (device, metric)
        dq = self._hist.setdefault(key, deque(maxlen=self.cfg.window))
        dq.append((event.sim_time, value))

        # Get metric-specific config
        threshold = self.cfg.cpu_warn_pct
        min_slope = self.cfg.min_slope
        if metric == "temp_c":
            threshold = getattr(self.cfg, "temp_warn_c", 75.0)
            min_slope = getattr(self.cfg, "temp_min_slope", 0.1)
        elif metric == "if_errors":
            threshold = getattr(self.cfg, "errors_warn", 100.0)
            min_slope = getattr(self.cfg, "errors_min_slope", 1.0)

        # Allow re-arming once the metric recovers well below the warn line.
        if value < threshold * 0.6:
            self._warned.discard(key)

        if len(dq) < self.cfg.window or key in self._warned:
            return None

        slope, _ = self._slope(dq)
        projected = value + slope * self.cfg.horizon_s
        if slope < min_slope or projected < threshold:
            return None

        self._warned.add(key)
        eta = max(0.0, (threshold - value) / slope) if slope > 0 else 0.0


        max_val = 100.0 if metric in ("cpu_pct", "mem_pct") else float("inf")
        proj_disp = min(projected, max_val)

        proj_str = f"{proj_disp:.0f}%" if metric == "cpu_pct" else (f"{proj_disp:.0f}°C" if metric == "temp_c" else f"{proj_disp:.0f} errors")
        val_str = f"{value:.0f}%" if metric == "cpu_pct" else (f"{value:.0f}°C" if metric == "temp_c" else f"{value:.0f} errors")

        return ForecastWarning(
            device=device,
            metric=metric,
            current_value=round(value, 1),
            projected_value=round(proj_disp, 1),
            eta_seconds=round(eta, 0),
            sim_time=event.sim_time,
            message=(
                f"{device} {metric} trending to exhaustion: "
                f"{val_str} now, projected {proj_str} in "
                f"{self.cfg.horizon_s:.0f}s. Instability likely in ~{eta:.0f}s."
            ),
        )
