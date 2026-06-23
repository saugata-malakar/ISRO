# Runbook: MPLS / LSP / Service Model

*Synthetic ISRO-style runbook — prototype data, not real.*

## Model
Services map to LSPs; LSPs traverse a path of PE/P routers. A node failure breaks
every LSP whose path includes it, and every service bound to those LSPs. Compute
blast radius from service criticality + count + node criticality.
