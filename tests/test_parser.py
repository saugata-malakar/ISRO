"""Syslog parser (README §8 ingestion)."""

from __future__ import annotations

from neuralink.ingestion.parser import parse_syslog
from neuralink.schemas import EventType, SeverityRaw


def test_bgp_down():
    p = parse_syslog(
        "<186>108: PE-Router-03: Jan 01 00:03:30: "
        "%BGP-5-ADJCHANGE: neighbor 10.0.0.2 Down hold time expired"
    )
    assert p.host == "PE-Router-03"
    assert p.event_type is EventType.BGP_SESSION_DOWN
    assert p.fields.get("peer_ip") == "10.0.0.2"
    assert p.seq == 108


def test_cpuhog():
    p = parse_syslog("<188>5: PE-Router-03: Jan 01 00:00:30: "
                     "%SYS-2-CPUHOG: high CPU utilization (92%/92%)")
    assert p.event_type is EventType.CPU_SPIKE
    assert p.severity is SeverityRaw.CRITICAL
    assert p.fields.get("cpu_pct") == 92


def test_link_down():
    p = parse_syslog("<187>9: P-Router-02: Jan 01 00:00:00: "
                     "%LINK-3-UPDOWN: Interface Gi0/1, changed state to down")
    assert p.event_type is EventType.LINK_DOWN


def test_normal_housekeeping():
    p = parse_syslog("<190>1: CE-Router-07: Jan 01 00:00:00: "
                     "%SYS-6-INFO: housekeeping ok cpu=20% mem=44%")
    assert p.event_type is EventType.NORMAL
    assert p.severity is SeverityRaw.INFO


def test_malformed_does_not_crash():
    p = parse_syslog("this is not a syslog line")
    assert p.event_type is EventType.NORMAL
    assert p.message == "this is not a syslog line"
