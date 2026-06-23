"""Unified command-line entry point (``neuralink <subcommand>``).

The Makefile targets shell out to these subcommands so the project is fully
operable on platforms without ``make`` (e.g. Windows). Subcommands are imported
lazily so a partially-installed environment still runs the parts that work.
"""

from __future__ import annotations

import argparse
import sys
import time

from neuralink.config import PROJECT_ROOT, get_settings

# Make the project-root `scripts/` package importable even when invoked via the
# installed console entry point (which does not add CWD to sys.path).
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _render_tick(console, tick: int, batch, sim_cfg) -> None:
    from rich.table import Table

    sim_t = tick * sim_cfg.time_compression
    table = Table(title=f"tick {tick}  ·  sim_t={sim_t:.0f}s", title_style="bold cyan")
    for col in ("device", "type", "sev", "cpu%", "mem%", "temp°C", "errs", "bgp", "link", "thrpt"):
        table.add_column(col, justify="right")
    for ev in batch:
        m = ev.metrics
        is_fault = "fault" in ev.tags
        style = "red" if ev.severity_raw.value == "critical" else (
            "yellow" if is_fault else "green"
        )
        table.add_row(
            ev.source_device,
            ev.event_type.value,
            ev.severity_raw.value,
            f"{m.cpu_pct:.0f}",
            f"{m.mem_pct:.0f}",
            f"{m.temp_c:.0f}",
            f"{m.if_in_errors + m.if_out_errors}",
            f"{m.bgp_peers_up}/{m.bgp_peers_total}",
            "up" if m.link_up else "DOWN",
            f"{m.throughput_mbps:.0f}",
            style=style,
        )
    console.print(table)
    for ev in batch:
        if "fault" in ev.tags:
            console.print(f"  [dim]syslog[/dim] {ev.raw_message}")


def cmd_run_sim(args: argparse.Namespace) -> int:
    from rich.console import Console

    from neuralink.simulator import Simulator, get_scenario

    settings = get_settings()
    console = Console()
    scenario = get_scenario(args.scenario) if args.scenario and args.scenario != "none" else None
    sim = Simulator(scenario=scenario, start_tick=args.start_tick, seed=args.seed)

    banner = scenario.name if scenario else "healthy (no fault)"
    console.rule(f"[bold]NeuraLink Simulator[/bold] · scenario={banner} · seed={sim.seed}")
    if scenario:
        console.print(f"[dim]{scenario.description}[/dim]")

    live = not args.fast
    for tick, batch in sim.iter_ticks(args.ticks):
        _render_tick(console, tick, batch, settings.simulator)
        if live:
            time.sleep(settings.simulator.tick_seconds)
    console.rule("[green]simulator run complete[/green]")
    return 0


def cmd_list_scenarios(_: argparse.Namespace) -> int:
    from neuralink.simulator.fault_injector import SCENARIO_BUILDERS

    for name in SCENARIO_BUILDERS:
        print(f"  {name:18s} {SCENARIO_BUILDERS[name]().description}")
    return 0


def cmd_verify_airgap(_: argparse.Namespace) -> int:
    from neuralink.security.egress_guard import verify_airgap

    ok, findings = verify_airgap()
    if ok:
        print("verify-airgap: PASS — no forbidden network symbols found.")
        return 0
    print("verify-airgap: FAIL — forbidden network references found:")
    for f in findings:
        print(f"  {f}")
    return 1


def cmd_verify_audit(_: argparse.Namespace) -> int:
    from neuralink.security.audit import AuditLog

    log = AuditLog()
    result = log.verify()
    if result.ok:
        print(f"verify-audit: PASS — {result.count} entries, chain intact.")
        return 0
    print(f"verify-audit: FAIL — {result.reason} (at seq {result.bad_seq}).")
    return 1


def cmd_seed(args: argparse.Namespace) -> int:
    from scripts import seed_data

    return seed_data.main(force=args.force)


def cmd_train(_: argparse.Namespace) -> int:
    from scripts import train_baseline

    return train_baseline.main()


def cmd_index(_: argparse.Namespace) -> int:
    from scripts import build_index

    return build_index.main()


def cmd_demo(args: argparse.Namespace) -> int:
    from scripts import run_demo

    return run_demo.main(scenario=args.scenario, seed=args.seed, fast=args.fast)


def cmd_serve(_: argparse.Namespace) -> int:
    import uvicorn

    s = get_settings()
    uvicorn.run("neuralink.api.server:app", host=s.api.host, port=s.api.port, log_level="info")
    return 0


def cmd_tui(args: argparse.Namespace) -> int:
    from neuralink.tui.app import run_tui

    return run_tui(scenario=args.scenario, seed=args.seed)


def cmd_web(_: argparse.Namespace) -> int:
    from neuralink.web.app import run_web

    return run_web()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="neuralink", description="NeuraLink Copilot CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    rs = sub.add_parser("run-sim", help="stream simulated telemetry + syslog")
    rs.add_argument("--scenario", default="none", help="fault scenario (or 'none')")
    rs.add_argument("--ticks", type=int, default=30)
    rs.add_argument("--start-tick", type=int, default=3)
    rs.add_argument("--seed", type=int, default=None)
    rs.add_argument("--fast", action="store_true", help="no real-time sleep between ticks")
    rs.set_defaults(func=cmd_run_sim)

    sub.add_parser("list-scenarios", help="list available fault scenarios").set_defaults(
        func=cmd_list_scenarios
    )

    sd = sub.add_parser("seed", help="generate synthetic runbooks + incidents")
    sd.add_argument("--force", action="store_true")
    sd.set_defaults(func=cmd_seed)

    sub.add_parser("train", help="train IsolationForest baseline").set_defaults(func=cmd_train)
    sub.add_parser("index", help="embed corpus -> encrypted FAISS index").set_defaults(
        func=cmd_index
    )

    dm = sub.add_parser("demo", help="run a full end-to-end scenario")
    dm.add_argument("--scenario", default="cpu_starvation")
    dm.add_argument("--seed", type=int, default=42)
    dm.add_argument("--fast", action="store_true")
    dm.set_defaults(func=cmd_demo)

    tu = sub.add_parser("tui", help="launch the Textual operator terminal")
    tu.add_argument("--scenario", default="cpu_starvation")
    tu.add_argument("--seed", type=int, default=42)
    tu.set_defaults(func=cmd_tui)

    sub.add_parser("serve", help="run the FastAPI server (localhost)").set_defaults(func=cmd_serve)
    sub.add_parser("web", help="run the Flask dashboard (localhost, optional)").set_defaults(
        func=cmd_web
    )
    sub.add_parser("verify-airgap", help="static scan for forbidden network symbols").set_defaults(
        func=cmd_verify_airgap
    )
    sub.add_parser("verify-audit", help="verify the audit hash-chain").set_defaults(
        func=cmd_verify_audit
    )
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
