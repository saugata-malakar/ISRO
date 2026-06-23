"""Parse config/topology.yaml into typed objects (README §7.2)."""

from __future__ import annotations

from pathlib import Path

import yaml

from neuralink.config import get_settings
from neuralink.schemas import Topology


def load_topology(path: str | Path | None = None) -> Topology:
    """Load the simulated MPLS network. Fails loudly if the file is missing."""
    p = Path(path) if path else get_settings().topology_file
    if not p.exists():
        raise FileNotFoundError(
            f"Topology file not found: {p}\n"
            "Expected config/topology.yaml (see README §7.2). Air-gapped build "
            "does not fetch topology — provide it locally."
        )
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return Topology(**data)
