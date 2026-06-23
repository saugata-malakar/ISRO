# Runbook: Backup Path Validation

*Synthetic ISRO-style runbook — prototype data, not real.*

## Steps
1. Identify primary and backup LSP for the affected service.
2. `show mpls lsp` — confirm backup is up before disrupting primary.
3. Only then perform disruptive remediation on the primary.
