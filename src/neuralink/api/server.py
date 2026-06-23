"""FastAPI server (README §8 api): WebSocket alert/inference feed + REST.

Binds localhost only (config). Installs the runtime egress guard on startup. The
WebSocket drives a scenario through the orchestrator and streams every stage
(telemetry/forecast/alert/token/response/audit) as JSON — this is what an
optional browser UI would consume.
"""

from __future__ import annotations

import asyncio

from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from neuralink.config import get_settings
from neuralink.orchestrator.pipeline import Hooks, Orchestrator
from neuralink.security import auth
from neuralink.security.audit import AuditLog
from neuralink.security.egress_guard import install_egress_guard, verify_airgap
from neuralink.simulator import get_scenario
from neuralink.simulator.fault_injector import list_scenarios

app = FastAPI(title="NeuraLink Copilot", version="0.1.0")


@app.on_event("startup")
def _startup() -> None:
    install_egress_guard()  # defence-in-depth: block outbound for the process


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #
class TokenRequest(BaseModel):
    subject: str = "ops_user_01"
    role: str = "operator"


def require_view(authorization: str | None = Header(default=None)) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token.")
    token = authorization.split(" ", 1)[1]
    try:
        return auth.require_permission(token, "view")
    except auth.AuthError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.post("/auth/token")
def issue_token(req: TokenRequest) -> dict:
    try:
        token = auth.issue_token(req.subject, req.role)
    except auth.AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"token": token, "role": req.role, "subject": req.subject}


# --------------------------------------------------------------------------- #
# REST
# --------------------------------------------------------------------------- #
@app.get("/health")
def health() -> dict:
    return {"status": "ok", "env": get_settings().env}


@app.get("/scenarios")
def scenarios() -> dict:
    return {"scenarios": list_scenarios()}


@app.get("/audit/verify")
def audit_verify(_claims: dict = Depends(require_view)) -> dict:
    res = AuditLog().verify()
    return {"ok": res.ok, "count": res.count, "reason": res.reason, "bad_seq": res.bad_seq}


@app.get("/airgap/verify")
def airgap_verify() -> dict:
    ok, findings = verify_airgap()
    return {"ok": ok, "findings": findings}


# --------------------------------------------------------------------------- #
# WebSocket alert/inference stream
# --------------------------------------------------------------------------- #
@app.websocket("/ws/alerts")
async def ws_alerts(ws: WebSocket) -> None:
    await ws.accept()
    params = ws.query_params
    scenario = params.get("scenario", "cpu_starvation")
    seed = int(params.get("seed", "42"))
    ticks = int(params.get("ticks", "40"))

    from neuralink.simulator import Simulator

    loop = asyncio.get_running_loop()
    settings = get_settings()
    queue: asyncio.Queue = asyncio.Queue()

    def emit(kind: str, data: dict) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, {"type": kind, **data})

    hooks = Hooks(
        on_forecast=lambda w: emit("forecast", w.model_dump()),
        on_alert=lambda a, b: emit("alert", {"alert": a.model_dump(), "blast": b.model_dump()}),
        on_token=lambda t: emit("token", {"text": t}),
        on_response=lambda a, b, r: emit("response", {"alert_id": a.alert_id, "response": r.model_dump()}),
        on_audit=lambda e: emit("audit", {"seq": e.seq, "action": e.action, "hash": e.entry_hash[:16]}),
    )

    try:
        orch = await loop.run_in_executor(None, Orchestrator)
        sim = Simulator(scenario=get_scenario(scenario), seed=seed)
    except Exception as exc:  # noqa: BLE001
        await ws.send_json({"type": "error", "detail": str(exc)})
        await ws.close()
        return

    async def producer() -> None:
        for _tick, batch in sim.iter_ticks(ticks):
            for ev in batch:
                await loop.run_in_executor(None, orch.process_event, ev, hooks)
            emit("telemetry", {"devices": {e.source_device: {
                "cpu": e.metrics.cpu_pct, "sev": e.severity_raw.value,
                "score": e.anomaly_score} for e in batch}})
            await asyncio.sleep(settings.simulator.tick_seconds)
        emit("done", {})

    task = asyncio.create_task(producer())
    try:
        while True:
            msg = await queue.get()
            await ws.send_json(msg)
            if msg["type"] == "done":
                break
    except WebSocketDisconnect:
        pass
    finally:
        task.cancel()
        try:
            await ws.close()
        except RuntimeError:
            pass
