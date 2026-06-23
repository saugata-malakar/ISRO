"""Generate the synthetic ISRO-style RAG corpus (README §8 rag).

Writes ~16 runbooks (.md) + ~8 past incidents (.json). Synthetic and clearly
labelled (README §10: never claim real ISRO data). Deterministic; safe to re-run.
"""

from __future__ import annotations

import json

from neuralink.config import get_settings

# (filename, title, body) — keyword-rich so offline retrieval is reliable.
RUNBOOKS: list[tuple[str, str, str]] = [
    (
        "bgp_session_recovery.md",
        "Runbook: BGP Session Down — Recovery",
        """## Symptom
BGP neighbor reported Down via %BGP-5-ADJCHANGE; one or more peers missing from
`show ip bgp summary`. Often follows CPU starvation on the control plane.

## Likely causes
- Control-plane CPU exhaustion (IP-Routing process starved) — hold timer expires.
- Interface/link flap breaking the TCP session (port 179).
- MTU / misconfig after a change.

## Diagnosis
1. `show ip bgp summary` — confirm which neighbor is down and the state.
2. `show processes cpu sorted` — check if IP-Routing is starving the CPU.
3. `show logging | include BGP` — correlate the adjacency change timeline.

## Remediation (least invasive first)
1. `show ip bgp summary` — verify peer state (risk: low).
2. `show processes cpu sorted` — identify the offending process (risk: low).
3. `clear ip bgp <peer> soft` — soft reconfig, no full session reset (risk: low, RECOMMENDED).
4. If soft clear fails: `clear ip bgp <peer>` — hard reset, brief outage (risk: medium).

## Escalation
If the peer does not re-establish within 2 minutes after a soft clear, escalate to
the routing on-call and open a SEV-2.
""",
    ),
    (
        "cpu_starvation.md",
        "Runbook: CPU Starvation on Router",
        """## Symptom
Sustained high CPU (%SYS-2-CPUHOG), control-plane protocols (BGP/OSPF) at risk.
CPU trending upward toward 100% over minutes.

## Likely causes
- Process loop / punted traffic to CPU (ACL log, ICMP redirects).
- Routing churn causing recomputation.
- Insufficient hardware for current load.

## Diagnosis
1. `show processes cpu sorted` — top CPU consumers.
2. `show processes cpu history` — confirm the ramp trend.
3. `show ip traffic` — look for punted/exception traffic.

## Remediation
1. `show processes cpu sorted` — identify the process (risk: low, RECOMMENDED).
2. Rate-limit or disable the offending feature (e.g. `no ip redirects`) (risk: medium).
3. Apply CoPP / control-plane policing to protect routing (risk: medium).

## Prevention
Deploy control-plane policing (CoPP) and monitor CPU trend with early-warning
thresholds so action is taken before BGP drops.
""",
    ),
    (
        "interface_flap.md",
        "Runbook: Interface Flapping",
        """## Symptom
Repeated %LINK-3-UPDOWN up/down with rising input/CRC errors on an interface.

## Likely causes
- Failing optic/SFP or dirty fiber connector.
- Duplex/speed mismatch.
- Marginal cable.

## Diagnosis
1. `show interface <if>` — check error counters, resets, last flap.
2. `show interface <if> transceiver` — optical power levels.

## Remediation
1. `show interface <if>` — confirm error rate (risk: low, RECOMMENDED).
2. `shutdown` then `no shutdown` to reset (risk: medium).
3. Replace SFP/clean fiber; if persistent, schedule hardware RMA.
""",
    ),
    (
        "fiber_cut.md",
        "Runbook: Fiber Cut / Link Down",
        """## Symptom
Hard %LINK-3-UPDOWN to down with zero throughput; LSPs on the path go down.

## Likely causes
- Physical fiber cut or transceiver failure.
- Upstream provider outage.

## Diagnosis
1. `show interface <if>` — confirm physical layer down (not admin-down).
2. `show mpls lsp` — list LSPs traversing the failed link.
3. Verify FRR / backup path availability.

## Remediation
1. Confirm protect/backup LSP took over (`show mpls lsp`) (risk: low, RECOMMENDED).
2. If no FRR, manually reroute traffic to the redundant path (risk: medium).
3. Dispatch field team for the physical repair; track via incident.
""",
    ),
    (
        "hardware_fault.md",
        "Runbook: Hardware / Thermal Fault & RMA",
        """## Symptom
Rising temperature (%ENVMON-2-TEMP), interface errors, possible thermal shutdown
(%PLATFORM-0-HALT) leaving the device unreachable.

## Likely causes
- Fan failure / blocked airflow.
- Failing line card or power module.

## Diagnosis
1. `show environment all` — temperatures, fans, power.
2. `show diag` / `show inventory` — identify the faulty FRU for RMA.

## Remediation
1. `show environment all` — confirm the thermal source (risk: low, RECOMMENDED).
2. Shift traffic off the affected device (drain) before it halts (risk: medium).
3. Raise an RMA for the faulty FRU; replace during maintenance window.
""",
    ),
    (
        "traffic_blackhole.md",
        "Runbook: Silent Traffic Blackhole",
        """## Symptom
Counters look healthy (CPU/mem/link nominal) but throughput collapses — a silent
forwarding blackhole. %TRAFFIC-4-DROP may appear.

## Likely causes
- FIB/RIB inconsistency after a routing change.
- Broken MPLS label binding (LFIB) on a transit node.
- ACL/null-route inadvertently dropping traffic.

## Diagnosis
1. `show ip cef <prefix>` — verify forwarding entry resolves.
2. `show mpls forwarding-table` — confirm label bindings.
3. `traceroute` from CE to detect where packets vanish.

## Remediation
1. `show ip cef <prefix>` — confirm FIB correctness (risk: low, RECOMMENDED).
2. `clear ip route *` to rebuild RIB/FIB (risk: medium, brief reconvergence).
3. Correct any erroneous ACL/null-route.
""",
    ),
    (
        "bgp_flap.md",
        "Runbook: BGP Adjacency Flapping",
        """## Symptom
Repeated BGP neighbor up/down (%BGP-5-ADJCHANGE) destabilising the routing table.

## Likely causes
- Underlying link flap.
- Hold-timer mismatch or path MTU issues.
- CPU pressure delaying keepalives.

## Remediation
1. `show ip bgp neighbors <peer>` — inspect timers and flap counts (risk: low, RECOMMENDED).
2. Stabilise the underlying interface first (see interface_flap runbook).
3. Consider BGP dampening for the unstable prefix (risk: medium).
""",
    ),
    (
        "mem_pressure.md",
        "Runbook: Memory Pressure",
        """## Symptom
High memory utilisation, %SYS malloc failures, risk of process restarts.

## Remediation
1. `show memory statistics` — identify the consumer (risk: low, RECOMMENDED).
2. Clear stale sessions/caches where safe (risk: medium).
3. Schedule a maintenance reload if a leak is confirmed.
""",
    ),
    (
        "lsp_reroute.md",
        "Runbook: MPLS LSP Reroute",
        """## Symptom
An LSP is down or degraded; services bound to it are impacted.

## Remediation
1. `show mpls lsp name <id>` — confirm state and path (risk: low, RECOMMENDED).
2. Trigger FRR / explicit reroute to the backup path (risk: medium).
3. Validate service restoration end-to-end.
""",
    ),
    (
        "ground_station_link.md",
        "Runbook: Ground Station Link Protection",
        """## Context
Ground-Station-Link services are criticality 1.0 — protect them first. They ride
LSP-12 across PE-Router-01 -> P-Router-02 -> PE-Router-03.

## Priority actions
1. On any PE-Router-03 or LSP-12 fault, verify Ground-Station-Link-B first.
2. Confirm backup LSP availability before any disruptive remediation.
3. Notify the mission operations desk if degradation ETA < 60s.
""",
    ),
    (
        "copp_hardening.md",
        "Runbook: Control-Plane Policing (CoPP)",
        """## Purpose
Protect the routing control plane from CPU starvation by policing punted traffic.

## Steps
1. Classify control traffic (BGP/OSPF/SSH).
2. Apply policers to limit exception/punted traffic.
3. Monitor `show policy-map control-plane`.
""",
    ),
    (
        "syslog_triage.md",
        "Runbook: Syslog Triage Quick Reference",
        """## Mnemonic -> meaning
- %BGP-5-ADJCHANGE: BGP neighbor state change (Up/Down).
- %SYS-2-CPUHOG: process holding CPU too long.
- %LINK-3-UPDOWN: interface line state change.
- %ENVMON-2-TEMP: environmental temperature alarm.
- %PLATFORM-0-HALT: platform halt (thermal/critical).
- %TRAFFIC-4-DROP: forwarding-plane drop anomaly.
""",
    ),
    (
        "escalation_policy.md",
        "Runbook: Incident Escalation Policy",
        """## Severity mapping
- CRITICAL (score >= 85) or any criticality-1.0 service at risk => SEV-1, page on-call.
- WARNING (score >= 60) => SEV-2, notify NOC.

## Confirm-before-execute
Operators must confirm any remediation CLI before it runs. Nothing auto-executes.
""",
    ),
    (
        "confirm_before_execute.md",
        "Runbook: Safe Remediation Practice",
        """## Principle
Always run read-only verification commands (show ...) before any state-changing
command (clear/shutdown/reload). Prefer soft over hard operations. Capture an
audit entry for every executed step.
""",
    ),
    (
        "mpls_overview.md",
        "Runbook: MPLS / LSP / Service Model",
        """## Model
Services map to LSPs; LSPs traverse a path of PE/P routers. A node failure breaks
every LSP whose path includes it, and every service bound to those LSPs. Compute
blast radius from service criticality + count + node criticality.
""",
    ),
    (
        "backup_path_validation.md",
        "Runbook: Backup Path Validation",
        """## Steps
1. Identify primary and backup LSP for the affected service.
2. `show mpls lsp` — confirm backup is up before disrupting primary.
3. Only then perform disruptive remediation on the primary.
""",
    ),
]

INCIDENTS: list[dict] = [
    {
        "id": "INC-2025-0143",
        "title": "PE-Router-03 BGP down after CPU starvation",
        "event_type": "BGP_SESSION_DOWN",
        "device": "PE-Router-03",
        "summary": "IP-Routing process starved the CPU (ramped to 99%); BGP neighbor 10.0.0.2 dropped on hold-timer expiry.",
        "root_cause": "Punted traffic loop drove control-plane CPU to exhaustion, delaying BGP keepalives.",
        "resolution": "clear ip bgp 10.0.0.2 soft restored the session; CoPP deployed to prevent recurrence.",
        "impact_services": ["Ground-Station-Link-B", "VoIP-Trunk-A"],
        "duration_min": 6,
    },
    {
        "id": "INC-2025-0099",
        "title": "Fiber cut on P-Router-02 uplink",
        "event_type": "LINK_DOWN",
        "device": "P-Router-02",
        "summary": "Physical fiber cut took LSP-12 down; no FRR configured on the segment.",
        "root_cause": "Construction work severed the dark fiber.",
        "resolution": "Manual reroute to redundant path; physical repair next day.",
        "impact_services": ["Ground-Station-Link-B"],
        "duration_min": 240,
    },
    {
        "id": "INC-2025-0210",
        "title": "Interface flap on PE-Router-01",
        "event_type": "INTERFACE_FLAP",
        "device": "PE-Router-01",
        "summary": "Failing SFP caused repeated up/down with rising CRC errors.",
        "root_cause": "Degraded optic.",
        "resolution": "Replaced SFP during maintenance window.",
        "impact_services": ["VoIP-Trunk-A"],
        "duration_min": 35,
    },
    {
        "id": "INC-2025-0301",
        "title": "Thermal shutdown of CORE-SW-1",
        "event_type": "HARDWARE_FAULT",
        "device": "CORE-SW-1",
        "summary": "Fan failure led to thermal runaway and platform halt.",
        "root_cause": "Failed fan tray.",
        "resolution": "Drained traffic, RMA'd fan tray.",
        "impact_services": [],
        "duration_min": 50,
    },
    {
        "id": "INC-2025-0322",
        "title": "Silent blackhole on PE-Router-03",
        "event_type": "TRAFFIC_BLACKHOLE",
        "device": "PE-Router-03",
        "summary": "Healthy counters but Telemetry-Feed-C throughput dropped to near zero.",
        "root_cause": "Stale LFIB label binding after a routing change.",
        "resolution": "clear ip route * rebuilt FIB; throughput restored.",
        "impact_services": ["Telemetry-Feed-C"],
        "duration_min": 18,
    },
    {
        "id": "INC-2024-0875",
        "title": "BGP flap due to link instability",
        "event_type": "BGP_SESSION_DOWN",
        "device": "PE-Router-03",
        "summary": "Marginal link caused BGP adjacency to flap repeatedly.",
        "root_cause": "Marginal cable on the uplink.",
        "resolution": "Stabilised interface; applied dampening.",
        "impact_services": ["VoIP-Trunk-A"],
        "duration_min": 22,
    },
    {
        "id": "INC-2024-0540",
        "title": "Memory pressure on PE-Router-01",
        "event_type": "MEM_PRESSURE",
        "device": "PE-Router-01",
        "summary": "Memory leak in a process led to malloc failures.",
        "root_cause": "Software defect (memory leak).",
        "resolution": "Reload during maintenance; upgraded image.",
        "impact_services": [],
        "duration_min": 30,
    },
    {
        "id": "INC-2024-0612",
        "title": "Ground station degradation averted by early warning",
        "event_type": "CPU_SPIKE",
        "device": "PE-Router-03",
        "summary": "CPU trend forecast warned ~90s before BGP would have dropped; operator applied CoPP proactively.",
        "root_cause": "Rising punted traffic.",
        "resolution": "Pre-emptive CoPP; no service impact.",
        "impact_services": [],
        "duration_min": 0,
    },
]


def main(force: bool = False) -> int:
    s = get_settings()
    rb_dir = s.runbooks_dir
    inc_dir = s.incidents_dir
    rb_dir.mkdir(parents=True, exist_ok=True)
    inc_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    for fname, title, body in RUNBOOKS:
        path = rb_dir / fname
        if path.exists() and not force:
            continue
        path.write_text(f"# {title}\n\n*Synthetic ISRO-style runbook — prototype data, not real.*\n\n{body}",
                        encoding="utf-8")
        written += 1

    for inc in INCIDENTS:
        path = inc_dir / f"{inc['id']}.json"
        if path.exists() and not force:
            continue
        path.write_text(json.dumps(inc, indent=2), encoding="utf-8")
        written += 1

    print(f"[seed] runbooks: {len(RUNBOOKS)} in {rb_dir}")
    print(f"[seed] incidents: {len(INCIDENTS)} in {inc_dir}")
    print(f"[seed] wrote {written} new files (force={force}).")
    return 0


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    raise SystemExit(main(force=ap.parse_args().force))
