"""Unified diagnostics contract for Memory Center main-chain optional capabilities.

Provides:
- Standard status vocabulary (success, disabled, empty, unavailable, unknown)
- Safe reason sanitizer that strips file paths, secrets, and tracebacks
- Helper to build diagnostic entries consistently

Usage:
    from memory_center.core.observability.diagnostics import diag_entry, safe_reason, DIAG

    # In a catch block:
    diagnostics["freshness"] = diag_entry(DIAG.UNAVAILABLE, exc)
"""

from __future__ import annotations

from typing import Any

from memory_center.core.foundation.redaction import safe_reason


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


# ``safe_reason`` 的真实实现位于 core.foundation.redaction（基础层纯文本能力）。
# 此处保留同名导入作为对外契约：observability 曾是该函数的主入口，
# 既有调用点与测试仍按 ``memory_center.core.observability.diagnostics.safe_reason`` 引用。


def diag_entry(
    status: str,
    exc: Exception | None = None,
    reason: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Build a diagnostic entry with ``status`` and safe ``reason``.

    >>> from memory_center.core.observability.diagnostics import diag_entry, DIAG
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
