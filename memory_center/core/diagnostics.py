"""Unified diagnostics contract for Memory Center main-chain optional capabilities.

Provides:
- Standard status vocabulary (success, disabled, empty, unavailable, unknown)
- Safe reason sanitizer that strips file paths, secrets, and tracebacks
- Helper to build diagnostic entries consistently

Usage:
    from memory_center.core.diagnostics import diag_entry, safe_reason, DIAG

    # In a catch block:
    diagnostics["freshness"] = diag_entry(DIAG.UNAVAILABLE, exc)
"""

from __future__ import annotations

import re
from typing import Any


class DIAG:
    """Unified diagnostics status vocabulary."""
    SUCCESS = "success"
    DISABLED = "disabled"
    EMPTY = "empty"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"
    ACTIVE = "active"
    PARTIAL = "partial"

    _VALID = {SUCCESS, DISABLED, EMPTY, UNAVAILABLE, UNKNOWN, ACTIVE, PARTIAL}

    @classmethod
    def validate(cls, status: str) -> str:
        """Return *status* if valid, else UNKNOWN."""
        return status if status in cls._VALID else cls.UNKNOWN


# Patterns that indicate sensitive content in error messages
_SENSITIVE_PATTERNS = [
    re.compile(r"/Users/\S+"),           # macOS home paths
    re.compile(r"/home/\S+"),            # Linux home paths
    re.compile(r"C:\\\\Users\\\\\S+"),   # Windows paths
    re.compile(r"[A-Z]:\\\\\S+"),        # Windows drive paths
    re.compile(r"(?i)(token|secret|password|api[_-]?key)\s*[=:]\s*\S+"),
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),  # OpenAI-style keys
    re.compile(r"(?i)traceback \(most recent call last\)"),  # full tracebacks
]


def safe_reason(exc: Exception | None = None, reason: str | None = None) -> str:
    """Produce a safe reason string from an exception or literal.

    Strips:
    - Absolute file paths (macOS, Linux, Windows)
    - Secrets / tokens / API keys
    - Full tracebacks
    - Excessively long messages (>200 chars)

    Returns a short, safe reason string.
    """
    if exc is not None:
        raw = type(exc).__name__
    elif reason is not None:
        raw = reason
    else:
        return ""

    for pat in _SENSITIVE_PATTERNS:
        raw = pat.sub("[REDACTED]", raw)

    # Truncate long messages
    if len(raw) > 200:
        raw = raw[:197] + "..."

    return raw


def diag_entry(
    status: str,
    exc: Exception | None = None,
    reason: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Build a diagnostic entry with ``status`` and safe ``reason``.

    >>> from memory_center.core.diagnostics import diag_entry, DIAG
    >>> diag_entry(DIAG.SUCCESS)
    {'status': 'success'}
    >>> diag_entry(DIAG.UNAVAILABLE, reason="freshness module not installed")
    {'status': 'unavailable', 'reason': 'freshness module not installed'}
    """
    entry: dict[str, Any] = {"status": DIAG.validate(status)}
    safe = safe_reason(exc=exc, reason=reason)
    if safe:
        entry["reason"] = safe
    entry.update(extra)
    return entry
