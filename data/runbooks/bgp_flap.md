# Runbook: BGP Adjacency Flapping

*Synthetic ISRO-style runbook — prototype data, not real.*

## Symptom
Repeated BGP neighbor up/down (%BGP-5-ADJCHANGE) destabilising the routing table.

## Likely causes
- Underlying link flap.
- Hold-timer mismatch or path MTU issues.
- CPU pressure delaying keepalives.

## Remediation
1. `show ip bgp neighbors <peer>` — inspect timers and flap counts (risk: low, RECOMMENDED).
2. Stabilise the underlying interface first (see interface_flap runbook).
3. Consider BGP dampening for the unstable prefix (risk: medium).
