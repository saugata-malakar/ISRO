"""Scripted fault scenarios (README §7.3).

Each scenario is a *timed sequence* of telemetry/syslog mutations expressed as
per-device :class:`FaultEffect` overlays sampled at a simulated time ``t`` (in
simulated seconds since scenario start). Effects are deterministic given the
global seed, so ``run_demo.py --scenario X --seed 42`` reproduces identically.

The forecaster must be able to warn *before* a hard failure, so faults that lead
to an outage ramp a metric gradually before the discrete failure event fires.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from neuralink.schemas import EventType, SeverityRaw
from neuralink.util import clamp


@dataclass
class FaultEffect:
    """An overlay applied on top of a device's healthy telemetry at time ``t``.

    Any field left ``None`` means "leave the healthy sample untouched". A set
    field overrides the sampled value. ``event_type`` / ``severity`` / ``syslog``
    force how the event is classified and rendered.
    """

    cpu_pct: float | None = None
    mem_pct: float | None = None
    temp_c: float | None = None
    if_in_errors: int | None = None
    if_out_errors: int | None = None
    bgp_peers_up: int | None = None
    link_up: bool | None = None
    throughput_mbps: float | None = None
    event_type: EventType | None = None
    severity: SeverityRaw | None = None
    syslog: str | None = None


# A scenario maps simulated-time -> {device_id: FaultEffect}
EffectsFn = Callable[[float], dict[str, "FaultEffect"]]


@dataclass
class Scenario:
    name: str
    description: str
    duration_s: float
    effects_fn: EffectsFn
    targets: list[str] = field(default_factory=list)

    def effects_at(self, t: float) -> dict[str, FaultEffect]:
        if t < 0:
            return {}
        return self.effects_fn(t)


def _lerp(a: float, b: float, frac: float) -> float:
    return a + (b - a) * clamp(frac, 0.0, 1.0)


# --------------------------------------------------------------------------- #
# Scenario builders
# --------------------------------------------------------------------------- #
def _cpu_starvation(device: str = "PE-Router-03", ramp_s: float = 180.0) -> Scenario:
    """CPU ramps 60->99% over ~3 min, then BGP_SESSION_DOWN. The hero scenario."""

    def fn(t: float) -> dict[str, FaultEffect]:
        if t < ramp_s:
            cpu = _lerp(60.0, 99.0, t / ramp_s)
            sev = SeverityRaw.WARNING if cpu < 90 else SeverityRaw.CRITICAL
            return {
                device: FaultEffect(
                    cpu_pct=cpu,
                    mem_pct=_lerp(45.0, 78.0, t / ramp_s),
                    event_type=EventType.CPU_SPIKE,
                    severity=sev,
                    syslog=(
                        f"%SYS-2-CPUHOG: Task is running for high CPU utilization "
                        f"({cpu:.0f}%/{cpu:.0f}%), process IP-Routing"
                    ),
                )
            }
        # Hard failure: BGP peers drop because the control plane is starved
        # (2 of 4 lost => unambiguously CRITICAL, vs a single-peer flap = WARNING).
        return {
            device: FaultEffect(
                cpu_pct=99.0,
                mem_pct=80.0,
                bgp_peers_up=1,
                event_type=EventType.BGP_SESSION_DOWN,
                severity=SeverityRaw.CRITICAL,
                syslog=(
                    "%BGP-5-ADJCHANGE: neighbor 10.0.0.2 Down "
                    "BGP Notification sent - hold time expired (3 of 4 peers lost)"
                ),
            )
        }

    return Scenario(
        name="cpu_starvation",
        description="CPU exhaustion on PE-Router-03 starves the control plane; BGP session drops.",
        duration_s=ramp_s + 60.0,
        effects_fn=fn,
        targets=[device],
    )


def _fiber_cut(device: str = "P-Router-02") -> Scenario:
    """LINK_DOWN on a core edge; LSPs traversing it break immediately."""

    def fn(t: float) -> dict[str, FaultEffect]:
        return {
            device: FaultEffect(
                link_up=False,
                if_in_errors=500,
                if_out_errors=500,
                throughput_mbps=0.0,
                event_type=EventType.LINK_DOWN,
                severity=SeverityRaw.CRITICAL,
                syslog="%LINK-3-UPDOWN: Interface GigabitEthernet0/1, changed state to down",
            )
        }

    return Scenario(
        name="fiber_cut",
        description="Physical link down on P-Router-02 uplink; LSP-12 path severed.",
        duration_s=120.0,
        effects_fn=fn,
        targets=[device],
    )


def _interface_flap(device: str = "PE-Router-01", period_s: float = 20.0) -> Scenario:
    """Repeated up/down with rising interface error counters."""

    def fn(t: float) -> dict[str, FaultEffect]:
        down = int(t // period_s) % 2 == 1
        errs = int(50 * (t // period_s + 1))
        return {
            device: FaultEffect(
                link_up=not down,
                if_in_errors=errs,
                if_out_errors=errs,
                event_type=EventType.INTERFACE_FLAP,
                severity=SeverityRaw.WARNING,
                syslog=(
                    f"%LINK-3-UPDOWN: Interface GigabitEthernet0/2, changed state to "
                    f"{'down' if down else 'up'}"
                ),
            )
        }

    return Scenario(
        name="interface_flap",
        description="Flapping interface on PE-Router-01 with climbing CRC errors.",
        duration_s=120.0,
        effects_fn=fn,
        targets=[device],
    )


def _hardware_fault(device: str = "CORE-SW-1", ramp_s: float = 120.0) -> Scenario:
    """Temperature rises + interface errors -> device unreachable."""

    def fn(t: float) -> dict[str, FaultEffect]:
        temp = _lerp(40.0, 92.0, t / ramp_s)
        if t < ramp_s:
            return {
                device: FaultEffect(
                    temp_c=temp,
                    if_in_errors=int(_lerp(0, 800, t / ramp_s)),
                    event_type=EventType.HARDWARE_FAULT if temp > 70 else EventType.NORMAL,
                    severity=SeverityRaw.WARNING if temp > 70 else SeverityRaw.INFO,
                    syslog=f"%ENVMON-2-TEMP: Temperature sensor reads {temp:.0f}C (threshold 75C)",
                )
            }
        return {
            device: FaultEffect(
                temp_c=95.0,
                link_up=False,
                event_type=EventType.HARDWARE_FAULT,
                severity=SeverityRaw.CRITICAL,
                syslog="%PLATFORM-0-HALT: Thermal shutdown; module powered off",
            )
        }

    return Scenario(
        name="hardware_fault",
        description="Thermal runaway on CORE-SW-1 ending in thermal shutdown.",
        duration_s=ramp_s + 40.0,
        effects_fn=fn,
        targets=[device],
    )


def _traffic_blackhole(device: str = "PE-Router-03") -> Scenario:
    """Metrics nominal but throughput collapses — the silent failure."""

    def fn(t: float) -> dict[str, FaultEffect]:
        return {
            device: FaultEffect(
                throughput_mbps=2.0,  # near-zero while CPU/mem/link look healthy
                event_type=EventType.TRAFFIC_BLACKHOLE,
                severity=SeverityRaw.WARNING,
                syslog="%TRAFFIC-4-DROP: Forwarding plane drop-rate anomaly on Tunnel12 (silent)",
            )
        }

    return Scenario(
        name="traffic_blackhole",
        description="Silent forwarding blackhole on PE-Router-03: clean counters, no throughput.",
        duration_s=120.0,
        effects_fn=fn,
        targets=[device],
    )


def _bgp_flap(device: str = "PE-Router-03", period_s: float = 15.0) -> Scenario:
    """Repeated BGP peer up/down."""

    def fn(t: float) -> dict[str, FaultEffect]:
        down = int(t // period_s) % 2 == 1
        return {
            device: FaultEffect(
                bgp_peers_up=3 if down else 4,
                event_type=EventType.BGP_SESSION_DOWN if down else EventType.NORMAL,
                severity=SeverityRaw.CRITICAL if down else SeverityRaw.INFO,
                syslog=(
                    f"%BGP-5-ADJCHANGE: neighbor 10.0.0.2 {'Down' if down else 'Up'}"
                ),
            )
        }

    return Scenario(
        name="bgp_flap",
        description="Unstable BGP adjacency on PE-Router-03 flapping up/down.",
        duration_s=120.0,
        effects_fn=fn,
        targets=[device],
    )


# Registry — name -> builder. run_demo.py / CLI select by name.
SCENARIO_BUILDERS: dict[str, Callable[[], Scenario]] = {
    "cpu_starvation": _cpu_starvation,
    "fiber_cut": _fiber_cut,
    "interface_flap": _interface_flap,
    "hardware_fault": _hardware_fault,
    "traffic_blackhole": _traffic_blackhole,
    "bgp_flap": _bgp_flap,
}


def list_scenarios() -> list[str]:
    return list(SCENARIO_BUILDERS)


def get_scenario(name: str) -> Scenario:
    if name not in SCENARIO_BUILDERS:
        raise KeyError(
            f"Unknown scenario '{name}'. Available: {', '.join(SCENARIO_BUILDERS)}"
        )
    return SCENARIO_BUILDERS[name]()
