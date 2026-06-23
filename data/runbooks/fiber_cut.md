# Runbook: Fiber Cut / Link Down

*Synthetic ISRO-style runbook — prototype data, not real.*

## Symptom
Hard %LINK-3-UPDOWN to down with zero throughput; LSPs on the path go down.

## Likely causes
- Physical fiber cut or transceiver failure.
- Upstream provider outage.

## Diagnosis
1. `show interface <if>` — confirm physical layer down (not admin-down).
2. `show mpls lsp` — list LSPs traversing the failed link.
3. Verify FRR / backup path availability.

## Remediation
1. Confirm protect/backup LSP took over (`show mpls lsp`) (risk: low, RECOMMENDED).
2. If no FRR, manually reroute traffic to the redundant path (risk: medium).
3. Dispatch field team for the physical repair; track via incident.
