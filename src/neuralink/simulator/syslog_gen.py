"""Render realistic Cisco/Junos-ish syslog lines for simulated events.

Normal telemetry emits low-severity housekeeping lines; faults supply their own
mnemonic message via :class:`~neuralink.simulator.fault_injector.FaultEffect`.
The parser (ingestion) is built to read these back into fields, so keep the
format stable.
"""

from __future__ import annotations

from datetime import UTC, datetime

from neuralink.schemas import Metrics, SeverityRaw

# Cisco syslog severity -> PRI-ish facility level (local7). Used only for realism.
_SEV_LEVEL = {SeverityRaw.INFO: 6, SeverityRaw.WARNING: 4, SeverityRaw.CRITICAL: 2}


def _stamp(sim_time: float) -> str:
    # Wall-clock-ish stamp derived from a fixed epoch + sim_time keeps demos
    # deterministic while looking like real syslog timestamps.
    base = datetime(2026, 1, 1, tzinfo=UTC)
    ts = base.timestamp() + sim_time
    return datetime.fromtimestamp(ts, tz=UTC).strftime("%b %d %H:%M:%S")


def normal_line(device: str, metrics: Metrics) -> str:
    """A benign periodic housekeeping line for healthy devices."""
    return (
        f"%SYS-6-INFO: housekeeping ok cpu={metrics.cpu_pct:.0f}% "
        f"mem={metrics.mem_pct:.0f}% temp={metrics.temp_c:.0f}C "
        f"bgp={metrics.bgp_peers_up}/{metrics.bgp_peers_total}"
    )


def render(
    device: str,
    sim_time: float,
    severity: SeverityRaw,
    mnemonic_msg: str,
    seq: int,
) -> str:
    """Wrap a mnemonic message in a host/timestamp/sequence envelope.

    Example::

        <188>42: PE-Router-03: Jan 01 00:03:00: %BGP-5-ADJCHANGE: neighbor ...
    """
    pri = 8 * 23 + _SEV_LEVEL.get(severity, 6)  # facility local7(23)*8 + level
    return f"<{pri}>{seq}: {device}: {_stamp(sim_time)}: {mnemonic_msg}"
