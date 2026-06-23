# Runbook: Silent Traffic Blackhole

*Synthetic ISRO-style runbook — prototype data, not real.*

## Symptom
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
