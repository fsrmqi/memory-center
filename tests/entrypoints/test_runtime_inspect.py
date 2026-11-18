from __future__ import annotations

import json
from pathlib import Path

import pytest

pass  # 4.x 入口已退役
from memory_center.core.audit.inspect import inspect_runtime
from memory_center.core.audit.interactions import bind_active_session
from memory_center.core.audit.runtime import AUDIT_LOG_FILE
from memory_center.core.storage.workspace import WorkspaceStore

pass  # 4.x 入口已退役


def test_runtime_inspect_is_path_free_and_reports_effective_state(tmp_path: Path, monkeypatch) -> None:
    from tests.fixtures import setup_demo_workspace

    workspace = setup_demo_workspace(tmp_path)
    monkeypatch.setattr("memory_center.core.audit.inspect.shutil.which", lambda _: "/private/tool/memory-center-mcp")
    monkeypatch.setattr("memory_center.core.audit.inspect._command_version", lambda _: "memory-center-mcp 4.1.4")
    bind_active_session(str(workspace), "thread-1", "session-1")

    result = inspect_runtime(str(workspace), thread_id="thread-1")
    rendered = json.dumps(result, ensure_ascii=False)

    assert result["workspace"]["root"] == "<workspace-root>"
    assert result["mcp"] == {
        "command": "memory-center-mcp",
        "available": True,
        "version": "memory-center-mcp 4.1.4",
        "version_source": "memory-center --version",
        "recommended_action": "use_current_mcp",
    }
    assert result["session"]["thread_session_bound"] is True
    assert result["history"]["retention"] == {"days": 30, "max_records": 100_000}
    assert result["ontology"]["assertions"]["active"] >= 0
    assert result["ontology"]["diagnostics"]["node_types"] == []
    assert result["ontology"]["diagnostics"]["edge_types"] == []
    assert str(tmp_path) not in rendered
    assert "session-1" not in rendered
    assert WorkspaceStore(workspace).read_jsonl(AUDIT_LOG_FILE, limit=10) == []


def test_runtime_inspect_does_not_recommend_removed_hook_commands(tmp_path: Path, monkeypatch) -> None:
    """5.0 已移除 hook 执行器：缺少 4.x 生成脚本不应再被当作待修问题。"""
    from tests.fixtures import setup_demo_workspace

    workspace = setup_demo_workspace(tmp_path)
    monkeypatch.setattr("memory_center.core.audit.inspect.shutil.which", lambda _: "/private/tool/memory-center-mcp")
    monkeypatch.setattr("memory_center.core.audit.inspect._command_version", lambda _: "4.1.4")

    result = inspect_runtime(str(workspace))

    # 事实仍然如实报告：4.x 的脚本确实不存在。
    assert result["hooks"]["codex_missing_scripts"]
    # 但不得再给出已被移除命令的修复建议。
    joined = " ".join(result["recommended_actions"])
    assert "generate-hooks" not in joined
    assert "run-hook" not in joined
    assert "setup-agent" not in joined


def test_runtime_inspect_flags_invalid_hooks_config(tmp_path: Path, monkeypatch) -> None:
    """非法 hooks.yaml 仍应给出可执行建议，因为它会被审计读取校验。"""
    from tests.fixtures import setup_demo_workspace

    workspace = setup_demo_workspace(tmp_path)
    hooks_file = Path(workspace).parent / "hooks.yaml"
    hooks_file.write_text("version: 999\nhooks: {}\n", encoding="utf-8")
    monkeypatch.setattr("memory_center.core.audit.inspect.shutil.which", lambda _: "/private/tool/memory-center-mcp")
    monkeypatch.setattr("memory_center.core.audit.inspect._command_version", lambda _: "4.1.4")

    result = inspect_runtime(str(workspace))

    assert result["hooks"]["config_valid"] is False
    assert any("hooks.yaml" in item for item in result["recommended_actions"])


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_runtime_inspect_has_cli_http_and_mcp_admin_entrypoints(tmp_path: Path, monkeypatch) -> None:
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")
