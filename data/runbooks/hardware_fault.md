# Runbook: Hardware / Thermal Fault & RMA

*Synthetic ISRO-style runbook — prototype data, not real.*

## Symptom
Rising temperature (%ENVMON-2-TEMP), interface errors, possible thermal shutdown
(%PLATFORM-0-HALT) leaving the device unreachable.

## Likely causes
- Fan failure / blocked airflow.
- Failing line card or power module.

## Diagnosis
1. `show environment all` — temperatures, fans, power.
2. `show diag` / `show inventory` — identify the faulty FRU for RMA.

## Remediation
1. `show environment all` — confirm the thermal source (risk: low, RECOMMENDED).
2. Shift traffic off the affected device (drain) before it halts (risk: medium).
3. Raise an RMA for the faulty FRU; replace during maintenance window.
