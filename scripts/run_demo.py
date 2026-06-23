"""One-command end-to-end demo (README §9).

    python scripts/run_demo.py --scenario cpu_starvation --seed 42

Drives a scenario through the orchestrator and renders the operator's view:
topology status, forecast early-warning, CRITICAL alert + blast radius, streaming
AI explanation/RCA, remediation playbook (with confirm-before-execute simulated),
and a tamper-evident audit footer. Proves zero egress and audit integrity at the
end. Deterministic for a given seed.
"""

from __future__ import annotations

import sys
import time

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from neuralink.config import get_settings
from neuralink.detection import baseline
from neuralink.orchestrator.pipeline import Hooks, Orchestrator
from neuralink.security.audit import AuditLog
from neuralink.security.egress_guard import install_egress_guard, verify_airgap
from neuralink.simulator import Simulator, get_scenario

console = Console()


def _ensure_artifacts() -> None:
    """Offline-prep artifacts (baseline + corpus + index). Generated locally,
    never downloaded. Auto-built on first demo run for convenience."""
    s = get_settings()
    s.ensure_runtime_dirs()
    if not baseline.default_artifact_path().exists():
        console.print("[dim]preparing anomaly baseline…[/dim]")
        from scripts import train_baseline

        train_baseline.main()
    if not list(s.runbooks_dir.glob("*.md")):
        console.print("[dim]seeding RAG corpus…[/dim]")
        from scripts import seed_data

        seed_data.main()
    if not s.faiss_path.exists():
        console.print("[dim]building RAG index…[/dim]")
        from scripts import build_index

        build_index.main()


def _reset_runtime_logs() -> None:
    """Clean audit log + event DB so the demo shows its own fresh chain."""
    s = get_settings()
    for p in (s.audit_path, s.db_path):
        if p.exists():
            p.unlink()


def _status_row(latest: dict, devices: list[str]) -> Table:
    t = Table.grid(expand=True)
    for _ in devices:
        t.add_column(justify="center")
    cells = []
    for d in devices:
        sev = latest.get(d, "info")
        color = {"critical": "bold white on red", "warning": "black on yellow"}.get(sev, "white on green")
        cells.append(f"[{color}] {d} [/]")
    t.add_row(*cells)
    return t


def main(scenario: str = "cpu_starvation", seed: int = 42, fast: bool = False) -> int:
    settings = get_settings()
    console.rule("[bold cyan]NeuraLink Copilot — Air-Gapped Predictive Copilot[/bold cyan]")
    console.print("[dim]Team ERROR 404 · simulated MPLS network (no real ISRO data) · all-local[/dim]\n")

    _ensure_artifacts()
    _reset_runtime_logs()
    install_egress_guard()  # prove zero egress for the duration of the demo
    console.print("[green]✓[/green] runtime egress guard installed (outbound blocked)\n")

    scen = get_scenario(scenario)
    sim = Simulator(scenario=scen, seed=seed)
    orch = Orchestrator(audit=AuditLog())
    devices = [n.id for n in sim.topology.nodes]

    console.print(Panel(scen.description, title=f"scenario: {scen.name} (seed={seed})", border_style="cyan"))

    latest_sev: dict[str, str] = {}
    fired = {"alert": False}

    def on_forecast(w):
        console.print(Panel(f"[bold]⚠ FORECAST EARLY-WARNING[/bold]\n{w.message}",
                            border_style="yellow", title="predictive"))

    def on_alert(alert, blast):
        ev = alert.event
        svc = "\n".join(f"   • {s.id}  (criticality {s.criticality}, degraded in ~{s.eta_seconds:.0f}s)"
                        for s in blast.affected_services) or "   • none"
        body = (
            f"[bold]{ev.event_type.value}[/bold] on [bold]{ev.source_device}[/bold] "
            f"({ev.source_ip})\n"
            f"anomaly score: {alert.anomaly_score}/100   blast radius: [bold]{blast.score}/100[/bold]\n"
            f"affected LSPs: {', '.join(blast.affected_lsps) or 'none'}\n"
            f"downstream services at risk:\n{svc}\n"
            f"syslog: [dim]{ev.raw_message}[/dim]"
        )
        console.print(Panel(body, border_style="red", title=f"🚨 {alert.severity.value} ALERT"))
        console.print("[dim]AI copilot analysing (streaming)…[/dim]")

    def on_token(tok):
        sys.stdout.write(f"\x1b[2m{tok}\x1b[0m")
        sys.stdout.flush()

    def on_response(alert, blast, resp):
        console.print("\n")
        console.print(Panel(resp.explanation, title="🧠 Explanation", border_style="cyan"))
        console.print(Panel(resp.root_cause, title="🔍 Root-Cause Hypothesis", border_style="magenta"))
        tbl = Table(title="🛠  Remediation Playbook (confirm-before-execute)", title_style="bold")
        for col in ("#", "command", "risk", "note", ""):
            tbl.add_column(col)
        for stp in resp.remediation:
            rec = "[bold green]◀ RECOMMENDED[/bold green]" if stp.recommended else ""
            risk_color = {"low": "green", "medium": "yellow", "high": "red"}.get(stp.risk.value, "white")
            tbl.add_row(str(stp.step), stp.command, f"[{risk_color}]{stp.risk.value}[/]", stp.note, rec)
        console.print(tbl)
        console.print(f"[dim]confidence {resp.confidence} · model {resp.model} · "
                      f"grounded by: {', '.join(resp.citations[:2])}[/dim]")

        # Confirm-before-execute. Headless demo auto-confirms the recommended step;
        # execution is SIMULATED (logged only — never touches real gear).
        rec_step = next((s for s in resp.remediation if s.recommended), None)
        if rec_step:
            console.print("\n[bold]Operator action[/bold] → [Y] Execute  [N] Skip  [E] Escalate "
                          "(auto-confirm: [green]Y[/green])")
            orch.record_action("EXECUTE_STEP", {
                "alert_id": alert.alert_id, "step": rec_step.step,
                "command": rec_step.command, "simulated": True})
            console.print(f"[green]✓ SIMULATED EXECUTE[/green]: {rec_step.command}  "
                          f"[dim](logged to audit; no device touched)[/dim]")

    def on_audit(entry):
        console.print(f"[dim]audit #{entry.seq} {entry.action} hash={entry.entry_hash[:12]}…[/dim]")

    hooks = Hooks(on_forecast=on_forecast, on_alert=on_alert, on_token=on_token,
                  on_response=on_response, on_audit=on_audit)

    # Drive the scenario.
    for tick, batch in sim.iter_ticks(30):
        for ev in batch:
            res = orch.process_event(ev, hooks)
            if res.alert is not None:
                fired["alert"] = True
            latest_sev[ev.source_device] = ev.severity_raw.value
        console.print(_status_row(latest_sev, devices))
        if not fast:
            time.sleep(settings.simulator.tick_seconds * 0.3)
        if fired["alert"] and tick > 24:
            break

    # Finale: prove integrity + zero egress.
    console.rule("[bold]proof[/bold]")
    audit_res = orch.audit.verify()
    console.print(f"audit chain: {'[green]VERIFIED[/green]' if audit_res.ok else '[red]TAMPERED[/red]'} "
                  f"({audit_res.count} entries)")
    ok, findings = verify_airgap()
    console.print(f"air-gap scan: {'[green]CLEAN — zero egress[/green]' if ok else '[red]VIOLATION[/red]'}")
    console.rule("[green]demo complete[/green]")
    return 0


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default="cpu_starvation")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--fast", action="store_true")
    a = ap.parse_args()
    raise SystemExit(main(scenario=a.scenario, seed=a.seed, fast=a.fast))
