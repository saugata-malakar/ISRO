"""Small shared utilities: deterministic RNG, JSON canonicalisation, time."""

from __future__ import annotations

import json
import random
from datetime import UTC, datetime
from typing import Any


def seeded_rng(seed: int, *salt: Any) -> random.Random:
    """Return an independent, deterministic RNG. ``salt`` lets callers derive
    per-device / per-scenario streams that are still fully reproducible."""
    h = hash((seed, *salt)) & 0xFFFFFFFF
    return random.Random(h)


def canonical_json(obj: Any) -> str:
    """Stable JSON string (sorted keys, no whitespace) for hashing/signing."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))
