"""Anomaly scoring + forecast (README §3 M2 DoD)."""

from __future__ import annotations

from neuralink.detection import baseline
from neuralink.detection.anomaly import AnomalyDetector
from neuralink.detection.forecast import TrendForecaster
from neuralink.schemas import AlertSeverity, EventType
from neuralink.simulator import Simulator, get_scenario


def _trained_detector():
    normal = list(Simulator(scenario=None, seed=42).iter_events(120))
    model = baseline.train(normal)
    return AnomalyDetector(model=model)


def test_normal_scores_low():
    det = _trained_detector()
    holdout = list(Simulator(scenario=None, seed=999).iter_events(60))
    scores = [det.score(e) for e in holdout]
    assert max(scores) < det.cfg.warning_score  # no false alerts on normal traffic


def test_fault_scores_high_and_critical():
    det = _trained_detector()
    faults = [e for e in Simulator(scenario=get_scenario("cpu_starvation"), seed=42).iter_events(30)
              if "fault" in e.tags]
    alerts = [det.evaluate(e) for e in faults]
    assert any(a and a.severity is AlertSeverity.CRITICAL for a in alerts)


def test_forecast_warns_before_bgp_drop():
    fc = TrendForecaster()
    sim = Simulator(scenario=get_scenario("cpu_starvation"), seed=42)
    warn_t = None
    bgp_t = None
    for ev in sim.iter_events(30):
        if ev.source_device != "PE-Router-03":
            continue
        w = fc.observe(ev)
        if w and warn_t is None:
            warn_t = ev.sim_time
        if ev.event_type is EventType.BGP_SESSION_DOWN and bgp_t is None:
            bgp_t = ev.sim_time
    assert warn_t is not None, "forecast never fired"
    assert bgp_t is not None
    assert warn_t < bgp_t  # warned BEFORE the hard failure


def test_forecast_warns_on_temp_fault():
    fc = TrendForecaster()
    sim = Simulator(scenario=get_scenario("hardware_fault"), seed=42)
    warn_t = None
    for ev in sim.iter_events(30):
        if ev.source_device != "CORE-SW-1":
            continue
        w = fc.observe(ev)
        if w and w.metric == "temp_c":
            warn_t = ev.sim_time
            break
    assert warn_t is not None, "temp_c forecast warning never fired"
