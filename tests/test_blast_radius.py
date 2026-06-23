"""Blast-radius computation (README §3 M3 DoD)."""

from __future__ import annotations

from neuralink.topology.blast_radius import compute_blast_radius
from neuralink.topology.graph import NetworkGraph


def test_pe_router_03_failure_flags_expected_lsps_and_service():
    br = compute_blast_radius("PE-Router-03")
    assert set(br.affected_lsps) == {"LSP-12", "LSP-15"}
    service_ids = {s.id for s in br.affected_services}
    assert "Ground-Station-Link-B" in service_ids
    assert {"Telemetry-Feed-C", "VoIP-Trunk-A"} <= service_ids


def test_pe_router_03_score_matches_demo():
    # The headline demo quotes blast radius 87/100 for PE-Router-03.
    assert compute_blast_radius("PE-Router-03").score == 87


def test_most_critical_service_first_and_has_eta():
    br = compute_blast_radius("PE-Router-03")
    assert br.affected_services[0].id == "Ground-Station-Link-B"
    assert br.affected_services[0].criticality == 1.0
    assert all(s.eta_seconds > 0 for s in br.affected_services)


def test_edge_fiber_cut():
    br = compute_blast_radius("P-Router-02", edge_dst="PE-Router-03")
    assert "LSP-12" in br.affected_lsps
    assert br.origin == "P-Router-02->PE-Router-03"


def test_leaf_node_small_blast():
    graph = NetworkGraph()
    br = compute_blast_radius("CE-Router-07", graph=graph)
    # CE-Router-07 only terminates LSP-15 / Telemetry-Feed-C.
    assert "LSP-15" in br.affected_lsps
    assert br.score < compute_blast_radius("PE-Router-03", graph=graph).score
