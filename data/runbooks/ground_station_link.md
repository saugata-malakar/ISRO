# Runbook: Ground Station Link Protection

*Synthetic ISRO-style runbook — prototype data, not real.*

## Context
Ground-Station-Link services are criticality 1.0 — protect them first. They ride
LSP-12 across PE-Router-01 -> P-Router-02 -> PE-Router-03.

## Priority actions
1. On any PE-Router-03 or LSP-12 fault, verify Ground-Station-Link-B first.
2. Confirm backup LSP availability before any disruptive remediation.
3. Notify the mission operations desk if degradation ETA < 60s.
