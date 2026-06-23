"""Simulator behaviour + determinism (README §3 M0 DoD, §1.7)."""

from __future__ import annotations

from neuralink.schemas import EventType
from neuralink.simulator import Simulator, get_scenario
from neuralink.simulator.topology_loader import load_topology


def test_topology_loads():
    topo = load_topology()
    assert {n.id for n in topo.nodes} >= {"PE-Router-01", "PE-Router-03", "CORE-SW-1"}
    assert topo.lsp("LSP-12") is not None


def test_deterministic_same_seed():
    a = list(Simulator(scenario=get_scenario("cpu_starvation"), seed=42).iter_events(20))
    b = list(Simulator(scenario=get_scenario("cpu_starvation"), seed=42).iter_events(20))
    assert [(e.source_device, e.sim_time, e.metrics.cpu_pct) for e in a] == \
           [(e.source_device, e.sim_time, e.metrics.cpu_pct) for e in b]


def test_healthy_run_is_stable():
    events = list(Simulator(scenario=None, seed=42).iter_events(50))
    cpus = [e.metrics.cpu_pct for e in events]
    assert max(cpus) < 40  # healthy CPU stays well below alarm levels
    assert all(e.event_type is EventType.NORMAL for e in events)


def test_cpu_starvation_produces_bgp_down():
    events = list(Simulator(scenario=get_scenario("cpu_starvation"), seed=42).iter_events(30))
    assert any(e.event_type is EventType.BGP_SESSION_DOWN for e in events)
    # CPU visibly ramps on the target before the failure.
    pe3 = [e.metrics.cpu_pct for e in events if e.source_device == "PE-Router-03"]
    assert max(pe3) >= 95
