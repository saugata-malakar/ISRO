# Runbook: Incident Escalation Policy

*Synthetic ISRO-style runbook — prototype data, not real.*

## Severity mapping
- CRITICAL (score >= 85) or any criticality-1.0 service at risk => SEV-1, page on-call.
- WARNING (score >= 60) => SEV-2, notify NOC.

## Confirm-before-execute
Operators must confirm any remediation CLI before it runs. Nothing auto-executes.
