"""Train the IsolationForest anomaly baseline on a normal-only run (M2).

Produces ``data/runtime/baseline.pkl``. Fully offline and deterministic (seeded).
Run once during offline-prep, or any time the topology/baselines change.
"""

from __future__ import annotations

from neuralink.config import get_settings
from neuralink.detection import baseline
from neuralink.simulator import Simulator


def main(ticks: int = 200) -> int:
    settings = get_settings()
    settings.ensure_runtime_dirs()

    # A healthy network with no fault scenario => normal-only training data.
    sim = Simulator(scenario=None, seed=settings.seed)
    events = list(sim.iter_events(ticks))
    print(f"[train] generated {len(events)} normal events "
          f"({ticks} ticks x {len(sim.topology.nodes)} devices)")

    model = baseline.train(events)
    path = baseline.save(model)

    # Quick sanity readout of the calibration.
    scores = model.score_matrix(baseline.features_matrix(events))
    print(f"[train] normal score distribution: "
          f"min={scores.min():.1f} median={sorted(scores)[len(scores)//2]:.1f} "
          f"p99={scores.max():.1f}")
    print(f"[train] saved baseline -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
