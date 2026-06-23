"""Tamper-evident audit chain (README §1.4, §3 M6 DoD)."""

from __future__ import annotations

from neuralink.security.audit import AuditLog


def _populate(path):
    log = AuditLog(path=path)
    log.append("ops_user_01", "operator", "ALERT_RAISED", {"score": 95})
    log.append("ops_user_01", "operator", "COPILOT_INFERENCE", {"confidence": 0.85})
    log.append("ops_user_01", "operator", "EXECUTE_STEP", {"cmd": "clear ip bgp 10.0.0.2 soft"})
    return log


def test_append_and_verify(audit_path):
    log = _populate(audit_path)
    res = log.verify()
    assert res.ok and res.count == 3


def test_chain_links(audit_path):
    log = _populate(audit_path)
    entries = log.entries()
    assert entries[0].prev_hash == "0" * 64
    for prev, cur in zip(entries, entries[1:], strict=False):
        assert cur.prev_hash == prev.entry_hash
        assert cur.seq == prev.seq + 1


def test_tamper_ciphertext_detected(audit_path):
    _populate(audit_path)
    lines = audit_path.read_bytes().splitlines()
    mid = bytearray(lines[1])
    mid[20] = ord("0") if chr(mid[20]) != "0" else ord("1")  # corrupt a hex char
    lines[1] = bytes(mid)
    audit_path.write_bytes(b"\n".join(lines) + b"\n")
    res = AuditLog(path=audit_path).verify()
    assert not res.ok
    assert res.bad_seq == 1


def test_truncation_detected(audit_path):
    _populate(audit_path)
    lines = audit_path.read_bytes().splitlines()
    # Drop the last entry -> count changes but remaining chain still verifies;
    # removing a MIDDLE entry breaks the prev_hash link.
    lines = [lines[0], lines[2]]
    audit_path.write_bytes(b"\n".join(lines) + b"\n")
    res = AuditLog(path=audit_path).verify()
    assert not res.ok
