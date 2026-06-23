"""Per-device metric streams with Gaussian noise around healthy baselines."""

from __future__ import annotations

import random

from neuralink.config import SimulatorCfg
from neuralink.schemas import Metrics, Node
from neuralink.simulator.fault_injector import FaultEffect
from neuralink.util import clamp

_HEALTHY_THROUGHPUT_MBPS = 450.0


def _noisy(base: float, jitter: float, rng: random.Random, lo: float = 0.0, hi: float = 1e9) -> float:
    return clamp(base + rng.gauss(0.0, base * jitter + 1e-9), lo, hi)


def healthy_sample(node: Node, cfg: SimulatorCfg, rng: random.Random) -> Metrics:
    """Sample a healthy operating point for a device with small Gaussian noise."""
    b = cfg.baselines
    is_pe = node.type.upper() == "PE"
    total = b.bgp_peers_total if is_pe else 0
    return Metrics(
        cpu_pct=round(_noisy(b.cpu_pct, cfg.jitter, rng, 0, 100), 2),
        mem_pct=round(_noisy(b.mem_pct, cfg.jitter, rng, 0, 100), 2),
        if_in_errors=0,
        if_out_errors=0,
        bgp_peers_up=total,
        bgp_peers_total=total,
        link_up=True,
        temp_c=round(_noisy(b.temp_c, cfg.jitter, rng, 0, 120), 2),
        throughput_mbps=round(_noisy(_HEALTHY_THROUGHPUT_MBPS, cfg.jitter, rng, 0), 2),
    )


def apply_effect(metrics: Metrics, effect: FaultEffect) -> Metrics:
    """Overlay a fault effect on top of a healthy sample (None => keep healthy)."""
    data = metrics.model_dump()
    for f in (
        "cpu_pct",
        "mem_pct",
        "temp_c",
        "if_in_errors",
        "if_out_errors",
        "bgp_peers_up",
        "link_up",
        "throughput_mbps",
    ):
        val = getattr(effect, f)
        if val is not None:
            data[f] = val
    return Metrics(**data)
