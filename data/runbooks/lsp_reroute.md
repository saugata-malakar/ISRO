# Runbook: MPLS LSP Reroute

*Synthetic ISRO-style runbook — prototype data, not real.*

## Symptom
An LSP is down or degraded; services bound to it are impacted.

## Remediation
1. `show mpls lsp name <id>` — confirm state and path (risk: low, RECOMMENDED).
2. Trigger FRR / explicit reroute to the backup path (risk: medium).
3. Validate service restoration end-to-end.
