"""Integration test that runs the full demo scenario end-to-end."""

from __future__ import annotations

from scripts import run_demo


def test_demo_integration():
    """Verify that run_demo runs successfully end-to-end."""
    # Run the demo in fast mode to verify no exceptions are raised and it exit code is 0.
    result = run_demo.main(scenario="cpu_starvation", seed=42, fast=True)
    assert result == 0
