"""AES-256-GCM crypto + key derivation (README §1.3)."""

from __future__ import annotations

import pytest
from cryptography.exceptions import InvalidTag

from neuralink.security import crypto


def test_roundtrip():
    blob = crypto.encrypt(b"top secret telemetry")
    assert blob != b"top secret telemetry"
    assert crypto.decrypt(blob) == b"top secret telemetry"


def test_roundtrip_with_aad():
    blob = crypto.encrypt_str("hello", aad=b"row-42")
    assert crypto.decrypt_str(blob, aad=b"row-42") == "hello"


def test_aad_mismatch_fails():
    blob = crypto.encrypt(b"x", aad=b"row-1")
    with pytest.raises(InvalidTag):
        crypto.decrypt(blob, aad=b"row-2")


def test_tamper_detected():
    blob = bytearray(crypto.encrypt(b"immutable"))
    blob[-1] ^= 0x01  # flip a ciphertext/tag bit
    with pytest.raises(InvalidTag):
        crypto.decrypt(bytes(blob))


def test_nonce_is_random():
    a = crypto.encrypt(b"same")
    b = crypto.encrypt(b"same")
    assert a != b  # random nonce per record


def test_subkeys_distinct_and_deterministic():
    assert crypto.audit_key() == crypto.audit_key()
    assert crypto.audit_key() != crypto.jwt_secret()
    assert len(crypto.audit_key()) == crypto.KEY_BYTES
