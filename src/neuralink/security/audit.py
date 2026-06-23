"""Append-only, tamper-evident audit log (README §1.4, §7.4).

Each entry is hash-chained:
    entry_hash = HMAC_SHA256(audit_key, canonical(seq, ts, actor, role, action,
                                                   payload, prev_hash))
and the whole line is then encrypted at rest with AES-256-GCM (README §1.3).
:meth:`AuditLog.verify` re-derives the entire chain and detects ANY edit:
a flipped ciphertext byte fails GCM auth; an altered field fails the HMAC; a
broken link or reordering fails the prev_hash check.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from neuralink.config import get_settings
from neuralink.schemas import AuditEntry
from neuralink.security import crypto
from neuralink.util import canonical_json, utcnow_iso

GENESIS_HASH = "0" * 64


def _entry_hash(entry: AuditEntry, key: bytes) -> str:
    body = canonical_json(
        {
            "seq": entry.seq,
            "ts": entry.ts,
            "actor": entry.actor,
            "role": entry.role,
            "action": entry.action,
            "payload": entry.payload,
            "prev_hash": entry.prev_hash,
        }
    )
    return hmac.new(key, body.encode("utf-8"), sha256).hexdigest()


@dataclass
class VerifyResult:
    ok: bool
    count: int
    reason: str = ""
    bad_seq: int | None = None


class AuditLog:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else get_settings().audit_path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._key = crypto.audit_key()

    # ------------------------------------------------------------------ #
    def _read_lines(self) -> list[bytes]:
        if not self.path.exists():
            return []
        return [ln for ln in self.path.read_bytes().splitlines() if ln.strip()]

    def _last_hash(self) -> tuple[int, str]:
        """Return (next_seq, prev_hash) without full verification."""
        lines = self._read_lines()
        if not lines:
            return 0, GENESIS_HASH
        last = self._decrypt_line(lines[-1])
        return last.seq + 1, last.entry_hash

    def _decrypt_line(self, line: bytes) -> AuditEntry:
        raw = crypto.decrypt(bytes.fromhex(line.decode("ascii")), aad=b"audit")
        return AuditEntry.model_validate_json(raw)

    # ------------------------------------------------------------------ #
    def append(self, actor: str, role: str, action: str, payload: dict | None = None) -> AuditEntry:
        seq, prev = self._last_hash()
        entry = AuditEntry(
            seq=seq,
            ts=utcnow_iso(),
            actor=actor,
            role=role,
            action=action,
            payload=payload or {},
            prev_hash=prev,
        )
        entry.entry_hash = _entry_hash(entry, self._key)
        blob = crypto.encrypt(entry.model_dump_json().encode("utf-8"), aad=b"audit")
        with self.path.open("ab") as fh:
            fh.write(blob.hex().encode("ascii") + b"\n")
        return entry

    def entries(self) -> list[AuditEntry]:
        return [self._decrypt_line(ln) for ln in self._read_lines()]

    def tail(self, n: int = 10) -> list[AuditEntry]:
        return self.entries()[-n:]

    def count(self) -> int:
        return len(self._read_lines())

    # ------------------------------------------------------------------ #
    def verify(self) -> VerifyResult:
        """Recompute the full chain; detect any tamper."""
        lines = self._read_lines()
        prev = GENESIS_HASH
        for i, line in enumerate(lines):
            try:
                entry = self._decrypt_line(line)
            except Exception as exc:  # noqa: BLE001 — GCM auth / corruption
                return VerifyResult(False, len(lines), f"decrypt failed: {exc}", i)
            if entry.seq != i:
                return VerifyResult(False, len(lines), f"seq out of order (got {entry.seq})", i)
            if entry.prev_hash != prev:
                return VerifyResult(False, len(lines), "prev_hash mismatch (chain broken)", entry.seq)
            recomputed = _entry_hash(entry, self._key)
            if not hmac.compare_digest(recomputed, entry.entry_hash):
                return VerifyResult(False, len(lines), "entry_hash mismatch (content altered)", entry.seq)
            prev = entry.entry_hash
        return VerifyResult(True, len(lines))
