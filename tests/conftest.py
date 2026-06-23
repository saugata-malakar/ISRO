"""Shared test fixtures. Pins a deterministic master key so crypto/audit/auth
tests are hermetic and never depend on (or create) an on-disk key file.
"""

from __future__ import annotations

import os

# Must be set before the crypto module reads/caches the key.
os.environ.setdefault("NEURALINK_MASTER_KEY", "11" * 32)
os.environ.setdefault("NEURALINK_LLM_MOCK", "true")

import pytest  # noqa: E402

from neuralink.config import reload_settings  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_settings():
    reload_settings()
    yield


@pytest.fixture
def audit_path(tmp_path):
    return tmp_path / "audit.log"
