"""Unified error model for Memory Center.

Provides five canonical error types with consistent behavior across
CLI, HTTP, and MCP entry points:

- invalid_input  → HTTP 400
- not_found      → HTTP 404
- unavailable    → HTTP 503
- conflict       → HTTP 409
- internal_error → HTTP 500

Each error carries a safe message (sanitized via diagnostics.safe_reason),
optional diagnostics dict, and optional suggested_action string.

Usage:
    from memory_center.core.foundation.errors import NotFoundError, InvalidInputError

    raise NotFoundError("workspace not found", suggested_action="run reindex")
"""
from __future__ import annotations

import sqlite3
from typing import Any

from click import UsageError

from memory_center.core.foundation.redaction import safe_reason

# Canonical error types and their HTTP status codes
ERROR_TYPES: dict[str, int] = {
    "invalid_input": 400,
    "not_found": 404,
    "unavailable": 503,
    "conflict": 409,
    "internal_error": 500,
}


class MCError(Exception):
    """Base unified error for Memory Center.

    Parameters
    ----------
    error_type : str
        One of the canonical ERROR_TYPES keys.
    message : str
        Human-readable message; will be sanitized of paths, secrets, tracebacks.
    diagnostics : dict, optional
        Structured diagnostic info (e.g. from DIAG entry).
    suggested_action : str, optional
        Actionable next step for the caller (agent or human).
    """

    def __init__(
        self,
        error_type: str,
        message: str,
        diagnostics: dict[str, Any] | None = None,
        suggested_action: str = "",
    ) -> None:
        if error_type not in ERROR_TYPES:
            error_type = "internal_error"
        self.error_type: str = error_type
        self.message: str = safe_reason(reason=message)
        self.diagnostics: dict[str, Any] | None = diagnostics
        self.suggested_action: str = suggested_action
        super().__init__(self.message)

    @property
    def http_status(self) -> int:
        """HTTP status code for this error type."""
        return ERROR_TYPES.get(self.error_type, 500)

    @property
    def cli_exit_code(self) -> int:
        """CLI exit code. All errors exit 1."""
        return 1

    def to_http_response(self) -> tuple[int, dict[str, Any]]:
        """Convert to (status_code, response_body) for HTTP entry.

        Response body always has ``ok=False`` and ``error_type``.
        Optional fields (suggested_action, diagnostics) are included only
        when non-empty.
        """
        body: dict[str, Any] = {
            "ok": False,
            "error_type": self.error_type,
            "error": self.message,
        }
        if self.suggested_action:
            body["suggested_action"] = self.suggested_action
        if self.diagnostics is not None:
            body["diagnostics"] = self.diagnostics
        return self.http_status, body

    def to_mcp_dict(self) -> dict[str, Any]:
        """Convert to dict for MCP tool responses.

        Includes ``error=True``, ``error_type``, and ``message`` for
        agent-decision downstream. Optional fields included when non-empty.
        """
        result: dict[str, Any] = {
            "error": True,
            "error_type": self.error_type,
            "message": self.message,
        }
        if self.suggested_action:
            result["suggested_action"] = self.suggested_action
        if self.diagnostics is not None:
            result["diagnostics"] = self.diagnostics
        return result

    def to_cli_message(self) -> str:
        """Convert to human-readable string for CLI output.

        Format: ``[error_type] message`` with optional suggested action line.
        """
        parts = [f"[{self.error_type}] {self.message}"]
        if self.suggested_action:
            parts.append(f"Suggested: {self.suggested_action}")
        return "\n".join(parts)


# ---- Convenience subclasses ----

class InvalidInputError(MCError):
    """Bad or missing input parameters (HTTP 400)."""

    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__("invalid_input", message, **kwargs)


class NotFoundError(MCError):
    """Requested resource not found (HTTP 404)."""

    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__("not_found", message, **kwargs)


class UnavailableError(MCError):
    """Service or capability temporarily unavailable (HTTP 503)."""

    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__("unavailable", message, **kwargs)


class ConflictError(MCError):
    """Conflict with current state (HTTP 409)."""

    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__("conflict", message, **kwargs)


class InternalError(MCError):
    """Unexpected internal error (HTTP 500)."""

    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__("internal_error", message, **kwargs)


def normalize_exception(exc: Exception) -> MCError:
    """Convert existing exceptions to the public Memory Center error model."""
    if isinstance(exc, MCError):
        return exc
    if isinstance(exc, FileNotFoundError):
        return NotFoundError(str(exc), suggested_action="Check the workspace or resource path and retry.")
    if isinstance(exc, (ValueError, TypeError, UsageError)):
        return InvalidInputError(str(exc), suggested_action="Check the input parameters and retry.")
    if isinstance(exc, (sqlite3.OperationalError, TimeoutError, ConnectionError)):
        return UnavailableError(str(exc), suggested_action="Retry after checking backend availability.")
    return InternalError(str(exc), suggested_action="Check diagnostics or logs, then retry.")
