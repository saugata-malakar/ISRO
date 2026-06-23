# Runbook: Safe Remediation Practice

*Synthetic ISRO-style runbook — prototype data, not real.*

## Principle
Always run read-only verification commands (show ...) before any state-changing
command (clear/shutdown/reload). Prefer soft over hard operations. Capture an
audit entry for every executed step.
