"""Tests for hook runner — parameter resolution, mode enforcement, facade dispatch."""
from pathlib import Path

from memory_center.hooks.spec import _SESSION_ID_FILE
from memory_center.hooks.runner import run_hook


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
    _SESSION_ID_FILE.unlink(missing_ok=True)
    try:
        result = run_hook(ws, "session_start", {"prompt": "test task"})
        assert _SESSION_ID_FILE.exists()
        session_id = _SESSION_ID_FILE.read_text(encoding="utf-8").strip()
        assert session_id  # session_id should not be empty
    finally:
        _SESSION_ID_FILE.unlink(missing_ok=True)


def test_run_hook_session_stop_soft_mode(tmp_path: Path):
    ws = _setup_workspace(tmp_path)
    # First start a session to create the session-id file
    start_result = run_hook(ws, "session_start", {"prompt": "test task"})
    session_id = _SESSION_ID_FILE.read_text(encoding="utf-8").strip()
    assert session_id
    # Then stop it
    result = run_hook(ws, "session_stop", stdin_json=None)
    assert result["mode"] == "soft"
    assert result["exit_code"] == 0
    # Cleanup should have deleted the session-id file
    assert not _SESSION_ID_FILE.exists()


def test_run_hook_session_stop_no_session_id(tmp_path: Path):
    ws = _setup_workspace(tmp_path)
    _SESSION_ID_FILE.unlink(missing_ok=True)
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
    # Default has user_prompt_submit disabled — enable it for this test
    import yaml
    from memory_center.hooks.spec import load_default_hooks
    config = load_default_hooks()
    config["hooks"]["user_prompt_submit"]["enabled"] = True
    ws_hooks = Path(ws).expanduser().resolve().parent / "hooks.yaml"
    ws_hooks.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
    result = run_hook(ws, "user_prompt_submit", {"prompt": "how does Kafka consumer work?"})
    assert result["mode"] == "suggest"
    assert result["exit_code"] == 0
    assert result["hook_result"]["type"] == "prompt"
    assert "how does Kafka consumer work?" in result["hook_result"]["prompt"]


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
    _SESSION_ID_FILE.unlink(missing_ok=True)
    _SESSION_ID_FILE.write_text("test-session-123", encoding="utf-8")
    result = _resolve_param("file", None, "session_id")
    assert result == "test-session-123"
    _SESSION_ID_FILE.unlink(missing_ok=True)


def test_param_resolution_static():
    from memory_center.hooks.runner import _resolve_param
    result = _resolve_param("static", None, "intent", "hello world")
    assert result == "hello world"
