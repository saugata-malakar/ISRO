"""Prompt templates + grounded remediation playbooks (README §8 llm).

The system prompt forces concise, grounded, *structured JSON* output and forbids
inventing device names not present in the supplied context. The playbooks encode
safe, vendor-style CLI steps per event type and are used both to steer the real
LLM and to drive the deterministic offline engine.
"""

from __future__ import annotations

from neuralink.schemas import Alert, BlastRadius, EventType, RetrievedDoc, Risk

SYSTEM_PROMPT = """You are NeuraLink Copilot, an air-gapped assistant for ISRO MPLS \
network operations. You help an on-call operator triage a fault FAST.

RULES (non-negotiable):
- Ground every statement ONLY in the provided FAULT CONTEXT and RETRIEVED DOCS.
- NEVER invent device names, IPs, services, or LSPs that are not in the context.
- Be concise and operational. Prefer least-invasive remediation first.
- You PROPOSE commands; a human confirms before anything runs. Never imply auto-execution.
- Output a SINGLE valid JSON object and nothing else, matching this schema:
{
  "explanation": str,            // plain-English what is happening + impact
  "root_cause": str,             // most probable cause + a secondary hypothesis
  "remediation": [               // ordered, least-invasive first
    {"step": int, "command": str, "risk": "low|medium|high",
     "note": str, "recommended": bool}
  ],
  "confidence": float,           // 0.0-1.0
  "citations": [str]             // titles/ids of docs you used
}
"""

# Per-event-type CLI playbooks: (command, risk, note, recommended)
PLAYBOOKS: dict[EventType, list[tuple[str, Risk, str, bool]]] = {
    EventType.BGP_SESSION_DOWN: [
        ("show ip bgp summary", Risk.LOW, "verify which peer is down and its state", False),
        ("show processes cpu sorted", Risk.LOW, "check if the control plane is CPU-starved", False),
        ("clear ip bgp {peer} soft", Risk.LOW, "soft reconfig — re-establish without a full reset", True),
        ("clear ip bgp {peer}", Risk.MEDIUM, "hard reset if the soft clear does not recover the peer", False),
    ],
    EventType.CPU_SPIKE: [
        ("show processes cpu sorted", Risk.LOW, "identify the process starving the CPU", True),
        ("show processes cpu history", Risk.LOW, "confirm the upward trend", False),
        ("control-plane policing: apply CoPP policy", Risk.MEDIUM, "protect routing from punted traffic", False),
    ],
    EventType.LINK_DOWN: [
        ("show interface {iface}", Risk.LOW, "confirm physical layer down, not admin-down", True),
        ("show mpls lsp", Risk.LOW, "list LSPs traversing the failed link", False),
        ("reroute traffic to backup path", Risk.MEDIUM, "if FRR did not protect automatically", False),
    ],
    EventType.INTERFACE_FLAP: [
        ("show interface {iface}", Risk.LOW, "inspect CRC/input error counters and flap count", True),
        ("shutdown ; no shutdown {iface}", Risk.MEDIUM, "reset the interface", False),
        ("replace SFP / clean fiber", Risk.MEDIUM, "if optics are degraded", False),
    ],
    EventType.HARDWARE_FAULT: [
        ("show environment all", Risk.LOW, "confirm the thermal/power source", True),
        ("drain traffic off the device", Risk.MEDIUM, "shift load before a thermal halt", False),
        ("raise RMA for faulty FRU", Risk.MEDIUM, "replace during maintenance window", False),
    ],
    EventType.TRAFFIC_BLACKHOLE: [
        ("show ip cef {prefix}", Risk.LOW, "verify the forwarding entry resolves", True),
        ("show mpls forwarding-table", Risk.LOW, "confirm label bindings (LFIB)", False),
        ("clear ip route *", Risk.MEDIUM, "rebuild RIB/FIB; brief reconvergence", False),
    ],
    EventType.MEM_PRESSURE: [
        ("show memory statistics", Risk.LOW, "identify the memory consumer", True),
        ("clear stale sessions/caches", Risk.MEDIUM, "reclaim memory where safe", False),
        ("schedule maintenance reload", Risk.MEDIUM, "if a leak is confirmed", False),
    ],
}


def fault_context_block(alert: Alert, blast: BlastRadius, allowed_devices: list[str]) -> str:
    ev = alert.event
    m = ev.metrics
    svcs = ", ".join(f"{s.id}(crit={s.criticality},eta={s.eta_seconds}s)" for s in blast.affected_services) or "none"
    return (
        "FAULT CONTEXT\n"
        f"- device: {ev.source_device} ({ev.source_ip})\n"
        f"- event_type: {ev.event_type.value}  severity: {alert.severity.value}  anomaly_score: {alert.anomaly_score}\n"
        f"- metrics: cpu={m.cpu_pct}% mem={m.mem_pct}% temp={m.temp_c}C "
        f"if_errors={m.if_in_errors + m.if_out_errors} "
        f"bgp={m.bgp_peers_up}/{m.bgp_peers_total} link={'up' if m.link_up else 'DOWN'} "
        f"throughput={m.throughput_mbps}Mbps\n"
        f"- raw_syslog: {ev.raw_message}\n"
        f"- blast_radius: score={blast.score}/100 origin={blast.origin}\n"
        f"- affected_lsps: {', '.join(blast.affected_lsps) or 'none'}\n"
        f"- affected_services: {svcs}\n"
        f"- ALLOWED device names (use only these): {', '.join(allowed_devices)}\n"
    )


def docs_block(docs: list[RetrievedDoc]) -> str:
    if not docs:
        return "RETRIEVED DOCS: (none)\n"
    lines = ["RETRIEVED DOCS (grounding — cite by title/id):"]
    for d in docs:
        snippet = d.text.replace("\n", " ").strip()
        if len(snippet) > 500:
            snippet = snippet[:500] + "..."
        lines.append(f"- [{d.kind}] {d.title} (score={d.score}): {snippet}")
    return "\n".join(lines) + "\n"


def build_user_prompt(
    alert: Alert, blast: BlastRadius, docs: list[RetrievedDoc], allowed_devices: list[str]
) -> str:
    return (
        fault_context_block(alert, blast, allowed_devices)
        + "\n"
        + docs_block(docs)
        + "\nProduce the JSON object now. Output JSON only."
    )
