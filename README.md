# NeuraLink Copilot — Build Specification (for Claude Code)

> **Air-Gapped Predictive Copilot for Secure MPLS Operations**
> Team **ERROR 404** · Bharatiya Antariksh Hackathon 2026 (PS #13)
>
> This file is the single source of truth for building the system. It is written **for an AI coding agent (Claude Code)** to execute against. Build in the order given. Respect the hard constraints — they are the entire point of the problem statement.

---

## 0. What we are building (one paragraph)

An AI assistant that lives **entirely inside an air-gapped network** and turns 30-minutes-to-hours of manual network-fault triage into **under 5 minutes**. It continuously ingests router/switch telemetry (SNMP + syslog), scores every event with an anomaly detector, maps the **blast radius** of a fault across the MPLS topology graph, retrieves the right runbooks via **offline RAG**, and uses a **local quantized LLM** to produce a plain-English explanation, a root-cause hypothesis, and ranked CLI remediation commands — all displayed in a secure operator terminal, with every action written to a **tamper-evident audit log**. No byte ever leaves the box.

---

## 1. Hard constraints (design invariants — never violate)

These are not features; they are correctness conditions. Code that breaks one of these is wrong even if it "works."

1. **No network egress at runtime.** The application makes **zero outbound network calls** during operation. No cloud APIs, no telemetry, no model downloads at runtime, no CDN assets, no `pip install` at runtime, no external fonts/JS. The *only* exception is `scripts/download_models.sh`, run **once, offline-prep phase only**, before air-gapping.
2. **All models run locally.** LLM and embedding model are loaded from local files (`data/models/`). If a file is missing, fail loudly with instructions — never fetch.
3. **Encryption at rest.** SQLite DB, FAISS index, and audit log are encrypted at rest with AES-256-GCM. Keys come from a local key file / env, never hardcoded.
4. **Append-only, tamper-evident audit.** Every alert, inference, and operator action is logged in a hash-chained log. Any edit to a past entry must be detectable.
5. **Confirm-before-execute.** The system **never auto-runs** a remediation CLI command. It proposes; a human confirms. (In the demo, "execute" is simulated — see §9.)
6. **Offline-first UI.** No external CDN, no Google Fonts, no remote JS. Bundle everything.
7. **Deterministic demo.** A judge must be able to reproduce a scenario on command. Randomness is seeded.

> Add a CI check / `make verify-airgap` that greps the codebase for `http://`, `https://`, `requests.get`, `urllib`, `boto3`, `openai`, CDN URLs, etc., outside the allowed download script, and fails if found.

---

## 2. Reality checks baked into this spec (read before coding)

The deck is the product vision. These are the engineering truths the build must honor:

- **There is no real ISRO network.** Everything on the "network" side is **simulated**. The simulator (`src/neuralink/simulator/`) is a first-class, demo-critical module — it generates realistic telemetry and injects scripted faults. Build it early.
- **CPU LLM latency is real.** Mistral-7B Q4_K_M is ~8–15 s/response on CPU. For a *live* demo that's painful. Make the model **configurable** and ship a fast fallback (a 3B-class instruct model) so demos stay snappy. Stream tokens to the UI so the operator sees output immediately.
- **4 GB VRAM cannot hold a 7B Q4 model.** Mistral-7B Q4_K_M ≈ 4.4 GB; a GTX 1650 (4 GB) cannot fully offload it. Either partial GPU offload + CPU, or use a 3B model for GPU. Treat `n_gpu_layers` as config; default to CPU.
- **Prefer correctness of the pipeline over model size.** A smaller model that returns fast and is grounded by good RAG demos far better than a big model that stalls.

---

## 3. Architecture (the pipeline)

```
                 ┌──────────────────────────────────────────────────────────┐
                 │            SIMULATOR (stands in for ISRO MPLS)            │
                 │  topology.yaml → telemetry_gen + syslog_gen + faults      │
                 └───────────────────────────┬──────────────────────────────┘
                                              │  SNMP-like metrics + syslog lines
                                              ▼
  ┌─────────────┐   events   ┌──────────────┐  scored  ┌──────────────────┐
  │ INGESTION   │──────────► │ DETECTION    │────────► │ TOPOLOGY ENGINE  │
  │ collect/    │  (JSON)    │ IsolationFor.│ (alerts) │ NetworkX + BFS    │
  │ parse/store │            │ + correlate  │          │ blast radius     │
  └─────────────┘            │ + forecast   │          └────────┬─────────┘
        │ (encrypted SQLite)  └──────────────┘                   │ fault context
        │                                                        ▼
        │                                          ┌──────────────────────────┐
        │                                          │ RAG  (FAISS, local embed) │
        │                                          │ top-k runbooks/incidents  │
        │                                          └────────────┬─────────────┘
        │                                                       ▼
        │                                          ┌──────────────────────────┐
        │                                          │ LLM  (llama.cpp, GGUF)    │
        │                                          │ explanation+RCA+CLI plan  │
        │                                          └────────────┬─────────────┘
        ▼                                                       ▼
  ┌──────────────────────────────────────────────────────────────────────────┐
  │ ORCHESTRATOR  → pushes to UI (TUI / Web)  → AUDIT CHAIN (hash-linked log)  │
  └──────────────────────────────────────────────────────────────────────────┘
        ▲                                                       ▲
        └──────────────  SECURITY: AES-256-GCM, JWT+RBAC, egress guard  ──────┘
```

The five layers from the deck map to packages: **(1) data sources → simulator**, **(2) ingestion**, **(3) intelligence core → detection + topology + rag + llm**, **(4) security**, **(5) interface → tui + web**.

---

## 4. Repository layout

```
neuralink-copilot/
├── README.md                      # this file
├── pyproject.toml                 # deps pinned (see §6)
├── Makefile                       # setup, run, demo, verify-airgap, test
├── .env.example                   # keys/paths (never commit real .env)
├── config/
│   ├── settings.yaml              # all tunables (thresholds, model paths, ports)
│   └── topology.yaml              # the simulated MPLS network (see §7.2)
├── data/
│   ├── models/                    # GGUF LLM + embed model  (gitignored)
│   ├── runbooks/                  # synthetic ISRO-style runbooks (.md)  → RAG
│   ├── incidents/                 # past resolved incidents (.json)       → RAG
│   └── runtime/                   # encrypted db, faiss index, audit log, keys
├── src/neuralink/
│   ├── config.py                  # pydantic-settings loader for settings.yaml
│   ├── schemas.py                 # ALL pydantic models / data contracts (§7)
│   ├── simulator/
│   │   ├── topology_loader.py     # parse topology.yaml → objects
│   │   ├── telemetry_gen.py       # per-device metric streams w/ noise
│   │   ├── syslog_gen.py          # realistic syslog lines
│   │   └── fault_injector.py      # scripted scenarios (§7.3)
│   ├── ingestion/
│   │   ├── collector.py           # async loop consuming simulator output
│   │   ├── parser.py              # grok/regex syslog → fields
│   │   ├── normaliser.py          # → NetworkEvent JSON (§7.1)
│   │   └── store.py               # encrypted SQLite (fault history)
│   ├── detection/
│   │   ├── baseline.py            # train IsolationForest on normal data
│   │   ├── anomaly.py             # score events 0–100, threshold → Alert
│   │   ├── correlation.py         # sliding-window dedup / alert-storm suppression
│   │   └── forecast.py            # trend-based early warning (feature #8)
│   ├── topology/
│   │   ├── graph.py               # build NetworkX DiGraph from topology
│   │   └── blast_radius.py        # weighted BFS → affected LSPs/services + score
│   ├── rag/
│   │   ├── corpus.py              # load + chunk runbooks/incidents
│   │   ├── embed.py               # local embedding model wrapper
│   │   └── index.py               # FAISS build + top-k query (encrypted at rest)
│   ├── llm/
│   │   ├── engine.py              # llama.cpp wrapper, streaming, model-swappable
│   │   ├── prompts.py             # prompt templates (explanation / RCA / CLI)
│   │   └── pipeline.py            # assemble context → 3 structured outputs
│   ├── security/
│   │   ├── crypto.py              # AES-256-GCM encrypt/decrypt + key mgmt
│   │   ├── audit.py              # hash-chained append-only audit log
│   │   ├── auth.py                # local JWT issue/verify + RBAC (3 roles)
│   │   └── egress_guard.py        # runtime assert no outbound; verify-airgap
│   ├── orchestrator/
│   │   └── pipeline.py            # event→alert→blast→rag→llm→ui→audit
│   ├── api/
│   │   └── server.py              # FastAPI: WebSocket alert feed + REST
│   ├── tui/
│   │   └── app.py                 # Textual operator terminal (PRIMARY UI)
│   └── web/
│       ├── app.py                 # Flask dashboard (localhost only, optional)
│       ├── static/                # bundled Chart.js, CSS — no CDN
│       └── templates/
├── scripts/
│   ├── download_models.sh         # ONE-TIME, pre-airgap only
│   ├── seed_data.py               # generate synthetic runbooks + incidents
│   ├── train_baseline.py          # produce IsolationForest model artifact
│   ├── build_index.py             # embed corpus → FAISS index
│   └── run_demo.py                # one command runs a full scenario end-to-end
├── tests/
│   ├── test_blast_radius.py
│   ├── test_audit_chain.py
│   ├── test_crypto.py
│   ├── test_parser.py
│   └── test_airgap.py             # asserts no forbidden network symbols
└── docs/
    └── DEMO_SCRIPT.md             # the finale walkthrough (judge-facing)
```

---

## 5. Build order (milestones) — follow this sequence

Each milestone is independently runnable and demoable. **Demo-critical path is M0→M1→M2→M3→M5→M7.** Do RAG (M4) and full security (M6) next; web dashboard + polish (M8) only if time remains.

| # | Milestone | Definition of done |
|---|-----------|--------------------|
| **M0** | Scaffold + config + simulator | `make run-sim` streams realistic per-device telemetry + syslog from `topology.yaml`; faults can be injected manually. Nothing else needed yet. |
| **M1** | Ingestion + encrypted store | Simulator output is parsed → `NetworkEvent` JSON → written to AES-256-GCM SQLite; queryable. |
| **M2** | Detection + forecast | IsolationForest scores events; thresholds raise `Alert`s; sliding window suppresses storms; trend forecaster emits early-warning before a scripted CPU-ramp fault. |
| **M3** | Topology + blast radius | On an alert, BFS computes affected LSPs + downstream services + a 0–100 blast-radius score. Unit-tested. |
| **M4** | Offline RAG | Synthetic corpus embedded into FAISS; top-k retrieval for a fault context in <200 ms; index encrypted at rest. |
| **M5** | Local LLM pipeline | llama.cpp loads local GGUF; given fault context + RAG docs, returns **3 structured outputs** (explanation, RCA hypothesis, ranked CLI plan). Streams tokens. Model swappable via config. |
| **M6** | Security | Hash-chained audit log (tamper-evident, verifiable); JWT auth + 3-role RBAC; `verify-airgap` passes. |
| **M7** | TUI + orchestrator | Textual terminal shows topology status, alert panel, AI explanation, remediation playbook with confirm-prompt, audit line. `scripts/run_demo.py --scenario X` drives the whole thing. |
| **M8** | Stretch | Flask dashboard (topology map, alert history, trend charts), more scenarios, more tests, perf tuning. |

---

## 6. Tech stack (pin these)

- **Python 3.11**
- LLM: **llama-cpp-python** (loads GGUF). Target model: `Mistral-7B-Instruct Q4_K_M`. **Demo fallback:** a 3B instruct GGUF (e.g. Qwen2.5-3B-Instruct Q4_K_M or Phi-3.5-mini) — set in `settings.yaml`.
- Embeddings: a **local** sentence-embedding model (e.g. `nomic-embed-text` GGUF via llama.cpp, or a local `sentence-transformers` MiniLM). Must run offline.
- Vector store: **faiss-cpu**
- ML: **scikit-learn** (IsolationForest), **pandas**, **numpy**
- Graph: **networkx**
- Backend: **fastapi**, **uvicorn**, **pydantic v2**, **pydantic-settings**, **apscheduler**
- Storage: stdlib **sqlite3** + **cryptography** (AES-256-GCM)
- Auth: **pyjwt**
- TUI: **textual**
- Web (optional): **flask**, **jinja2**, bundled **Chart.js** (no CDN)
- Parsing: **pygrok** or hand-written regex
- Dev: **pytest**, **ruff**, **mypy**

> Keep a `requirements.lock` / pinned versions so the environment is reproducible after air-gapping.

---

## 7. Data contracts (implement in `schemas.py` first)

### 7.1 `NetworkEvent`
```jsonc
{
  "event_id": "uuid4",
  "timestamp": "ISO-8601",
  "source_device": "PE-Router-03",
  "source_ip": "10.0.0.3",
  "event_type": "BGP_SESSION_DOWN | INTERFACE_FLAP | CPU_SPIKE | MEM_PRESSURE | LINK_DOWN | HARDWARE_FAULT | TRAFFIC_BLACKHOLE | NORMAL",
  "severity_raw": "info | warning | critical",   // as seen in syslog
  "metrics": { "cpu_pct": 92.3, "mem_pct": 71.0, "if_in_errors": 0,
               "if_out_errors": 0, "bgp_peers_up": 3, "bgp_peers_total": 4,
               "link_up": true, "temp_c": 41.0 },
  "raw_message": "original syslog line",
  "anomaly_score": null,                          // 0–100, filled by detector
  "tags": ["..."]
}
```

### 7.2 `topology.yaml` (the simulated MPLS network)
```yaml
nodes:
  - {id: PE-Router-01, type: PE,   asn: 65001, ip: 10.0.0.1, criticality: 0.9}
  - {id: P-Router-02,  type: P,    ip: 10.0.0.2, criticality: 0.7}
  - {id: PE-Router-03, type: PE,   asn: 65001, ip: 10.0.0.3, criticality: 0.95}
  - {id: CE-Router-07, type: CE,   asn: 65002, ip: 10.0.0.7, criticality: 0.6}
  - {id: CORE-SW-1,    type: SWITCH, ip: 10.0.1.1, criticality: 0.8}
edges:
  - {src: PE-Router-01, dst: P-Router-02,  link_type: physical, bandwidth_mbps: 10000, criticality: 0.8}
  - {src: P-Router-02,  dst: PE-Router-03, link_type: physical, bandwidth_mbps: 10000, criticality: 0.9}
  - {src: PE-Router-03, dst: CE-Router-07, link_type: physical, bandwidth_mbps: 1000,  criticality: 0.85}
lsps:
  - {id: LSP-12, path: [PE-Router-01, P-Router-02, PE-Router-03], services: [VoIP-Trunk-A, Ground-Station-Link-B]}
  - {id: LSP-15, path: [PE-Router-03, CE-Router-07],              services: [Telemetry-Feed-C]}
services:
  - {id: Ground-Station-Link-B, criticality: 1.0, lsps: [LSP-12]}
  - {id: VoIP-Trunk-A,          criticality: 0.7, lsps: [LSP-12]}
  - {id: Telemetry-Feed-C,      criticality: 0.95, lsps: [LSP-15]}
```

### 7.3 Fault scenarios (`fault_injector.py`)
Each scenario is a **timed sequence** of telemetry/syslog mutations so that the **forecaster** can warn *before* the hard failure. Implement at least:

- `cpu_starvation` → CPU ramps 60→99% over ~3 min, then `BGP_SESSION_DOWN` (the deck's hero scenario).
- `fiber_cut` → `LINK_DOWN` on an edge → LSPs on that edge break.
- `interface_flap` → repeated up/down with rising `if_errors`.
- `hardware_fault` → temp rises + interface errors → device unreachable.
- `traffic_blackhole` → metrics nominal but throughput drops (silent failure).
- `bgp_flap` → repeated peer up/down.

`run_demo.py --scenario cpu_starvation --seed 42` must reproduce identically.

### 7.4 `Alert`, `BlastRadius`, `CopilotResponse`, `AuditEntry`
```jsonc
// Alert
{ "alert_id":"...", "event": NetworkEvent, "severity":"WARNING|CRITICAL",
  "anomaly_score": 87, "created_at":"ISO-8601" }

// BlastRadius
{ "origin":"PE-Router-03", "affected_lsps":["LSP-12","LSP-15"],
  "affected_services":[{"id":"Ground-Station-Link-B","eta_seconds":30,"criticality":1.0}],
  "score": 87 }

// CopilotResponse  (the LLM pipeline output — keep STRUCTURED)
{ "explanation":"...plain English...",
  "root_cause":"...most probable + secondary hypothesis...",
  "remediation":[ {"step":1,"command":"show ip bgp summary","risk":"low","note":"verify peer state"},
                  {"step":3,"command":"clear ip bgp 10.0.0.2 soft","risk":"low","recommended":true} ],
  "confidence": 0.0 }

// AuditEntry  (hash-chained)
{ "seq": 42, "ts":"ISO-8601", "actor":"ops_user_01", "role":"operator",
  "action":"EXECUTE_STEP", "payload":{...},
  "prev_hash":"hex", "entry_hash":"hex" }   // entry_hash = HMAC_SHA256(key, canonical(seq..prev_hash))
```

---

## 8. Module specs (key behavior + acceptance criteria)

**simulator** — Generates per-device metric streams with Gaussian noise around healthy baselines; emits syslog lines in real Cisco/Junos-ish format. Fault injector overlays scenarios. *Done when:* a 10-min normal run shows stable metrics and a `cpu_starvation` run produces a visible ramp then a BGP-down syslog.

**ingestion** — `collector` consumes the simulator (in-process queue is fine — no real sockets needed, but keep the interface swappable so real SNMP/syslog could be dropped in). `parser` extracts fields; `normaliser` emits `NetworkEvent`; `store` persists encrypted. *Done when:* every simulated event lands in the encrypted DB and round-trips correctly.

**detection** — `baseline.py` trains IsolationForest on a normal-only run and saves the artifact. `anomaly.py` maps the model's score to **0–100**; >60 = WARNING, >85 = CRITICAL (configurable). `correlation.py` collapses duplicates inside a rolling 60 s window. `forecast.py` does simple trend extrapolation (rolling slope on CPU / error counters) → early warning. *Done when:* normal events score low, injected faults score high, and the CPU ramp triggers a forecast warning before the BGP drop.

**topology** — `graph.py` builds a `networkx.DiGraph` (+ LSP/service maps). `blast_radius.py`: from the origin node/edge, find LSPs whose path traverses it, then services depending on those LSPs; compute a weighted 0–100 score from service criticalities + count + node criticality; estimate degradation ETA. *Done when:* `test_blast_radius.py` proves that failing `PE-Router-03` flags `LSP-12/15` and `Ground-Station-Link-B`.

**rag** — `seed_data.py` writes ~15–30 synthetic runbooks (BGP recovery, interface flap, CPU starvation, fiber cut, hardware RMA, etc.) + past incidents. `build_index.py` embeds and saves a FAISS index (encrypted at rest). `index.query(context, k=5)` returns top docs with scores. *Done when:* a BGP fault context retrieves the BGP runbook in the top results, fully offline.

**llm** — `engine.py` wraps llama-cpp-python; model path, `n_ctx`, `n_gpu_layers`, temperature from config; **streaming** generation. `prompts.py` holds a system prompt that forces grounded, concise, structured output and forbids inventing device names not in context. `pipeline.py` assembles `{alert, blast_radius, retrieved_docs}` → calls the model → parses into `CopilotResponse` (instruct the model to emit JSON; validate with pydantic; retry once on parse failure). *Done when:* given the BGP scenario, output names the right devices, a plausible RCA, and safe CLI steps with the soft-reset recommended — within a few seconds on the fallback model.

**security** — `crypto.py`: AES-256-GCM helpers (random nonce per record, key from `data/runtime/master.key` or env). `audit.py`: append-only chain, `verify()` recomputes the whole chain and detects any tamper. `auth.py`: issue/verify local JWT, decorator-style RBAC (admin/operator/read-only). `egress_guard.py`: a function asserting no outbound + the `verify-airgap` static scan. *Done when:* `test_audit_chain.py` shows editing any past entry fails verification; `make verify-airgap` is green.

**orchestrator** — Wires the pipeline: event → detection → (if alert) blast radius → RAG → LLM → push to UI → write audit entries at each meaningful step. Backpressure-safe; one fault must not block ingestion of the next.

**api** — FastAPI app exposing a WebSocket alert/inference stream for the UIs and REST for history/auth. Localhost bind only.

**tui** (PRIMARY) — Textual app reproducing the deck's wireframe: topology status row, alert panel, AI explanation pane, remediation playbook with `[Y] Execute [N] Skip [E] Escalate`, audit footer. Executing a step is **simulated** (logs intended command + writes audit) — it does not touch real devices.

**web** (optional) — Flask on `localhost:5000`, bundled assets only: topology map, alert history table, trend charts.

---

## 9. Demo (what judges see) — put in `docs/DEMO_SCRIPT.md`

The headline run:

```bash
make demo          # or: python scripts/run_demo.py --scenario cpu_starvation --seed 42
```

Sequence the operator/judge observes:
1. Topology row all green; telemetry ticking.
2. **Forecast warning** (~3 min compressed to seconds): "PE-Router-03 CPU trending to exhaustion; BGP instability likely in ~90 s."
3. **CRITICAL alert** fires: `BGP-SESSION-DOWN`, blast-radius **87/100**, downstream `VoIP-Trunk-A`, `Ground-Station-Link-B`, `Telemetry-Feed-C` at risk.
4. **AI explanation + RCA** stream in (grounded by the retrieved BGP runbook).
5. **Remediation playbook** with `clear ip bgp ... soft` recommended; operator confirms `[Y]`.
6. **Audit footer** updates with a chained HMAC; run `make verify-audit` live to prove tamper-evidence.
7. Optionally run `make verify-airgap` live to prove zero egress.

Keep wall-clock under ~3 minutes. Use the fast fallback model for the live run.

---

## 10. Instructions for Claude Code (conventions)

**DO**
- Build milestone by milestone (§5); after each, ensure `make run-<thing>` works and write its test.
- Put **all** data shapes in `schemas.py` (pydantic v2) and import from there — no ad-hoc dicts.
- Read every tunable from `config/settings.yaml` via `config.py`. No magic numbers in logic.
- Keep the LLM/embedding models behind thin interfaces so they're swappable.
- Type-hint everything; pass `ruff` and `mypy`. Seed all randomness.
- Fail loudly with actionable messages when a local model/key is missing.
- Write `docs/DEMO_SCRIPT.md` and a top-level `Makefile` with: `setup`, `seed`, `train`, `index`, `run-sim`, `run`, `demo`, `verify-airgap`, `verify-audit`, `test`.

**DON'T**
- Don't add any runtime network call, cloud SDK, external API, CDN asset, or remote font. (Only `download_models.sh` may fetch, pre-airgap.)
- Don't auto-execute remediation commands. Confirm-before-execute, always.
- Don't hardcode secrets/keys. Use `.env` / key file.
- Don't invent device names in LLM output — constrain it to the provided topology/context.
- Don't over-build the web dashboard before the TUI + pipeline work.
- Don't claim real SNMP/ISRO data — the simulator is clearly labeled as a stand-in.

**First actions for the agent**
1. Scaffold the repo (§4), `pyproject.toml` (§6), `Makefile`, `.env.example`, `config/settings.yaml`, `config/topology.yaml` (§7.2).
2. Implement `schemas.py` (§7).
3. Build the **simulator** (M0) and prove `make run-sim`.
4. Proceed down §5.

---

## 11. Open assumptions (flag if any is wrong before deep work)

- Simulator stands in for the real network (no SNMP hardware in the demo).
- Live demo uses a 3B fallback model for latency; 7B Mistral is the documented production target.
- "Execute remediation" is simulated/logged, not run against live gear.
- Synthetic runbooks/incidents are acceptable as the RAG corpus for the prototype.

If all four hold, build straight through §5.
