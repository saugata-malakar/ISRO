"""Local JWT auth + role-based access control (README §8 security).

Three roles (admin / operator / read-only) with a permission hierarchy. Tokens
are signed locally with HS256 using a key derived from the master secret — no
external identity provider, nothing leaves the box.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt

from neuralink.config import get_settings
from neuralink.security import crypto

# Coarse permissions per role.
ROLE_PERMISSIONS: dict[str, set[str]] = {
    "read-only": {"view"},
    "operator": {"view", "execute", "escalate"},
    "admin": {"view", "execute", "escalate", "manage"},
}


class AuthError(Exception):
    """Raised on invalid/expired tokens or insufficient privileges."""


def has_permission(role: str, action: str) -> bool:
    return action in ROLE_PERMISSIONS.get(role, set())


def issue_token(subject: str, role: str, ttl_seconds: int | None = None) -> str:
    if role not in ROLE_PERMISSIONS:
        raise AuthError(f"Unknown role '{role}'. Valid: {', '.join(ROLE_PERMISSIONS)}")
    cfg = get_settings().security.jwt
    ttl = ttl_seconds if ttl_seconds is not None else cfg.ttl_seconds
    now = datetime.now(UTC)
    claims = {
        "sub": subject,
        "role": role,
        "iss": cfg.issuer,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl)).timestamp()),
    }
    return jwt.encode(claims, crypto.jwt_secret(), algorithm="HS256")


def verify_token(token: str) -> dict:
    cfg = get_settings().security.jwt
    try:
        return jwt.decode(
            token, crypto.jwt_secret(), algorithms=["HS256"], issuer=cfg.issuer
        )
    except jwt.PyJWTError as exc:
        raise AuthError(f"Invalid token: {exc}") from exc


def require_permission(token: str, action: str) -> dict:
    """Verify a token and assert it grants ``action``. Returns the claims."""
    claims = verify_token(token)
    if not has_permission(claims.get("role", ""), action):
        raise AuthError(
            f"Role '{claims.get('role')}' lacks permission '{action}'."
        )
    return claims
