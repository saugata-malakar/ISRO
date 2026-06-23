"""Egress guard (README §1.1, §8 security).

Two layers:
  1. **Runtime**: :func:`install_egress_guard` monkeypatches the socket layer to
     raise on any outbound connection to a non-local host (localhost is allowed
     so the bundled API/UI work). Defence-in-depth against accidental egress.
  2. **Static**: :func:`verify_airgap` scans the codebase for forbidden network
     symbols/URLs/CDNs outside the single allowed download script. Backs
     `make verify-airgap`.
"""

from __future__ import annotations

import re
import socket
from pathlib import Path

from neuralink.config import PROJECT_ROOT

# --------------------------------------------------------------------------- #
# 1) Runtime egress guard
# --------------------------------------------------------------------------- #
_ALLOWED_HOSTS = {"127.0.0.1", "::1", "localhost", "0.0.0.0", ""}
_original_connect = socket.socket.connect
_installed = False


class EgressViolation(RuntimeError):
    """Raised when code attempts an outbound network connection."""


def _host_of(address) -> str:
    if isinstance(address, tuple):
        return str(address[0])
    return str(address)


def _guarded_connect(self, address):  # type: ignore[no-untyped-def]
    host = _host_of(address)
    if host not in _ALLOWED_HOSTS:
        raise EgressViolation(
            f"Blocked outbound connection to {host!r}. The runtime is air-gapped "
            "(README §1.1): no network egress is permitted."
        )
    return _original_connect(self, address)


def install_egress_guard() -> None:
    global _installed
    socket.socket.connect = _guarded_connect  # type: ignore[method-assign]
    _installed = True


def remove_egress_guard() -> None:
    global _installed
    socket.socket.connect = _original_connect  # type: ignore[method-assign]
    _installed = False


def is_installed() -> bool:
    return _installed


# --------------------------------------------------------------------------- #
# 2) Static air-gap scan
# --------------------------------------------------------------------------- #
# Patterns that indicate runtime network use. The download script and this guard
# file are the only allowed places to reference such symbols.
_FORBIDDEN = [
    (re.compile(r"https?://(?!127\.0\.0\.1|localhost)", re.I), "external URL"),
    (re.compile(r"\bimport\s+requests\b"), "requests import"),
    (re.compile(r"\brequests\.(get|post|put|delete|patch|head|request|Session)\b"), "requests call"),
    (re.compile(r"\b(import\s+urllib|urllib\.request|urlopen)\b"), "urllib use"),
    (re.compile(r"\bboto3\b"), "boto3 (AWS SDK)"),
    (re.compile(r"\b(import\s+openai|openai\.)\b"), "openai SDK"),
    (re.compile(r"(cdnjs|unpkg|jsdelivr|gstatic|fonts\.googleapis|ajax\.googleapis)", re.I), "CDN/remote asset"),
]

_SCAN_DIRS = ["src", "scripts", "config"]
_SCAN_EXTS = {".py", ".html", ".js", ".css", ".yaml", ".yml"}
_ALLOWED_FILES = {
    "scripts/download_models.sh",  # the only file allowed to fetch (offline-prep)
    "src/neuralink/security/egress_guard.py",  # this scanner defines the patterns
}


def _iter_scan_files(root: Path):
    for sub in _SCAN_DIRS:
        base = root / sub
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if not p.is_file() or p.suffix.lower() not in _SCAN_EXTS:
                continue
            if "__pycache__" in p.parts or ".venv" in p.parts:
                continue
            rel = p.relative_to(root).as_posix()
            if rel in _ALLOWED_FILES:
                continue
            yield p, rel


def verify_airgap(root: Path | None = None) -> tuple[bool, list[str]]:
    """Scan the codebase for forbidden network references.

    Returns ``(ok, findings)`` where each finding is ``"<file>:<line>: <why> -> <text>"``.
    """
    root = root or PROJECT_ROOT
    findings: list[str] = []
    for path, rel in _iter_scan_files(root):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for pattern, why in _FORBIDDEN:
                if pattern.search(line):
                    findings.append(f"{rel}:{lineno}: {why} -> {line.strip()[:100]}")
    return (len(findings) == 0), findings
