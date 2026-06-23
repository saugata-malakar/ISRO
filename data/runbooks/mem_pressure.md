# Runbook: Memory Pressure

*Synthetic ISRO-style runbook — prototype data, not real.*

## Symptom
High memory utilisation, %SYS malloc failures, risk of process restarts.

## Remediation
1. `show memory statistics` — identify the consumer (risk: low, RECOMMENDED).
2. Clear stale sessions/caches where safe (risk: medium).
3. Schedule a maintenance reload if a leak is confirmed.
