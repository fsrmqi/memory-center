"""B-04 real entrypoint error-boundary tests."""
from __future__ import annotations

import pytest
from click import UsageError

pass  # 4.x 入口已退役
from memory_center.core.foundation.errors import MCError, normalize_exception

pass  # 4.x 入口已退役
pass  # 4.x 入口已退役


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
@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_http_error_boundary_maps_existing_exceptions(exc: Exception, error_type: str, status: int):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


def test_normalize_exception_preserves_mcerror():
    error = MCError("conflict", "already exists")
    assert normalize_exception(error) is error


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_mcp_sync_tool_error_boundary_returns_structured_error():
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_mcp_async_tool_error_boundary_returns_structured_error():
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_http_error_boundary_sanitizes_internal_details():
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_cli_command_still_propagates_to_installed_boundary():
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_installed_cli_boundary_prints_unified_error_without_traceback(monkeypatch, capsys):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")
