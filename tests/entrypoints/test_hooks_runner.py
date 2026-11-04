"""Tests for hook runner — parameter resolution, mode enforcement, facade dispatch."""

from pathlib import Path

import pytest

pass  # 4.x 入口已退役


def _setup_workspace(tmp_path: Path) -> str:
    from tests.fixtures import setup_demo_workspace
    return str(setup_demo_workspace(tmp_path))

@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_run_hook_session_start_soft_mode(tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_run_hook_session_start_creates_session_id_file(tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_run_hook_session_stop_soft_mode(tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_run_hook_session_stop_no_session_id(tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_run_hook_pre_edit_guard_mode_no_match(tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_run_hook_pre_edit_guard_mode_must_rule_blocks(tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_run_hook_pre_edit_guard_mode_non_must_passes(tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_run_hook_user_prompt_submit_suggest_mode(tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_run_hook_unknown_hook(tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_run_hook_off_mode(tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_run_hook_enabled_false_disables_hook(tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_run_hook_pre_edit_tool_matcher_from_filter_skips_non_matching_tool(tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_run_hook_mc_lookup_symbol_uses_compact_view(tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_run_hook_mc_lookup_chain_uses_compact_view(tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_param_resolution_event():
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_param_resolution_tool_input_file():
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_param_resolution_file(tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_param_resolution_static():
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


def test_session_id_file_is_workspace_scoped_and_overridable(tmp_path: Path, monkeypatch):
    """交接文件必须按 workspace 隔离且可注入（此前是全局单例、写死 ~/.cache）。"""
    from memory_center.core.audit.hook_config import session_id_file

    # 先关掉 conftest 的注入，验证默认的按 workspace 隔离逻辑
    monkeypatch.delenv("MEMORY_CENTER_SESSION_ID_FILE", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    ws_a = tmp_path / "a" / ".memory-center" / "workspace.yaml"
    ws_b = tmp_path / "b" / ".memory-center" / "workspace.yaml"
    scoped_a = session_id_file(ws_a)
    assert scoped_a != session_id_file(ws_b)
    assert scoped_a == session_id_file(ws_a)
    assert scoped_a.is_relative_to(tmp_path / "home" / ".cache" / "memory-center" / "sessions")
    # 未提供 workspace 时保留旧的全局路径（向后兼容）
    assert session_id_file() == Path.home() / ".cache" / "memory-center" / "session-id"

    override = tmp_path / "custom" / "session-id"
    monkeypatch.setenv("MEMORY_CENTER_SESSION_ID_FILE", str(override))
    assert session_id_file(ws_a) == override
    assert session_id_file() == override


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_two_workspaces_do_not_clobber_each_others_session_id(tmp_path: Path, monkeypatch):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")
