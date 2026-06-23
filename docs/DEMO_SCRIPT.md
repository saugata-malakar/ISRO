# NeuraLink Copilot — Demo Script (judge-facing)

> **Air-Gapped Predictive Copilot for Secure MPLS Operations** · Team **ERROR 404**
> Bharatiya Antariksh Hackathon 2026 (PS #13)
>
> Everything runs **locally**. No byte leaves the box. The "network" is a
> labelled **simulator** standing in for the real ISRO MPLS fabric (there is no
> real ISRO hardware in the demo — see README §2). Randomness is **seeded**, so
> every run is identical.

---

## 0. One-time setup (offline-prep phase — before air-gapping)

```bash
make setup          # uv venv + install (Windows: see note below)
make prep           # seed runbooks/incidents → train baseline → build encrypted index
# (Optional) real LLM instead of the deterministic offline engine:
#   bash scripts/download_models.sh           # the ONLY script allowed to fetch
#   then set llm.mock:false + llm.model_path in config/settings.yaml
```

> **Windows / no `make`:** use the CLI directly with the venv Python, e.g.
> `\.venv\Scripts\python -m neuralink.cli prep` is `seed` + `train` + `index`, or run
> `\.venv\Scripts\python -m neuralink.cli demo`. Every Makefile target maps 1:1 to a
> `neuralink <subcommand>`.

The default build uses a **deterministic offline LLM engine** (`llm.mock: true`)
and an **offline hashing embedder**, so the entire pipeline runs with **zero
downloads**. Swap in a local GGUF (3B fallback for snappy live demos, 7B Mistral
as the documented production target) only if you want a live model.

---

## 1. The headline run (≈ 30–40 s wall-clock)

```bash
make demo
# or:  python scripts/run_demo.py --scenario cpu_starvation --seed 42
```

### What the operator/judge sees, in order

1. **Egress guard installs** — the process blocks all outbound connections for
   the duration of the run (defence-in-depth on top of the static air-gap scan).
2. **Topology row all green**, telemetry ticking on all 5 devices.
3. **⚠ Forecast early-warning** (~sim-t 70 s): *"PE-Router-03 cpu trending to
   exhaustion: 78% now, projected 100% in 90 s. Instability likely in ~27 s."*
   — fired **before** any hard failure.
4. **CPU_SPIKE WARNING** as the ramp crosses the operational threshold.
5. **🚨 CRITICAL alert**: `BGP_SESSION_DOWN` on PE-Router-03, anomaly ~94/100,
   **blast radius 87/100**, downstream **Ground-Station-Link-B (crit 1.0, ETA 30 s)**,
   **Telemetry-Feed-C**, **VoIP-Trunk-A** at risk.
6. **🧠 AI explanation + 🔍 RCA stream in** (grounded by the retrieved BGP runbook
   + the matching past incident): control-plane CPU exhaustion delayed BGP
   keepalives → neighbor dropped on hold-timer expiry.
7. **🛠 Remediation playbook** with `clear ip bgp 10.0.0.2 soft` marked
   **◀ RECOMMENDED**; the operator confirms **[Y]** (auto-confirmed headless).
   Execution is **SIMULATED** — the intended command is logged to the audit
   chain; nothing touches a real device.
8. **Audit footer** updates with a chained HMAC for every step.
9. **Proof footer**: `audit chain: VERIFIED` and `air-gap scan: CLEAN — zero egress`.

---

## 2. The PRIMARY UI — operator terminal (TUI)

```bash
make run        # python -m neuralink.cli tui --scenario cpu_starvation --seed 42
```

Reproduces the deck's wireframe: topology status row, alert panel, AI
explanation/RCA pane, streaming model output, and a remediation playbook.

| Key | Action |
|-----|--------|
| `Y` | Execute recommended step (**simulated**, audited) |
| `N` | Skip |
| `E` | Escalate |
| `P` | Pause / resume the feed |
| `Q` | Quit |

---

## 3. Prove the hard constraints live

```bash
make verify-audit     # recomputes the whole hash-chain → VERIFIED
make verify-airgap    # static scan: no http/https/requests/urllib/boto3/openai/CDN
```

**Tamper demo:** edit any byte of `data/runtime/audit.log` and re-run
`make verify-audit` → it reports `FAIL` at the offending sequence number
(AES-256-GCM auth + HMAC chain both catch it).

---

## 4. Other scenarios (all deterministic, all detected)

```bash
python -m neuralink.cli demo --scenario fiber_cut --seed 42
python -m neuralink.cli demo --scenario traffic_blackhole --seed 42   # the silent failure
python -m neuralink.cli demo --scenario hardware_fault --seed 42
python -m neuralink.cli demo --scenario interface_flap --seed 42
python -m neuralink.cli demo --scenario bgp_flap --seed 42
python -m neuralink.cli list-scenarios
```

| Scenario | What it shows |
|----------|---------------|
| `cpu_starvation` | **Hero** — predictive warning → CPU spike → BGP down → ground-station blast radius |
| `fiber_cut` | Link down severs LSP-12; CRITICAL |
| `traffic_blackhole` | Counters look healthy, throughput collapses — caught anyway |
| `hardware_fault` | Thermal runaway → shutdown |
| `interface_flap` | Rising CRC errors, storm suppressed to one alert |
| `bgp_flap` | Single-peer flap → WARNING (vs sustained 3-peer loss → CRITICAL) |

---

## 5. Talking points (why it matters)

- **30 min → < 5 min triage:** forecast + detection + blast radius + grounded RCA
  + ranked CLI, all on one screen.
- **Air-gapped by construction:** offline models, AES-256-GCM at rest, tamper-evident
  audit, runtime egress guard, static air-gap CI check.
- **Trustworthy AI:** retrieval-grounded, constrained to the real topology (no
  invented devices), confirm-before-execute, every action audited.
- **Honest engineering:** the simulator is clearly a stand-in; the offline LLM
  engine is deterministic; the 7B model is the documented production target while
  a 3B fallback keeps the live demo snappy.
