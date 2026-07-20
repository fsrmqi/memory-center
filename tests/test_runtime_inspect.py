from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from memory_center.application.admin import build_admin_registry
from memory_center.cli.main import app
from memory_center.core.audit.inspect import inspect_runtime
from memory_center.core.audit.interactions import bind_active_session
from memory_center.core.audit.runtime import AUDIT_LOG_FILE
from memory_center.core.storage.workspace import WorkspaceStore
from memory_center.http.server import _route_request


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


def test_runtime_inspect_reports_missing_hook_scripts(tmp_path: Path, monkeypatch) -> None:
    from tests.fixtures import setup_demo_workspace

    workspace = setup_demo_workspace(tmp_path)
    monkeypatch.setattr("memory_center.core.audit.inspect.shutil.which", lambda _: "/private/tool/memory-center-mcp")
    monkeypatch.setattr("memory_center.core.audit.inspect._command_version", lambda _: "4.1.4")

    result = inspect_runtime(str(workspace))

    assert result["hooks"]["codex_missing_scripts"]
    assert any("generate-hooks --host codex" in item for item in result["recommended_actions"])


def test_runtime_inspect_has_cli_http_and_mcp_admin_entrypoints(tmp_path: Path, monkeypatch) -> None:
    from tests.fixtures import setup_demo_workspace

    workspace = setup_demo_workspace(tmp_path)
    monkeypatch.setattr("memory_center.core.audit.inspect.shutil.which", lambda _: "/private/tool/memory-center-mcp")
    monkeypatch.setattr("memory_center.core.audit.inspect._command_version", lambda _: "4.1.4")
    expected = set(inspect_runtime(str(workspace)).keys())

    cli = CliRunner().invoke(app, ["inspect", "--workspace", str(workspace)])
    assert cli.exit_code == 0
    assert set(json.loads(cli.stdout).keys()) == expected

    http = _route_request("/workspace/inspect", {"workspace": [str(workspace)]}, None)
    assert set(http.keys()) == expected

    registry = build_admin_registry(workspace_file=str(workspace), action="runtime_inspect")
    assert set(registry.dispatch("runtime_inspect").keys()) == expected
