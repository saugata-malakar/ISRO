"""Simulator package — stands in for the real ISRO MPLS network (README §2).

The :class:`Simulator` ties together the topology, per-device telemetry, scripted
fault scenarios, and syslog rendering into a deterministic stream of
:class:`~neuralink.schemas.NetworkEvent` objects.
"""

from __future__ import annotations

from collections.abc import Iterator

from neuralink.config import Settings, get_settings
from neuralink.schemas import EventType, NetworkEvent, SeverityRaw, Topology
from neuralink.simulator.fault_injector import FaultEffect, Scenario, get_scenario
from neuralink.simulator.syslog_gen import normal_line, render
from neuralink.simulator.telemetry_gen import apply_effect, healthy_sample
from neuralink.simulator.topology_loader import load_topology
from neuralink.util import seeded_rng

__all__ = [
    "Simulator",
    "load_topology",
    "get_scenario",
    "Scenario",
    "FaultEffect",
]


class Simulator:
    """Deterministic telemetry + syslog generator.

    Parameters
    ----------
    topology:
        The network to simulate. If ``None`` it is loaded from config.
    settings:
        App settings; defaults to :func:`get_settings`.
    scenario:
        Optional active fault scenario. ``start_tick`` controls when (in ticks)
        the fault begins, allowing a healthy warm-up so the forecaster has a
        baseline. ``None`` => a fully healthy network (manual-injection idle).
    """

    def __init__(
        self,
        topology: Topology | None = None,
        settings: Settings | None = None,
        scenario: Scenario | None = None,
        start_tick: int = 3,
        seed: int | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.topology = topology or load_topology()
        self.scenario = scenario
        self.start_tick = start_tick
        self.seed = self.settings.seed if seed is None else seed
        self._seq = 0
        self.sim_cfg = self.settings.simulator

    # ------------------------------------------------------------------ #
    def inject(self, scenario_name: str, start_tick: int = 0) -> None:
        """Manually arm a fault scenario (used by `make run-sim` and the TUI)."""
        self.scenario = get_scenario(scenario_name)
        self.start_tick = start_tick

    # ------------------------------------------------------------------ #
    def _classify(self, effect: FaultEffect | None) -> tuple[EventType, SeverityRaw]:
        if effect and effect.event_type is not None:
            return effect.event_type, (effect.severity or SeverityRaw.WARNING)
        return EventType.NORMAL, SeverityRaw.INFO

    def _tick_effects(self, tick: int) -> dict[str, FaultEffect]:
        if not self.scenario or tick < self.start_tick:
            return {}
        sim_t = (tick - self.start_tick) * self.sim_cfg.time_compression
        if sim_t > self.scenario.duration_s:
            # Fault has run its course; keep emitting its terminal effect so the
            # outage persists (more realistic than snapping back to healthy).
            sim_t = self.scenario.duration_s
        return self.scenario.effects_at(sim_t)

    def _make_event(self, node, tick: int, effect: FaultEffect | None) -> NetworkEvent:
        rng = seeded_rng(self.seed, node.id, tick)
        metrics = healthy_sample(node, self.sim_cfg, rng)
        if effect:
            metrics = apply_effect(metrics, effect)
        etype, sev = self._classify(effect)
        sim_time = tick * self.sim_cfg.time_compression
        if effect and effect.syslog:
            msg = effect.syslog
        else:
            msg = normal_line(node.id, metrics)
        self._seq += 1
        raw = render(node.id, sim_time, sev, msg, self._seq)
        tags = ["sim"]
        if effect:
            tags.append("fault")
        return NetworkEvent(
            source_device=node.id,
            source_ip=node.ip,
            event_type=etype,
            severity_raw=sev,
            metrics=metrics,
            raw_message=raw,
            sim_time=sim_time,
            tags=tags,
        )

    # ------------------------------------------------------------------ #
    def iter_events(self, max_ticks: int) -> Iterator[NetworkEvent]:
        """Yield events tick-by-tick, one per device, in deterministic order."""
        for tick in range(max_ticks):
            effects = self._tick_effects(tick)
            for node in self.topology.nodes:
                yield self._make_event(node, tick, effects.get(node.id))

    def iter_ticks(self, max_ticks: int) -> Iterator[tuple[int, list[NetworkEvent]]]:
        """Yield ``(tick, [events for all devices])`` batches."""
        for tick in range(max_ticks):
            effects = self._tick_effects(tick)
            batch = [self._make_event(n, tick, effects.get(n.id)) for n in self.topology.nodes]
            yield tick, batch
