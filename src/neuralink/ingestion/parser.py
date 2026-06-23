"""Syslog line -> structured fields (README §8 ingestion).

Hand-written regex (the spec allows pygrok *or* regex; regex keeps the air-gapped
dependency surface minimal). Parses the simulator's Cisco/Junos-ish lines, and is
robust to real-world-ish lines too.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from neuralink.schemas import EventType, SeverityRaw

# <PRI>SEQ: HOST: Mon DD HH:MM:SS: %FAC-LVL-MNEMONIC: message
_LINE_RE = re.compile(
    r"^(?:<(?P<pri>\d+)>)?\s*(?:(?P<seq>\d+):\s+)?"
    r"(?P<host>[\w.\-]+):\s+"
    r"(?P<ts>[A-Z][a-z]{2}\s+\d+\s+\d{2}:\d{2}:\d{2}):\s+"
    r"(?P<body>.*)$"
)
_BODY_RE = re.compile(
    r"%(?P<fac>[A-Z]+)-(?P<lvl>\d)-(?P<mnem>[A-Z0-9_]+):\s*(?P<msg>.*)$"
)

# Cisco severity level (0-7) -> our coarse SeverityRaw.
_LEVEL_TO_SEV = {
    0: SeverityRaw.CRITICAL,
    1: SeverityRaw.CRITICAL,
    2: SeverityRaw.CRITICAL,
    3: SeverityRaw.CRITICAL,
    4: SeverityRaw.WARNING,
    5: SeverityRaw.WARNING,
    6: SeverityRaw.INFO,
    7: SeverityRaw.INFO,
}

_IPV4_RE = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")
_CPU_RE = re.compile(r"(\d{1,3})\s*%")


@dataclass
class ParsedSyslog:
    raw: str
    host: str = ""
    seq: int | None = None
    timestamp: str = ""
    facility: str = ""
    level: int | None = None
    mnemonic: str = ""
    message: str = ""
    severity: SeverityRaw = SeverityRaw.INFO
    event_type: EventType = EventType.NORMAL
    fields: dict = field(default_factory=dict)


def classify(mnemonic: str, message: str) -> EventType:
    """Map a syslog mnemonic/message to a NeuraLink event type."""
    m = mnemonic.upper()
    msg = message.lower()
    if "CPUHOG" in m or "CPU" in m:
        return EventType.CPU_SPIKE
    if "ADJCHANGE" in m or "BGP" in m:
        return EventType.BGP_SESSION_DOWN if "down" in msg else EventType.NORMAL
    if "UPDOWN" in m or "LINEPROTO" in m:
        return EventType.LINK_DOWN if "down" in msg else EventType.INTERFACE_FLAP
    if "MEM" in m or "MALLOC" in m:
        return EventType.MEM_PRESSURE
    if "ENVMON" in m or "TEMP" in m or "PLATFORM" in m or "HALT" in m:
        return EventType.HARDWARE_FAULT
    if "TRAFFIC" in m or "DROP" in m or "BLACKHOLE" in msg:
        return EventType.TRAFFIC_BLACKHOLE
    return EventType.NORMAL


def parse_syslog(line: str) -> ParsedSyslog:
    """Parse one syslog line into structured fields. Never raises on bad input."""
    out = ParsedSyslog(raw=line)
    m = _LINE_RE.match(line.strip())
    if not m:
        out.message = line.strip()
        return out
    out.host = m.group("host")
    if m.group("seq"):
        out.seq = int(m.group("seq"))
    out.timestamp = m.group("ts")
    body = m.group("body")

    bm = _BODY_RE.match(body)
    if bm:
        out.facility = bm.group("fac")
        out.level = int(bm.group("lvl"))
        out.mnemonic = bm.group("mnem")
        out.message = bm.group("msg")
        out.severity = _LEVEL_TO_SEV.get(out.level, SeverityRaw.INFO)
    else:
        out.message = body

    out.event_type = classify(out.mnemonic, out.message)

    # Extract a few useful numeric/identifier fields.
    ip = _IPV4_RE.search(out.message)
    if ip:
        out.fields["peer_ip"] = ip.group(1)
    cpu = _CPU_RE.search(out.message)
    if cpu:
        out.fields["cpu_pct"] = int(cpu.group(1))
    return out
