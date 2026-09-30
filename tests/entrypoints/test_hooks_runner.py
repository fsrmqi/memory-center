"""Tests for hook runner — parameter resolution, mode enforcement, facade dispatch."""
from pathlib import Path

from memory_center.hooks.runner import run_hook
from memory_center.hooks.runner import _get_workspace_file
from memory_center.hooks.spec import session_id_file


def _setup_workspace(tmp_path: Path) -> str:
    from tests.fixtures import setup_demo_workspace
    return str(setup_demo_workspace(tmp_path))

def test_run_hook_session_start_soft_mode(tmp_path: Path):
    ws = _setup_workspace(tmp_path)
    result = run_hook(ws, "session_start", {"prompt": "fix Kafka consumer bug"})
    assert result["mode"] == "soft"
    assert result["exit_code"] == 0
    assert "session_id" in result.get("hook_result", {}).get("session", {})
    assert result["hook_result"]["workflow"] == "mc-start"


def test_run_hook_session_start_creates_session_id_file(tmp_path: Path):
    ws = _setup_workspace(tmp_path)
    # Clean up any existing session-id file
    session_id_file(_get_workspace_file(ws)).unlink(missing_ok=True)
    try:
        result = run_hook(ws, "session_start", {"prompt": "test task"})
        assert result["mode"] == "soft"
        assert session_id_file(_get_workspace_file(ws)).exists()
        session_id = session_id_file(_get_workspace_file(ws)).read_text(encoding="utf-8").strip()
        assert session_id  # session_id should not be empty
    finally:
        session_id_file(_get_workspace_file(ws)).unlink(missing_ok=True)


def test_run_hook_session_stop_soft_mode(tmp_path: Path):
    ws = _setup_workspace(tmp_path)
    # First start a session to create the session-id file
    start_result = run_hook(ws, "session_start", {"prompt": "test task"})
    assert start_result["mode"] == "soft"
    session_id = session_id_file(_get_workspace_file(ws)).read_text(encoding="utf-8").strip()
    assert session_id
    # Then stop it
    result = run_hook(ws, "session_stop", stdin_json=None)
    assert result["mode"] == "soft"
    assert result["exit_code"] == 0
    # Cleanup should have deleted the session-id file
    assert not session_id_file(_get_workspace_file(ws)).exists()


def test_run_hook_session_stop_no_session_id(tmp_path: Path):
    ws = _setup_workspace(tmp_path)
    session_id_file(_get_workspace_file(ws)).unlink(missing_ok=True)
    result = run_hook(ws, "session_stop", stdin_json=None)
    assert result["exit_code"] == 0
    assert "No session_id" in result["system_message"]


def test_run_hook_pre_edit_guard_mode_no_match(tmp_path: Path):
    ws = _setup_workspace(tmp_path)
    # A file that doesn't match the high-risk file patterns
    result = run_hook(ws, "pre_edit", {
        "tool_name": "Edit",
        "tool_input": {"file_path": "some/random/file.txt"}
    })
    # Doesn't match filter patterns, so it should skip
    assert result["exit_code"] == 0
    assert "does not match filter" in result["system_message"]


def test_run_hook_pre_edit_guard_mode_must_rule_blocks(tmp_path: Path):
    ws = _setup_workspace(tmp_path)
    # A file matching contract patterns — use the actual DTO path
    result = run_hook(ws, "pre_edit", {
        "tool_name": "Edit",
        "tool_input": {"file_path": "common-api/src/main/java/com/example/common/api/dto/ArticleDTO.java"}
    })
    assert result["mode"] == "guard"
    # Should block with exit_code=2 because CONTRACT-001 is must-severity
    assert result["exit_code"] == 2
    assert "BLOCKED" in result["system_message"]


def test_run_hook_pre_edit_guard_mode_non_must_passes(tmp_path: Path):
    ws = _setup_workspace(tmp_path)
    # Override hooks.yaml: remove file filter so ALL files get checked,
    # but use soft mode so it doesn't block
    import yaml

    from memory_center.hooks.spec import load_default_hooks
    config = load_default_hooks()
    config["hooks"]["pre_edit"]["mode"] = "soft"
    config["hooks"]["pre_edit"]["filter"]["file_patterns"] = []
    ws_hooks = Path(ws).expanduser().resolve().parent / "hooks.yaml"
    ws_hooks.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
    # A regular service file — may match LOG-001 (must-severity) but soft mode should not block
    result = run_hook(ws, "pre_edit", {
        "tool_name": "Edit",
        "tool_input": {"file_path": "article-service/src/main/java/com/example/article/service/ArticleService.java"}
    })
    assert result["mode"] == "soft"
    assert result["exit_code"] == 0


def test_run_hook_user_prompt_submit_suggest_mode(tmp_path: Path):
    ws = _setup_workspace(tmp_path)
    import yaml

    from memory_center.hooks.spec import load_default_hooks
    config = load_default_hooks()
    config["hooks"]["user_prompt_submit"]["enabled"] = True
    ws_hooks = Path(ws).expanduser().resolve().parent / "hooks.yaml"
    ws_hooks.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
    result = run_hook(ws, "user_prompt_submit", {"prompt": "how does Kafka consumer work?"})
    assert result["mode"] == "record_only"
    assert result["exit_code"] == 0
    assert result["hook_result"]["type"] == "recorded"
    from memory_center.core.storage.workspace import WorkspaceStore
    event = WorkspaceStore(ws).read_jsonl("host-interactions.jsonl", limit=1)[0]
    assert event["interaction"]["query"] == "how does Kafka consumer work?"


def test_run_hook_unknown_hook(tmp_path: Path):
    ws = _setup_workspace(tmp_path)
    result = run_hook(ws, "unknown_event", None)
    assert result["exit_code"] == 1
    assert "Unknown hook" in result["system_message"]


def test_run_hook_off_mode(tmp_path: Path):
    ws = _setup_workspace(tmp_path)
    import yaml

    from memory_center.hooks.spec import load_default_hooks
    config = load_default_hooks()
    config["hooks"]["session_start"]["mode"] = "off"
    ws_hooks = Path(ws).expanduser().resolve().parent / "hooks.yaml"
    ws_hooks.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
    result = run_hook(ws, "session_start", None)
    assert result["mode"] == "off"
    assert result["exit_code"] == 0
    assert "disabled" in result["system_message"]


def test_run_hook_enabled_false_disables_hook(tmp_path: Path):
    ws = _setup_workspace(tmp_path)
    import yaml

    from memory_center.hooks.spec import load_default_hooks
    config = load_default_hooks()
    config["hooks"]["session_start"]["enabled"] = False
    ws_hooks = Path(ws).expanduser().resolve().parent / "hooks.yaml"
    ws_hooks.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
    result = run_hook(ws, "session_start", {"prompt": "fix bug"})
    assert result["mode"] == "off"
    assert result["exit_code"] == 0
    assert "enabled=false" in result["system_message"]


def test_run_hook_pre_edit_tool_matcher_from_filter_skips_non_matching_tool(tmp_path: Path):
    ws = _setup_workspace(tmp_path)
    result = run_hook(ws, "pre_edit", {
        "tool_name": "Read",
        "tool_input": {"file_path": "common-api/src/main/java/com/example/common/api/dto/ArticleDTO.java"},
    })
    assert result["exit_code"] == 0
    assert "does not match tool_matcher" in result["system_message"]


def test_run_hook_mc_lookup_symbol_uses_compact_view(tmp_path: Path):
    ws = _setup_workspace(tmp_path)
    import yaml

    from memory_center.hooks.spec import load_default_hooks

    config = load_default_hooks()
    config["hooks"]["lookup_symbol"] = {
        "enabled": True,
        "facade": "mc_lookup",
        "mode": "soft",
        "params": {
            "intent": "ArticleFeignClient",
            "mode": "symbol",
            "view": "compact",
            "budget": "small",
            "limit": 5,
        },
    }
    ws_hooks = Path(ws).expanduser().resolve().parent / "hooks.yaml"
    ws_hooks.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")

    result = run_hook(ws, "lookup_symbol", None)
    payload = result["hook_result"]["result"]
    assert result["exit_code"] == 0
    assert payload["found"] is True
    assert payload["summary_lines"]
    assert "progressive" not in payload


def test_run_hook_mc_lookup_chain_uses_compact_view(tmp_path: Path):
    ws = _setup_workspace(tmp_path)
    import yaml

    from memory_center.hooks.spec import load_default_hooks

    config = load_default_hooks()
    config["hooks"]["lookup_chain"] = {
        "enabled": True,
        "facade": "mc_lookup",
        "mode": "soft",
        "params": {
            "intent": "ArticleFeignClient",
            "mode": "chain",
            "chain_direction": "callers",
            "view": "compact",
            "budget": "small",
            "limit": 5,
            "depth": 2,
        },
    }
    ws_hooks = Path(ws).expanduser().resolve().parent / "hooks.yaml"
    ws_hooks.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")

    result = run_hook(ws, "lookup_chain", None)
    payload = result["hook_result"]["result"]
    assert result["exit_code"] == 0
    assert payload["found"] is True
    assert payload["summary_lines"]
    assert "callers" not in payload


def test_param_resolution_event():
    from memory_center.hooks.runner import _resolve_param
    result = _resolve_param("event", {"prompt": "fix bug"}, "intent")
    assert result == "fix bug"


def test_param_resolution_tool_input_file():
    from memory_center.hooks.runner import _resolve_param
    result = _resolve_param("tool_input_file", {
        "tool_input": {"file_path": "/path/to/File.java"}
    }, "target")
    assert result == "/path/to/File.java"


def test_param_resolution_file(tmp_path: Path):
    from memory_center.hooks.runner import _resolve_param
    path = session_id_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("test-session-123", encoding="utf-8")
    try:
        assert _resolve_param("file", None, "session_id") == "test-session-123"
    finally:
        path.unlink(missing_ok=True)


def test_param_resolution_static():
    from memory_center.hooks.runner import _resolve_param
    result = _resolve_param("static", None, "intent", "hello world")
    assert result == "hello world"


def test_session_id_file_is_workspace_scoped_and_overridable(tmp_path: Path, monkeypatch):
    """交接文件必须按 workspace 隔离且可注入（此前是全局单例、写死 ~/.cache）。"""
    from memory_center.hooks.spec import session_id_file

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


def test_two_workspaces_do_not_clobber_each_others_session_id(tmp_path: Path, monkeypatch):
    """并行处理两个项目时，后启动的 session 不得覆盖前一个项目的交接文件。"""
    monkeypatch.delenv("MEMORY_CENTER_SESSION_ID_FILE", raising=False)
    (tmp_path / "home").mkdir()
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    ws_a = _setup_workspace(tmp_path / "a")
    ws_b = _setup_workspace(tmp_path / "b")

    assert run_hook(ws_a, "session_start", {"prompt": "task a"})["mode"] == "soft"
    path_a = session_id_file(_get_workspace_file(ws_a))
    session_a = path_a.read_text(encoding="utf-8").strip()
    assert session_a

    assert run_hook(ws_b, "session_start", {"prompt": "task b"})["mode"] == "soft"
    session_b = session_id_file(_get_workspace_file(ws_b)).read_text(encoding="utf-8").strip()

    assert session_b and session_b != session_a
    # 全局单例实现下这里会读到 B 的 session_id，A 的 Stop hook 会关掉 B 的 session
    assert path_a.read_text(encoding="utf-8").strip() == session_a
