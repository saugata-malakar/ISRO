# NeuraLink Copilot 🛰️
> **Air-Gapped Predictive Copilot for Secure MPLS Operations**
> Team **ERROR 404** · Bharatiya Antariksh Hackathon 2026 (PS #13)

---

### 🌐 Live Dashboard URL
Deploy is fully live and running in production on Render:
**👉 [https://isro-1-p8fz.onrender.com/](https://isro-1-p8fz.onrender.com/)**

---

## 🚀 What is NeuraLink Copilot?
An AI assistant designed to run **entirely inside an air-gapped network** (like ISRO's classified ground station operations), turning 30-minutes-to-hours of manual network-fault triage into **under 5 minutes**. 

It continuously ingests simulated router/switch telemetry (SNMP + syslog), scores events with an **IsolationForest** anomaly detector, maps the **blast radius** of faults across the MPLS topology graph using NetworkX, retrieves specific runbooks via **offline RAG**, and uses a local quantized model to produce plain-English root-cause explanations and ranked CLI remediation commands. No bytes ever leave the local secure network.

---

## 🎨 Premium NOC Interface & Interactive Features

The Flask Web Dashboard ([http://localhost:5000](http://localhost:5000)) has been fully customized into a state-of-the-art **NOC (Network Operations Center)**:

### 1. 🌌 Futuristic Cyber Glassmorphism
* **Modern CSS Styling**: Designed with dark translucent panels, radial background space gradients, micro-blur filters, and glowing cyan, emerald, and red borders.
* **Animated Packet Flows**: The topology map is alive with animated dashed edges that dynamically flow along network pathways to represent active packet transmission.
* **Pulsing Alarm States**: Active nodes on the topology map pulsate using SVG drop-shadow keyframe glow filters based on their active warning or critical status.

### 2. 🎞️ Stepped Live Playback
* Clicking **▶ Run** triggers a smooth, real-time animation playback loop (180ms per tick) that allows judges to watch telemetry trends fill from left to right, alerts slide in, and nodes change state chronologically as the scenario unfolds.

### 3. 📈 Multi-Metric Telemetry Selector
* Toggle the trend chart in real-time between **CPU (%)**, **Temperature (°C)**, and **Interface Errors** using a clean dropdown menu. The chart automatically scales its y-axis, updates threshold lines, and draws corresponding neon curves.

### 4. 💻 Interactive operator CLI console
* Proposes recommended commands using a character-by-character **console typing animation**. Operators confirm and execute CLI commands via the `/api/execute` endpoint, writing the step securely to the audit chain.

### 5. 🔐 Tamper-Evidence Simulator
* Click **Simulate Tamper** to manually corrupt the encrypted logs on disk, then click **Verify Chain** to run the cryptographic HMAC-SHA256 integrity check. If altered, GCM decryption fails, and the dashboard flashes red with a `TAMPER DETECTED` alarm.

---

## 🛠️ Installation & Local Setup

### 1. Requirements
* **Python 3.11** (Render uses Python `3.11.9` enforced by `.python-version`)
* **Local package installation** (Editable mode recommended to preserve `PROJECT_ROOT` configurations):
  ```bash
  pip install -e .[web] gunicorn
  ```

### 2. One-Command Setup (Offline-Prep)
Seed the runbooks/incidents corpus, train the IsolationForest baseline model, and embed the corpus into the encrypted FAISS search index:
```bash
python -m neuralink.cli seed --force
python -m neuralink.cli train
python -m neuralink.cli index
```

### 3. Run the App
* **Start Web Dashboard**:
  ```bash
  python -m neuralink.cli web
  ```
  Open **[http://localhost:5000](http://localhost:5000)** in your browser.
* **Start TUI Interface (Primary TUI Terminal)**:
  ```bash
  python -m neuralink.cli tui --scenario cpu_starvation
  ```
* **Verify Codebase Type Checks**:
  ```bash
  python -m mypy
  ```
* **Run Verification Tests**:
  ```bash
  python -m pytest
  ```

---

## 🧱 Repository Architecture

* `config/` — holds `settings.yaml` (tunables and ports) and `topology.yaml` (simulated MPLS network).
* `data/` — contains offline runbooks, resolved incidents, and runtime AES-encrypted storage files.
* `src/neuralink/` — core codebase:
  * `schemas.py` — unified data contracts (Pydantic v2).
  * `detection/` — anomaly IsolationForest, correlate storm filters, and multi-metric forecasters.
  * `security/` — AES-256-GCM encryption, HMAC-SHA256 audit chaining, and socket monkeypatching (Egress Guard).
  * `web/` — Flask dashboard, static stylesheet animations, and interactive console endpoints.
  * `tui/` — Textual console terminal.

---

## 🛡️ Core Hard Constraints (Design Invariants)
1. **Zero Runtime Egress**: Static checks scans the code (`make verify-airgap`) and monkeypatches python sockets (`egress_guard.py`) to block outbound calls.
2. **Local Models Only**: Quantized GGUF LLM and local sentence-transformers (configured via `settings.yaml`).
3. **Encryption at Rest**: AES-256-GCM SQLite blobs, FAISS index, and audit logs.
4. **Chained HMAC Logs**: Tamper-proof sequence hashes block database manipulation.
5. **Confirm-Before-Execute**: Remediation console prompts operators for confirmation before simulated deployment.
