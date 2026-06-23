"""Blast-radius computation (README §8 topology).

From a failing origin (node or edge), find the LSPs that traverse it, then the
services that depend on those LSPs, then a weighted 0-100 impact score:

    score = 100 * ( w_sc * mean(service criticalities)
                  + w_cnt * (1 - 1/(1 + n_services))     # saturating count term
                  + w_nc * origin node criticality )

and a per-service degradation ETA = eta_base * (2 - criticality), so the most
critical services degrade soonest. Weights live in config (no magic numbers).
"""

from __future__ import annotations

from neuralink.config import BlastCfg, get_settings
from neuralink.schemas import AffectedService, BlastRadius
from neuralink.topology.graph import NetworkGraph


def _eta_for(criticality: float, base: float) -> float:
    return round(base * (2.0 - criticality), 1)


def compute_blast_radius(
    origin: str,
    graph: NetworkGraph | None = None,
    edge_dst: str | None = None,
    cfg: BlastCfg | None = None,
) -> BlastRadius:
    """Compute the blast radius for a failing node (or edge if ``edge_dst`` set)."""
    graph = graph or NetworkGraph()
    cfg = cfg or get_settings().topology.blast

    if edge_dst is not None:
        affected_lsps = graph.lsps_through_edge(origin, edge_dst)
        node_crit = max(graph.node_criticality(origin), graph.node_criticality(edge_dst))
    else:
        affected_lsps = graph.lsps_through_node(origin)
        node_crit = graph.node_criticality(origin)

    services = graph.services_for_lsps(affected_lsps)
    affected_services = [
        AffectedService(
            id=s.id,
            criticality=s.criticality,
            eta_seconds=_eta_for(s.criticality, cfg.eta_base_seconds),
        )
        for s in services
    ]
    # Most critical / soonest first.
    affected_services.sort(key=lambda s: (-s.criticality, s.eta_seconds))

    n = len(services)
    crit_score = (sum(s.criticality for s in services) / n) if n else 0.0
    count_score = 1.0 - 1.0 / (1.0 + n) if n else 0.0
    raw = (
        cfg.w_service_criticality * crit_score
        + cfg.w_service_count * count_score
        + cfg.w_node_criticality * node_crit
    )
    score = int(round(min(1.0, raw) * 100))

    affected_nodes = graph.downstream_nodes(origin)
    return BlastRadius(
        origin=origin if edge_dst is None else f"{origin}->{edge_dst}",
        affected_lsps=affected_lsps,
        affected_services=affected_services,
        affected_nodes=affected_nodes,
        score=score,
    )
