# Runbook: CPU Starvation on Router

*Synthetic ISRO-style runbook — prototype data, not real.*

## Symptom
Sustained high CPU (%SYS-2-CPUHOG), control-plane protocols (BGP/OSPF) at risk.
CPU trending upward toward 100% over minutes.

## Likely causes
- Process loop / punted traffic to CPU (ACL log, ICMP redirects).
- Routing churn causing recomputation.
- Insufficient hardware for current load.

## Diagnosis
1. `show processes cpu sorted` — top CPU consumers.
2. `show processes cpu history` — confirm the ramp trend.
3. `show ip traffic` — look for punted/exception traffic.

## Remediation
1. `show processes cpu sorted` — identify the process (risk: low, RECOMMENDED).
2. Rate-limit or disable the offending feature (e.g. `no ip redirects`) (risk: medium).
3. Apply CoPP / control-plane policing to protect routing (risk: medium).

## Prevention
Deploy control-plane policing (CoPP) and monitor CPU trend with early-warning
thresholds so action is taken before BGP drops.
