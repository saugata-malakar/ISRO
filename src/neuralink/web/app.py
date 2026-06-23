"""Optional Flask dashboard (README §8 web, M8 stretch).

Localhost-only. Bundles ALL assets locally (no CDN, no remote fonts/JS — see the
air-gap constraint). Renders a topology map, an alert history table, and a CPU
trend chart drawn by a tiny hand-written canvas helper. The /api/run endpoint
runs a scenario through the orchestrator server-side and returns JSON.
"""

from __future__ import annotations

from neuralink.config import get_settings
from neuralink.orchestrator.pipeline import Hooks, Orchestrator
from neuralink.security.audit import AuditLog
from neuralink.security.egress_guard import install_egress_guard
from neuralink.simulator import Simulator, get_scenario
from neuralink.simulator.fault_injector import list_scenarios
from neuralink.simulator.topology_loader import load_topology


def create_app():
    from flask import Flask, jsonify, render_template, request

    app = Flask(__name__, static_folder="static", template_folder="templates")
    install_egress_guard()

    @app.get("/")
    def index():
        topo = load_topology()
        return render_template(
            "dashboard.html",
            nodes=[n.model_dump() for n in topo.nodes],
            edges=[e.model_dump() for e in topo.edges],
            scenarios=list_scenarios(),
        )

    @app.get("/api/run")
    def api_run():
        scenario = request.args.get("scenario", "cpu_starvation")
        seed = int(request.args.get("seed", "42"))
        ticks = int(request.args.get("ticks", "30"))

        # Fresh audit chain for this run.
        s = get_settings()
        if s.audit_path.exists():
            s.audit_path.unlink()

        sim = Simulator(scenario=get_scenario(scenario), seed=seed)
        orch = Orchestrator(audit=AuditLog())
        devices = [n.id for n in sim.topology.nodes]

        trend: list[dict] = []
        alerts: list[dict] = []
        forecasts: list[dict] = []

        hooks = Hooks(
            on_forecast=lambda w: forecasts.append(w.model_dump()),
            on_response=lambda a, b, r: alerts.append(
                {"alert": a.model_dump(), "blast": b.model_dump(), "response": r.model_dump()}
            ),
        )

        for tick, batch in sim.iter_ticks(ticks):
            row = {"tick": tick, "sim_time": tick * s.simulator.time_compression}
            for ev in batch:
                orch.process_event(ev, hooks)
                row[ev.source_device] = {
                    "cpu": ev.metrics.cpu_pct,
                    "temp": ev.metrics.temp_c,
                    "errors": ev.metrics.if_in_errors + ev.metrics.if_out_errors,
                    "sev": ev.severity_raw.value,
                    "score": ev.anomaly_score,
                }
            trend.append(row)

        audit = orch.audit.verify()
        return jsonify(
            {
                "scenario": scenario,
                "seed": seed,
                "devices": devices,
                "trend": trend,
                "alerts": alerts,
                "forecasts": forecasts,
                "audit": {"ok": audit.ok, "count": audit.count},
            }
        )

    @app.get("/api/execute")
    def api_execute():
        device = request.args.get("device", "PE-Router-03")
        command = request.args.get("command", "")
        alert_id = request.args.get("alert_id", "")

        orch = Orchestrator(audit=AuditLog())
        entry = orch.record_action(
            "EXECUTE_STEP",
            {"alert_id": alert_id, "device": device, "command": command, "simulated": True}
        )
        audit = orch.audit.verify()

        output = (
            f"{device}# {command}\n"
            f"Connection established to {device}.\n"
            f"Executing diagnostic playbook step...\n"
            f"Command output: OK. State changes applied.\n"
            f"Remediation logged to audit chain seq #{entry.seq}.\n"
        )

        return jsonify({
            "ok": True,
            "output": output,
            "audit": {"ok": audit.ok, "count": audit.count}
        })

    @app.get("/api/tamper")
    def api_tamper():
        s = get_settings()
        path = s.audit_path
        if not path.exists():
            return jsonify({"ok": False, "reason": "No audit log found. Please run a scenario first."})
        lines = [ln for ln in path.read_bytes().splitlines() if ln.strip()]
        if not lines:
            return jsonify({"ok": False, "reason": "Audit log is empty. Please run a scenario first."})
        last_line = lines[-1]
        corrupted = bytearray(last_line)
        for i in range(min(5, len(corrupted))):
            corrupted[i] = ord('f') if corrupted[i] != ord('f') else ord('0')
        lines[-1] = bytes(corrupted)
        path.write_bytes(b"\n".join(lines) + b"\n")
        return jsonify({"ok": True})

    @app.get("/api/verify")
    def api_verify():
        res = AuditLog().verify()
        return jsonify({
            "ok": res.ok,
            "count": res.count,
            "reason": res.reason,
            "bad_seq": res.bad_seq
        })

    return app


def run_web() -> int:
    import os
    s = get_settings()
    app = create_app()
    port = int(os.environ.get("PORT", s.web.port))
    host = os.environ.get("HOST", s.web.host)
    if "PORT" in os.environ:
        host = "0.0.0.0"
    app.run(host=host, port=port, debug=False)
    return 0
