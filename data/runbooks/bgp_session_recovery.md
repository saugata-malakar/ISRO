# Runbook: BGP Session Down — Recovery

*Synthetic ISRO-style runbook — prototype data, not real.*

## Symptom
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
