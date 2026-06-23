# Runbook: Interface Flapping

*Synthetic ISRO-style runbook — prototype data, not real.*

## Symptom
Repeated %LINK-3-UPDOWN up/down with rising input/CRC errors on an interface.

## Likely causes
- Failing optic/SFP or dirty fiber connector.
- Duplex/speed mismatch.
- Marginal cable.

## Diagnosis
1. `show interface <if>` — check error counters, resets, last flap.
2. `show interface <if> transceiver` — optical power levels.

## Remediation
1. `show interface <if>` — confirm error rate (risk: low, RECOMMENDED).
2. `shutdown` then `no shutdown` to reset (risk: medium).
3. Replace SFP/clean fiber; if persistent, schedule hardware RMA.
