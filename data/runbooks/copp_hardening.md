# Runbook: Control-Plane Policing (CoPP)

*Synthetic ISRO-style runbook — prototype data, not real.*

## Purpose
Protect the routing control plane from CPU starvation by policing punted traffic.

## Steps
1. Classify control traffic (BGP/OSPF/SSH).
2. Apply policers to limit exception/punted traffic.
3. Monitor `show policy-map control-plane`.
