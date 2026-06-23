"""IsolationForest baseline (README §8 detection).

Trains on *normal-only* telemetry and maps the model's raw anomaly score to an
operator-friendly 0-100 scale via a two-anchor linear calibration learned from
the normal distribution (so normal events land low and faults land high). The
calibration anchors are *learned parameters* stored in the artifact, not magic
numbers in logic.
"""

from __future__ import annotations

import pickle
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

from neuralink.config import DetectionCfg, get_settings
from neuralink.schemas import NetworkEvent
from neuralink.util import clamp

FEATURE_NAMES = [
    "cpu_pct",
    "mem_pct",
    "temp_c",
    "if_errors",
    "bgp_down",
    "link_down",
    "throughput_deficit",
]
_HEALTHY_THROUGHPUT = 450.0


def features(event: NetworkEvent) -> list[float]:
    m = event.metrics
    return [
        m.cpu_pct,
        m.mem_pct,
        m.temp_c,
        float(m.if_in_errors + m.if_out_errors),
        float(max(0, m.bgp_peers_total - m.bgp_peers_up)),
        0.0 if m.link_up else 1.0,
        max(0.0, _HEALTHY_THROUGHPUT - m.throughput_mbps),
    ]


def features_matrix(events: list[NetworkEvent]) -> np.ndarray:
    return np.asarray([features(e) for e in events], dtype=float)


def _feature_severity(value: float, warn: float, crit: float) -> float:
    """Map one feature value to 0..100 via operational thresholds.

    < warn        -> 0
    warn..crit    -> 60..85   (WARNING band)
    >= crit       -> 85..100  (CRITICAL band, ramps over one more (crit-warn) span)
    """
    if value < warn:
        return 0.0
    span = max(crit - warn, 1e-9)
    if value < crit:
        return 60.0 + 25.0 * (value - warn) / span
    return min(100.0, 85.0 + 15.0 * (value - crit) / span)


@dataclass
class AnomalyModel:
    """Bundled IsolationForest + scaler + learned/operational score calibration.

    The operator score (0-100) is::

        max( per-feature operational severity , if_blend_weight * IF score )

    The IF term (calibrated IsolationForest) surfaces subtle multivariate
    anomalies but is bounded so its score-saturation tail cannot fabricate a false
    CRITICAL. The per-feature severity gives an interpretable, monotonic gradient
    that drives clean WARNING/CRITICAL thresholds.
    """

    model: IsolationForest
    scaler: StandardScaler
    raw_lo: float
    raw_hi: float
    score_lo: float
    score_hi: float
    feature_severity: dict[str, list[float]]
    if_blend_weight: float = 0.6

    def _if_score(self, X: np.ndarray) -> np.ndarray:
        raw = -self.model.score_samples(self.scaler.transform(X))  # higher => more anomalous
        frac = (raw - self.raw_lo) / max(self.raw_hi - self.raw_lo, 1e-9)
        return np.clip(self.score_lo + frac * (self.score_hi - self.score_lo), 0.0, 100.0)

    def _severity(self, X: np.ndarray) -> np.ndarray:
        sev = np.zeros(X.shape[0], dtype=float)
        for name, (warn, crit) in self.feature_severity.items():
            if name not in FEATURE_NAMES:
                continue
            col = X[:, FEATURE_NAMES.index(name)]
            fs = np.array([_feature_severity(float(v), warn, crit) for v in col])
            sev = np.maximum(sev, fs)
        return sev

    def score_matrix(self, X: np.ndarray) -> np.ndarray:
        blended = np.maximum(self._severity(X), self.if_blend_weight * self._if_score(X))
        return np.clip(blended, 0.0, 100.0)

    def score_event(self, event: NetworkEvent) -> float:
        return float(self.score_matrix(features_matrix([event]))[0])


def train(events: list[NetworkEvent], cfg: DetectionCfg | None = None) -> AnomalyModel:
    """Fit the model on normal-only events and learn the score calibration."""
    cfg = cfg or get_settings().detection
    if not events:
        raise ValueError("Cannot train baseline on an empty event set.")
    X = features_matrix(events)
    scaler = StandardScaler().fit(X)
    # Override scales for discrete safety-critical indicators (see config docs):
    # any nonzero value is a major fault, so use a small operational spread.
    for name, scale in cfg.indicator_scales.items():
        if name in FEATURE_NAMES:
            scaler.scale_[FEATURE_NAMES.index(name)] = float(scale)
    model = IsolationForest(
        n_estimators=cfg.n_estimators,
        contamination=cfg.contamination,
        random_state=get_settings().seed,
    ).fit(scaler.transform(X))

    Z = scaler.transform(X)
    raw = -model.score_samples(Z)
    c = cfg.calibration
    raw_lo = float(np.percentile(raw, c.low_pct))
    raw_hi = float(np.percentile(raw, c.high_pct))

    return AnomalyModel(
        model=model,
        scaler=scaler,
        raw_lo=raw_lo,
        raw_hi=raw_hi,
        score_lo=c.low_score,
        score_hi=c.high_score,
        feature_severity={k: list(v) for k, v in cfg.feature_severity.items()},
        if_blend_weight=c.if_blend_weight,
    )


def default_artifact_path() -> Path:
    return get_settings().runtime_dir / "baseline.pkl"


def save(model: AnomalyModel, path: str | Path | None = None) -> Path:
    p = Path(path) if path else default_artifact_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("wb") as fh:
        pickle.dump(model, fh)
    return p


def load(path: str | Path | None = None) -> AnomalyModel:
    p = Path(path) if path else default_artifact_path()
    if not p.exists():
        raise FileNotFoundError(
            f"Anomaly baseline not found at {p}. Run `make train` (scripts/train_baseline.py) "
            "to produce it — the air-gapped build never trains implicitly at runtime."
        )
    with p.open("rb") as fh:
        return pickle.load(fh)


def clamp_score(score: float) -> float:
    return clamp(score, 0.0, 100.0)
