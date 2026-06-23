"""Build a NetworkX DiGraph (+ LSP/service maps) from the topology (README §8)."""

from __future__ import annotations

import networkx as nx

from neuralink.schemas import LSP, Service, Topology
from neuralink.simulator.topology_loader import load_topology


class NetworkGraph:
    """Wraps the MPLS topology as a directed graph plus LSP/service indexes."""

    def __init__(self, topology: Topology | None = None) -> None:
        self.topology = topology or load_topology()
        self.g = nx.DiGraph()
        self._build()
        self._lsp: dict[str, LSP] = {lsp.id: lsp for lsp in self.topology.lsps}
        self._svc: dict[str, Service] = {s.id: s for s in self.topology.services}

    def _build(self) -> None:
        for n in self.topology.nodes:
            self.g.add_node(
                n.id, type=n.type, ip=n.ip, criticality=n.criticality, asn=n.asn
            )
        for e in self.topology.edges:
            self.g.add_edge(
                e.src, e.dst, link_type=e.link_type,
                bandwidth_mbps=e.bandwidth_mbps, criticality=e.criticality,
            )

    # ------------------------------------------------------------------ #
    def node_criticality(self, node_id: str) -> float:
        return float(self.g.nodes.get(node_id, {}).get("criticality", 0.5))

    def lsps_through_node(self, node_id: str) -> list[str]:
        """LSPs whose path traverses the given node."""
        return [lsp.id for lsp in self.topology.lsps if node_id in lsp.path]

    def lsps_through_edge(self, src: str, dst: str) -> list[str]:
        """LSPs whose path traverses the directed (or reverse) edge."""
        out = []
        for lsp in self.topology.lsps:
            p = lsp.path
            pairs = list(zip(p, p[1:], strict=False))
            if (src, dst) in pairs or (dst, src) in pairs:
                out.append(lsp.id)
        return out

    def services_for_lsps(self, lsp_ids: list[str]) -> list[Service]:
        """Services that depend on any of the given LSPs (deduped, stable order)."""
        seen: dict[str, Service] = {}
        for lid in lsp_ids:
            lsp = self._lsp.get(lid)
            if not lsp:
                continue
            for sid in lsp.services:
                svc = self._svc.get(sid)
                if svc and sid not in seen:
                    seen[sid] = svc
        return list(seen.values())

    def downstream_nodes(self, origin: str) -> list[str]:
        """Nodes reachable downstream of origin (blast spread), excluding origin."""
        if origin not in self.g:
            return []
        return sorted(nx.descendants(self.g, origin))

    def total_services(self) -> int:
        return len(self.topology.services)
