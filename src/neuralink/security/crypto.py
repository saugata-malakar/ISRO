"""AES-256-GCM encryption at rest + local key management (README §1.3).

Keys never appear in source. The 32-byte master key is sourced, in order, from:
  1. ``NEURALINK_MASTER_KEY`` env (64 hex chars), else
  2. ``data/runtime/master.key`` (created with 0600 perms on first use).
Subkeys for the audit HMAC and JWT signing are derived with HKDF so a single
master secret protects everything, yet domains stay cryptographically separated.
"""

from __future__ import annotations

import os
import secrets
import stat
from functools import lru_cache
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from neuralink.config import get_settings

NONCE_BYTES = 12  # 96-bit nonce, recommended for GCM
KEY_BYTES = 32  # AES-256


def _generate_key_file(path: Path) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_bytes(KEY_BYTES)
    path.write_bytes(key)
    try:  # best-effort 0600 (POSIX); on Windows this is a no-op-ish narrowing
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    return key


@lru_cache(maxsize=1)
def get_master_key() -> bytes:
    """Return the 32-byte master key, sourcing or creating it locally."""
    env = os.environ.get("NEURALINK_MASTER_KEY")
    if env:
        raw = bytes.fromhex(env.strip())
        if len(raw) != KEY_BYTES:
            raise ValueError("NEURALINK_MASTER_KEY must be 64 hex chars (32 bytes).")
        return raw
    key_path = get_settings().master_key_path
    if key_path.exists():
        raw = key_path.read_bytes()
        if len(raw) != KEY_BYTES:
            raise ValueError(
                f"Master key at {key_path} is {len(raw)} bytes; expected {KEY_BYTES}."
            )
        return raw
    return _generate_key_file(key_path)


def _derive(label: bytes, master: bytes | None = None) -> bytes:
    """Derive a 32-byte subkey for a domain label via HKDF-SHA256."""
    hkdf = HKDF(algorithm=hashes.SHA256(), length=KEY_BYTES, salt=None, info=label)
    return hkdf.derive(master or get_master_key())


def audit_key() -> bytes:
    return _derive(b"neuralink-audit-hmac")


def jwt_secret() -> bytes:
    env = os.environ.get("NEURALINK_JWT_SECRET")
    if env:
        return env.encode("utf-8")
    return _derive(b"neuralink-jwt-signing")


def encrypt(plaintext: bytes, aad: bytes = b"") -> bytes:
    """Encrypt with AES-256-GCM. Output = nonce(12) || ciphertext+tag."""
    key = get_master_key()
    nonce = secrets.token_bytes(NONCE_BYTES)
    ct = AESGCM(key).encrypt(nonce, plaintext, aad)
    return nonce + ct


def decrypt(blob: bytes, aad: bytes = b"") -> bytes:
    """Inverse of :func:`encrypt`. Raises on tamper (GCM tag mismatch)."""
    if len(blob) < NONCE_BYTES + 16:
        raise ValueError("Ciphertext too short / corrupt.")
    key = get_master_key()
    nonce, ct = blob[:NONCE_BYTES], blob[NONCE_BYTES:]
    return AESGCM(key).decrypt(nonce, ct, aad)


def encrypt_str(text: str, aad: bytes = b"") -> bytes:
    return encrypt(text.encode("utf-8"), aad)


def decrypt_str(blob: bytes, aad: bytes = b"") -> str:
    return decrypt(blob, aad).decode("utf-8")
