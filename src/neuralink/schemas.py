"""All data contracts (README §7). Every module imports shapes from here —
no ad-hoc dicts anywhere in the codebase.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, Field


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


def _uuid4() -> str:
    return str(uuid.uuid4())


# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #
class EventType(str, Enum):
    BGP_SESSION_DOWN = "BGP_SESSION_DOWN"
    INTERFACE_FLAP = "INTERFACE_FLAP"
    CPU_SPIKE = "CPU_SPIKE"
    MEM_PRESSURE = "MEM_PRESSURE"
    LINK_DOWN = "LINK_DOWN"
    HARDWARE_FAULT = "HARDWARE_FAULT"
    TRAFFIC_BLACKHOLE = "TRAFFIC_BLACKHOLE"
    NORMAL = "NORMAL"


class SeverityRaw(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertSeverity(str, Enum):
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class Risk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# --------------------------------------------------------------------------- #
# 7.1 NetworkEvent
# --------------------------------------------------------------------------- #
class Metrics(BaseModel):
    cpu_pct: float = 0.0
    mem_pct: float = 0.0
    if_in_errors: int = 0
    if_out_errors: int = 0
    bgp_peers_up: int = 0
    bgp_peers_total: int = 0
    link_up: bool = True
    temp_c: float = 0.0
    throughput_mbps: float = 0.0  # used by traffic_blackhole (silent failure)


class NetworkEvent(BaseModel):
    event_id: str = Field(default_factory=_uuid4)
    timestamp: str = Field(default_factory=_utcnow_iso)  # ISO-8601
    sim_time: float = 0.0  # simulated seconds since scenario start (deterministic ordering)
    source_device: str
    source_ip: str
    event_type: EventType = EventType.NORMAL
    severity_raw: SeverityRaw = SeverityRaw.INFO
    metrics: Metrics = Field(default_factory=Metrics)
    raw_message: str = ""
    anomaly_score: float | None = None  # 0-100, filled by detector
    tags: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# 7.4 Alert
# --------------------------------------------------------------------------- #
class Alert(BaseModel):
    alert_id: str = Field(default_factory=_uuid4)
    event: NetworkEvent
    severity: AlertSeverity
    anomaly_score: float
    created_at: str = Field(default_factory=_utcnow_iso)


# --------------------------------------------------------------------------- #
# Forecast early-warning (feature #8)
# --------------------------------------------------------------------------- #
class ForecastWarning(BaseModel):
    warning_id: str = Field(default_factory=_uuid4)
    device: str
    metric: str
    current_value: float
    projected_value: float
    eta_seconds: float
    message: str
    sim_time: float = 0.0
    created_at: str = Field(default_factory=_utcnow_iso)


# --------------------------------------------------------------------------- #
# 7.4 BlastRadius
# --------------------------------------------------------------------------- #
class AffectedService(BaseModel):
    id: str
    eta_seconds: float
    criticality: float


class BlastRadius(BaseModel):
    origin: str
    affected_lsps: list[str] = Field(default_factory=list)
    affected_services: list[AffectedService] = Field(default_factory=list)
    affected_nodes: list[str] = Field(default_factory=list)
    score: int = 0  # 0-100


# --------------------------------------------------------------------------- #
# RAG retrieval
# --------------------------------------------------------------------------- #
class RetrievedDoc(BaseModel):
    doc_id: str
    source: str  # file path or incident id
    kind: str  # "runbook" | "incident"
    title: str
    text: str
    score: float  # similarity 0-1


# --------------------------------------------------------------------------- #
# 7.4 CopilotResponse (LLM pipeline output — STRUCTURED)
# --------------------------------------------------------------------------- #
class RemediationStep(BaseModel):
    step: int
    command: str
    risk: Risk = Risk.LOW
    note: str = ""
    recommended: bool = False


class CopilotResponse(BaseModel):
    explanation: str = ""
    root_cause: str = ""
    remediation: list[RemediationStep] = Field(default_factory=list)
    confidence: float = 0.0
    citations: list[str] = Field(default_factory=list)  # doc ids/titles used
    model: str = ""  # which engine produced this (mock / gguf name)


# --------------------------------------------------------------------------- #
# 7.4 AuditEntry (hash-chained)
# --------------------------------------------------------------------------- #
class AuditEntry(BaseModel):
    seq: int
    ts: str = Field(default_factory=_utcnow_iso)
    actor: str
    role: str
    action: str
    payload: dict = Field(default_factory=dict)
    prev_hash: str
    entry_hash: str = ""  # HMAC_SHA256(key, canonical(seq..prev_hash))


# --------------------------------------------------------------------------- #
# Topology models (loaded from config/topology.yaml — §7.2)
# --------------------------------------------------------------------------- #
class Node(BaseModel):
    id: str
    type: str
    ip: str
    asn: int | None = None
    criticality: float = 0.5
    x: float = 0.0
    y: float = 0.0


class Edge(BaseModel):
    src: str
    dst: str
    link_type: str = "physical"
    bandwidth_mbps: int = 1000
    criticality: float = 0.5


class LSP(BaseModel):
    id: str
    path: list[str]
    services: list[str] = Field(default_factory=list)


class Service(BaseModel):
    id: str
    criticality: float = 0.5
    lsps: list[str] = Field(default_factory=list)


class Topology(BaseModel):
    nodes: list[Node]
    edges: list[Edge]
    lsps: list[LSP] = Field(default_factory=list)
    services: list[Service] = Field(default_factory=list)

    def node(self, node_id: str) -> Node | None:
        return next((n for n in self.nodes if n.id == node_id), None)

    def service(self, sid: str) -> Service | None:
        return next((s for s in self.services if s.id == sid), None)

    def lsp(self, lid: str) -> LSP | None:
        return next((lsp for lsp in self.lsps if lsp.id == lid), None)
