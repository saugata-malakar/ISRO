"""Configuration loader (README §10: read every tunable from settings.yaml).

Loads ``config/settings.yaml`` into typed pydantic models, layers a ``.env`` /
environment overrides on top (prefix ``NEURALINK_``), resolves all paths against
the project root, and caches the result. No magic numbers anywhere else in code.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

# Project root = the dir that contains config/ and data/. This file lives at
# <root>/src/neuralink/config.py, so root is parents[2].
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv(root: Path) -> None:
    """Minimal .env loader (no external dep, no network). Does not overwrite
    variables already present in the environment."""
    env_file = root / ".env"
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


# --------------------------------------------------------------------------- #
# Typed settings models (mirror config/settings.yaml)
# --------------------------------------------------------------------------- #
class Paths(BaseModel):
    data_dir: str = "data"
    models_dir: str = "data/models"
    runbooks_dir: str = "data/runbooks"
    incidents_dir: str = "data/incidents"
    runtime_dir: str = "data/runtime"
    topology_file: str = "config/topology.yaml"


class SimBaselines(BaseModel):
    cpu_pct: float = 22.0
    mem_pct: float = 45.0
    temp_c: float = 38.0
    if_errors: float = 0.0
    bgp_peers_total: int = 4


class SimulatorCfg(BaseModel):
    tick_seconds: float = 1.0
    time_compression: float = 30.0
    jitter: float = 0.04
    baselines: SimBaselines = Field(default_factory=SimBaselines)


class IngestionCfg(BaseModel):
    queue_maxsize: int = 10000
    batch_commit: int = 1


class ForecastCfg(BaseModel):
    window: int = 12
    horizon_s: int = 90
    cpu_warn_pct: float = 90.0
    min_slope: float = 1.5
    temp_warn_c: float = 75.0
    temp_min_slope: float = 0.1
    errors_warn: float = 100.0
    errors_min_slope: float = 1.0


class CalibrationCfg(BaseModel):
    # Two-anchor linear map of the IsolationForest raw score -> 0..100.
    low_pct: float = 50.0
    low_score: float = 8.0
    high_pct: float = 98.0
    high_score: float = 55.0
    # The operator score = max(per-feature operational severity, if_blend_weight *
    # IF score). Bounding the IF contribution prevents its score-saturation tail
    # from fabricating false CRITICALs, while still surfacing subtle multivariate
    # anomalies as elevated scores.
    if_blend_weight: float = 0.6


class DetectionCfg(BaseModel):
    contamination: float = 0.02
    n_estimators: int = 200
    warning_score: int = 60
    critical_score: int = 85
    correlation_window_s: int = 60
    calibration: CalibrationCfg = Field(default_factory=CalibrationCfg)
    forecast: ForecastCfg = Field(default_factory=ForecastCfg)
    # Operational scales for discrete safety-critical indicators that are ~0 in
    # normal data (zero empirical variance). A single BGP-peer / link loss is a
    # major event, so we measure it against a small operational spread rather than
    # the (degenerate) noise std. feature -> std used by the scaler.
    indicator_scales: dict[str, float] = Field(
        default_factory=lambda: {"bgp_down": 0.1, "link_down": 0.1}
    )
    # Per-feature operational severity thresholds [warn, crit]. Below warn => 0;
    # warn..crit maps to 60..85 (WARNING band); at/above crit maps to 85..100
    # (CRITICAL band). The overall feature severity is the max across features.
    feature_severity: dict[str, list[float]] = Field(
        default_factory=lambda: {
            "cpu_pct": [85.0, 130.0],          # ramp stays WARNING; forecast leads the demo
            "mem_pct": [85.0, 100.0],
            "temp_c": [70.0, 90.0],
            "if_errors": [50.0, 500.0],
            "bgp_down": [1.0, 2.0],            # 1 peer lost = WARNING, 2+ = CRITICAL
            "link_down": [1.0, 2.0],
            "throughput_deficit": [150.0, 400.0],
        }
    )


class BlastCfg(BaseModel):
    w_service_criticality: float = 0.55
    w_service_count: float = 0.20
    w_node_criticality: float = 0.25
    eta_base_seconds: int = 30


class TopologyCfg(BaseModel):
    blast: BlastCfg = Field(default_factory=BlastCfg)


class EmbeddingCfg(BaseModel):
    backend: str = "hashing"
    dim: int = 384


class IndexCfg(BaseModel):
    backend: str = "auto"


class RagCfg(BaseModel):
    chunk_size: int = 700
    chunk_overlap: int = 120
    top_k: int = 5
    embedding: EmbeddingCfg = Field(default_factory=EmbeddingCfg)
    index: IndexCfg = Field(default_factory=IndexCfg)


class LlmCfg(BaseModel):
    model_config = {"protected_namespaces": ()}  # allow field name "model_path"

    mock: bool = True
    model_path: str = "data/models/qwen2.5-3b-instruct-q4_k_m.gguf"
    fallback_model_path: str = "data/models/qwen2.5-3b-instruct-q4_k_m.gguf"
    n_ctx: int = 4096
    n_gpu_layers: int = 0
    n_threads: int = 0
    temperature: float = 0.2
    max_tokens: int = 768
    stream: bool = True
    json_retries: int = 1


class JwtCfg(BaseModel):
    issuer: str = "neuralink-copilot"
    ttl_seconds: int = 3600


class SecurityCfg(BaseModel):
    master_key_file: str = "data/runtime/master.key"
    db_file: str = "data/runtime/neuralink.db"
    audit_file: str = "data/runtime/audit.log"
    faiss_file: str = "data/runtime/rag.index.enc"
    jwt: JwtCfg = Field(default_factory=JwtCfg)
    roles: list[str] = Field(default_factory=lambda: ["admin", "operator", "read-only"])


class ApiCfg(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8077


class WebCfg(BaseModel):
    host: str = "127.0.0.1"
    port: int = 5000


class AuditCfg(BaseModel):
    actor_default: str = "ops_user_01"
    role_default: str = "operator"


class Settings(BaseModel):
    env: str = "demo"
    seed: int = 42
    paths: Paths = Field(default_factory=Paths)
    simulator: SimulatorCfg = Field(default_factory=SimulatorCfg)
    ingestion: IngestionCfg = Field(default_factory=IngestionCfg)
    detection: DetectionCfg = Field(default_factory=DetectionCfg)
    topology: TopologyCfg = Field(default_factory=TopologyCfg)
    rag: RagCfg = Field(default_factory=RagCfg)
    llm: LlmCfg = Field(default_factory=LlmCfg)
    security: SecurityCfg = Field(default_factory=SecurityCfg)
    api: ApiCfg = Field(default_factory=ApiCfg)
    web: WebCfg = Field(default_factory=WebCfg)
    audit: AuditCfg = Field(default_factory=AuditCfg)

    # ---- path helpers (always absolute, project-root anchored) ---- #
    def _abs(self, rel: str) -> Path:
        p = Path(rel)
        return p if p.is_absolute() else (PROJECT_ROOT / p)

    @property
    def root(self) -> Path:
        return PROJECT_ROOT

    @property
    def runtime_dir(self) -> Path:
        return self._abs(self.paths.runtime_dir)

    @property
    def models_dir(self) -> Path:
        return self._abs(self.paths.models_dir)

    @property
    def runbooks_dir(self) -> Path:
        return self._abs(self.paths.runbooks_dir)

    @property
    def incidents_dir(self) -> Path:
        return self._abs(self.paths.incidents_dir)

    @property
    def topology_file(self) -> Path:
        return self._abs(self.paths.topology_file)

    @property
    def db_path(self) -> Path:
        return self._abs(self.security.db_file)

    @property
    def audit_path(self) -> Path:
        return self._abs(self.security.audit_file)

    @property
    def faiss_path(self) -> Path:
        return self._abs(self.security.faiss_file)

    @property
    def master_key_path(self) -> Path:
        return self._abs(self.security.master_key_file)

    @property
    def llm_model_path(self) -> Path:
        return self._abs(self.llm.model_path)

    def ensure_runtime_dirs(self) -> None:
        for d in (self.runtime_dir, self.models_dir, self.runbooks_dir, self.incidents_dir):
            d.mkdir(parents=True, exist_ok=True)


def _apply_env_overrides(data: dict) -> dict:
    """Layer a handful of env overrides onto the YAML dict (README §10: .env)."""
    llm = data.setdefault("llm", {})
    if os.environ.get("NEURALINK_LLM_MODEL_PATH"):
        llm["model_path"] = os.environ["NEURALINK_LLM_MODEL_PATH"]
    if os.environ.get("NEURALINK_ENV"):
        data["env"] = os.environ["NEURALINK_ENV"]
    # Explicit mock toggle for CI / demos without a GGUF present.
    mock_env = os.environ.get("NEURALINK_LLM_MOCK")
    if mock_env is not None:
        llm["mock"] = mock_env.strip().lower() in {"1", "true", "yes", "on"}
    return data


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load (and cache) settings from config/settings.yaml + env overrides."""
    _load_dotenv(PROJECT_ROOT)
    cfg_path = PROJECT_ROOT / "config" / "settings.yaml"
    data: dict = {}
    if cfg_path.exists():
        data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    data = _apply_env_overrides(data)
    return Settings(**data)


def reload_settings() -> Settings:
    """Clear the cache and reload (useful in tests)."""
    get_settings.cache_clear()
    return get_settings()
