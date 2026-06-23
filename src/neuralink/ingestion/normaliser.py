"""Normalise incoming telemetry into the canonical :class:`NetworkEvent`.

Two entry points keep the source swappable (README §8 ingestion):
  * :func:`normalise_event` — enrich an already-structured event from the
    simulator (confirms classification against the parsed raw syslog line).
  * :func:`from_raw` — build an event from a raw syslog line + a metrics snapshot
    (the shape a real SNMP/syslog collector would hand us).
"""

from __future__ import annotations

from neuralink.ingestion.parser import parse_syslog
from neuralink.schemas import EventType, Metrics, NetworkEvent, SeverityRaw


def normalise_event(event: NetworkEvent) -> NetworkEvent:
    """Confirm/enrich a structured event using its raw syslog line."""
    parsed = parse_syslog(event.raw_message)
    # Trust an explicit fault classification from the parser if the structured
    # event arrived as NORMAL (defensive against under-classification).
    if event.event_type == EventType.NORMAL and parsed.event_type != EventType.NORMAL:
        event.event_type = parsed.event_type
        event.severity_raw = parsed.severity
    if "parsed" not in event.tags:
        event.tags.append("parsed")
    return event


def from_raw(
    raw_line: str,
    metrics: Metrics,
    source_ip: str,
    source_device: str | None = None,
    sim_time: float = 0.0,
) -> NetworkEvent:
    """Build a :class:`NetworkEvent` from a raw syslog line + metrics snapshot."""
    parsed = parse_syslog(raw_line)
    device = source_device or parsed.host or "unknown"
    severity = parsed.severity if parsed.event_type != EventType.NORMAL else SeverityRaw.INFO
    return NetworkEvent(
        source_device=device,
        source_ip=source_ip,
        event_type=parsed.event_type,
        severity_raw=severity,
        metrics=metrics,
        raw_message=raw_line,
        sim_time=sim_time,
        tags=["parsed"],
    )
