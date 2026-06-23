"""Textual operator terminal — the PRIMARY UI (README §8 tui).

Reproduces the deck's wireframe: a topology status row, an alert panel, the AI
explanation/RCA pane, a remediation playbook with confirm-before-execute, and a
tamper-evident audit footer. The simulation + orchestrator run on a worker thread
and push updates into the UI; executing a step is SIMULATED (logged to audit,
never sent to a device).

Keys:  Y execute recommended · N skip · E escalate · P pause/resume · Q quit
"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Footer, Header, RichLog, Static

from neuralink.config import get_settings
from neuralink.orchestrator.pipeline import Hooks, Orchestrator
from neuralink.schemas import Alert, BlastRadius, CopilotResponse, RemediationStep
from neuralink.simulator import Simulator, get_scenario

_SEV_STYLE = {"critical": "bold white on red", "warning": "black on yellow", "info": "white on green"}


class NeuraLinkApp(App):
    CSS = """
    Screen { layout: vertical; }
    #topo { height: 3; border: round $accent; padding: 0 1; }
    #mid { height: 1fr; }
    #left { width: 55%; }
    #right { width: 45%; }
    #forecast { height: 5; border: round yellow; padding: 0 1; }
    #alert { height: 1fr; border: round red; padding: 0 1; }
    #explain { height: 1fr; border: round cyan; padding: 0 1; }
    #stream { height: 8; border: round $panel; padding: 0 1; }
    #playbook { height: 11; border: round green; }
    #audit { height: 4; border: round $panel; padding: 0 1; }
    """

    BINDINGS = [
        ("y", "execute", "Execute recommended"),
        ("n", "skip", "Skip"),
        ("e", "escalate", "Escalate"),
        ("p", "toggle_pause", "Pause/Resume"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, scenario: str = "cpu_starvation", seed: int = 42) -> None:
        super().__init__()
        self.scenario_name = scenario
        self.seed = seed
        self.settings = get_settings()
        self.orch: Orchestrator | None = None
        self.devices: list[str] = []
        self.latest_sev: dict[str, str] = {}
        self.paused = False
        self._pending: tuple[Alert, RemediationStep] | None = None

    # ------------------------------------------------------------------ #
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("topology", id="topo")
        with Horizontal(id="mid"):
            with Vertical(id="left"):
                yield Static("No early warning.", id="forecast")
                yield Static("No active alert. Monitoring telemetry…", id="alert")
            with Vertical(id="right"):
                yield Static("AI copilot idle.", id="explain")
                yield RichLog(id="stream", markup=False, highlight=False, wrap=True)
        yield DataTable(id="playbook")
        yield Static("audit: (empty)", id="audit")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "NeuraLink Copilot"
        self.sub_title = f"scenario={self.scenario_name} · seed={self.seed} · air-gapped"
        table = self.query_one("#playbook", DataTable)
        table.add_columns("#", "command", "risk", "note", "rec")
        self.run_worker(self._sim_loop(), name="sim", exclusive=True)

    # ------------------------------------------------------------------ #
    async def _sim_loop(self) -> None:
        """Async worker: drive the scenario; blocking pipeline work runs in an
        executor thread so the UI loop stays responsive (hooks marshal back via
        call_from_thread)."""
        import asyncio

        loop = asyncio.get_running_loop()
        scen = get_scenario(self.scenario_name)
        sim = Simulator(scenario=scen, seed=self.seed)
        self.devices = [n.id for n in sim.topology.nodes]
        # Fresh audit chain for the session, then build the orchestrator (loads
        # the baseline + RAG index) off the UI loop.
        if self.settings.audit_path.exists():
            self.settings.audit_path.unlink()
        self.orch = await loop.run_in_executor(None, Orchestrator)

        hooks = Hooks(
            on_forecast=lambda w: self.call_from_thread(self._on_forecast, w),
            on_alert=lambda a, b: self.call_from_thread(self._on_alert, a, b),
            on_token=lambda t: self.call_from_thread(self._on_token, t),
            on_response=lambda a, b, r: self.call_from_thread(self._on_response, a, b, r),
            on_audit=lambda e: self.call_from_thread(self._on_audit),
        )

        for _tick, batch in sim.iter_ticks(40):
            while self.paused:
                await asyncio.sleep(0.1)
            for ev in batch:
                self.latest_sev[ev.source_device] = ev.severity_raw.value
                await loop.run_in_executor(None, self.orch.process_event, ev, hooks)
            self._render_topo()
            await asyncio.sleep(self.settings.simulator.tick_seconds)

    # ------------------------------------------------------------------ #
    def _render_topo(self) -> None:
        cells = []
        for d in self.devices:
            sev = self.latest_sev.get(d, "info")
            cells.append(f"[{_SEV_STYLE.get(sev, 'white')}] {d} [/]")
        self.query_one("#topo", Static).update("  ".join(cells))

    def _on_forecast(self, warning) -> None:
        self.query_one("#forecast", Static).update(
            f"[bold yellow]⚠ FORECAST EARLY-WARNING[/]\n{warning.message}"
        )

    def _on_alert(self, alert: Alert, blast: BlastRadius) -> None:
        ev = alert.event
        svc = "\n".join(
            f"  • {s.id} (crit {s.criticality}, ~{s.eta_seconds:.0f}s)"
            for s in blast.affected_services
        ) or "  • none"
        self.query_one("#alert", Static).update(
            f"[bold red]🚨 {alert.severity.value}[/]  {ev.event_type.value} on "
            f"[bold]{ev.source_device}[/]\n"
            f"anomaly {alert.anomaly_score}/100 · blast [bold]{blast.score}/100[/]\n"
            f"LSPs: {', '.join(blast.affected_lsps) or 'none'}\n"
            f"services at risk:\n{svc}"
        )
        self.query_one("#stream", RichLog).clear()
        self.query_one("#explain", Static).update("[dim]AI copilot analysing (streaming)…[/]")

    def _on_token(self, tok: str) -> None:
        self.query_one("#stream", RichLog).write(tok)

    def _on_response(self, alert: Alert, blast: BlastRadius, resp: CopilotResponse) -> None:
        table = self.query_one("#playbook", DataTable)
        table.clear()
        rec_step: RemediationStep | None = None
        for s in resp.remediation:
            mark = "◀ YES" if s.recommended else ""
            table.add_row(str(s.step), s.command, s.risk.value, s.note, mark)
            if s.recommended:
                rec_step = s

        text = (
            f"[bold cyan]🧠 Explanation[/]\n{resp.explanation}\n\n"
            f"[bold magenta]🔍 Root cause[/]\n{resp.root_cause}\n\n"
            f"[dim]confidence {resp.confidence} · {resp.model}[/]"
        )
        if rec_step:
            self._pending = (alert, rec_step)
            text += f"\n\n[bold]Confirm:[/] [Y] {rec_step.command}  ·  [N] skip  ·  [E] escalate"
        self.query_one("#explain", Static).update(text)

    def _on_audit(self) -> None:
        if not self.orch:
            return
        tail = self.orch.audit.tail(3)
        lines = [f"#{e.seq} {e.action} {e.entry_hash[:10]}…" for e in tail]
        res = self.orch.audit.verify()
        status = "[green]VERIFIED[/]" if res.ok else "[red]TAMPERED[/]"
        self.query_one("#audit", Static).update(
            f"audit chain {status} ({res.count}) | " + "  ".join(lines)
        )

    # ------------------------------------------------------------------ #
    def _act(self, action: str) -> None:
        if not self._pending or not self.orch:
            self.notify("No pending remediation.", severity="warning")
            return
        alert, step = self._pending
        payload = {"alert_id": alert.alert_id, "step": step.step,
                   "command": step.command, "simulated": True}
        self.orch.record_action(action, payload)
        verb = {"EXECUTE_STEP": "SIMULATED EXECUTE", "SKIP_STEP": "skipped", "ESCALATE": "escalated"}[action]
        self.notify(f"{verb}: {step.command}", title="operator action")
        self._pending = None
        self._on_audit()

    def action_execute(self) -> None:
        self._act("EXECUTE_STEP")

    def action_skip(self) -> None:
        self._act("SKIP_STEP")

    def action_escalate(self) -> None:
        self._act("ESCALATE")

    def action_toggle_pause(self) -> None:
        self.paused = not self.paused
        self.notify("paused" if self.paused else "resumed")


def run_tui(scenario: str = "cpu_starvation", seed: int = 42) -> int:
    NeuraLinkApp(scenario=scenario, seed=seed).run()
    return 0
