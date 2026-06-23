"""Air-gap static scan (README §1.1, §3 M6 DoD)."""

from __future__ import annotations

from neuralink.security.egress_guard import (
    EgressViolation,
    install_egress_guard,
    remove_egress_guard,
    verify_airgap,
)


def test_codebase_is_clean():
    ok, findings = verify_airgap()
    assert ok, "forbidden network references found:\n" + "\n".join(findings)


def test_scan_detects_planted_violation(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "bad.py").write_text("import requests\nrequests.get('https://evil.example')\n")
    ok, findings = verify_airgap(root=tmp_path)
    assert not ok
    assert any("bad.py" in f for f in findings)


def test_runtime_guard_blocks_outbound():
    import socket

    install_egress_guard()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            with __import__("pytest").raises(EgressViolation):
                s.connect(("93.184.216.34", 80))  # example.com — must be blocked
        finally:
            s.close()
    finally:
        remove_egress_guard()


def test_runtime_guard_allows_localhost():
    import socket

    install_egress_guard()
    try:
        # Connecting to a closed local port raises ConnectionRefused, NOT
        # EgressViolation — i.e. localhost is permitted through the guard.
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.2)
        try:
            s.connect(("127.0.0.1", 9))
        except EgressViolation as exc:
            raise AssertionError("localhost should be allowed") from exc
        except OSError:
            pass  # refused/timeout is fine
        finally:
            s.close()
    finally:
        remove_egress_guard()
