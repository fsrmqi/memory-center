"""B-04 real entrypoint error-boundary tests."""
from __future__ import annotations

import asyncio

import pytest
from click import UsageError
from typer.testing import CliRunner

from memory_center.cli.main import app
from memory_center.core.errors import MCError, normalize_exception
from memory_center.http.server import _http_error_response
from memory_center.mcp.server import _mcp_error_boundary


@pytest.mark.parametrize(
    ("exc", "error_type", "status"),
    [
        (ValueError("bad input"), "invalid_input", 400),
        (UsageError("bad command"), "invalid_input", 400),
        (FileNotFoundError("missing workspace"), "not_found", 404),
        (TimeoutError("backend timeout"), "unavailable", 503),
        (RuntimeError("unexpected"), "internal_error", 500),
    ],
)
def test_http_error_boundary_maps_existing_exceptions(exc: Exception, error_type: str, status: int):
    actual_status, body = _http_error_response(exc)
    assert actual_status == status
    assert body["ok"] is False
    assert body["error_type"] == error_type
    assert body["error"]


def test_normalize_exception_preserves_mcerror():
    error = MCError("conflict", "already exists")
    assert normalize_exception(error) is error


def test_mcp_sync_tool_error_boundary_returns_structured_error():
    def failing_tool():
        raise ValueError("bad mode")

    result = _mcp_error_boundary(failing_tool)()
    assert result["error"] is True
    assert result["error_type"] == "invalid_input"
    assert result["message"] == "bad mode"


def test_mcp_async_tool_error_boundary_returns_structured_error():
    async def failing_tool():
        raise FileNotFoundError("missing workspace")

    result = asyncio.run(_mcp_error_boundary(failing_tool)())
    assert result["error"] is True
    assert result["error_type"] == "not_found"


def test_http_error_boundary_sanitizes_internal_details():
    _, body = _http_error_response(RuntimeError("failed at /Users/private/workspace.yaml"))
    assert "/Users/private" not in body["error"]
    assert "[REDACTED]" in body["error"]


def test_cli_command_still_propagates_to_installed_boundary():
    result = CliRunner().invoke(app, ["status", "--workspace", "/nonexistent/workspace.yaml"])
    assert result.exit_code != 0
    assert isinstance(result.exception, FileNotFoundError)


def test_installed_cli_boundary_prints_unified_error_without_traceback(monkeypatch, capsys):
    import memory_center.cli.main as cli

    def failing_app(**_kwargs):
        raise FileNotFoundError("missing workspace")

    monkeypatch.setattr(cli, "app", failing_app)
    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    captured = capsys.readouterr()
    assert exc_info.value.code == 1
    assert "[not_found] missing workspace" in captured.err
    assert "Traceback" not in captured.err
