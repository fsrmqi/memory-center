"""Tests for host adapters — Claude Code, Codex, Cursor."""
from pathlib import Path
import shutil
import json
import pytest

from memory_center.core.config import load_workspace_config
from memory_center.core.indexer import reindex_workspace
from memory_center.core.store import WorkspaceStore
from memory_center.hooks.spec import load_hooks_config, ensure_default_hooks
from memory_center.hooks.adapters.claude_code import (
    generate_claude_code_hooks,
    write_claude_code_settings,
)
from memory_center.hooks.adapters.codex import generate_codex_scripts
from memory_center.hooks.adapters.cursor import generate_cursor_rules


def _setup_workspace(tmp_path: Path) -> str:
    source = Path("examples/spring-cloud-demo")
    target = tmp_path / "demo"
    shutil.copytree(source, target)
    workspace = target / ".memory-center" / "workspace.yaml"
    lines = workspace.read_text(encoding="utf-8").splitlines()
    lines = [f"root: {target.as_posix()}" if line.startswith("root:") else line for line in lines]
    workspace.write_text("\n".join(lines) + "\n", encoding="utf-8")
    config = load_workspace_config(workspace)
    store = WorkspaceStore(workspace)
    reindex_workspace(config, store)
    ensure_default_hooks(store)
    return str(workspace)


def test_claude_code_adapter_generates_4_hook_types(tmp_path: Path):
    ws = _setup_workspace(tmp_path)
    config = load_hooks_config(ws)
    hooks = generate_claude_code_hooks(ws, config)
    assert "SessionStart" in hooks
    assert "PreToolUse" in hooks
    assert "Stop" in hooks
    assert "UserPromptSubmit" in hooks


def test_claude_code_adapter_session_start_is_command(tmp_path: Path):
    ws = _setup_workspace(tmp_path)
    config = load_hooks_config(ws)
    hooks = generate_claude_code_hooks(ws, config)
    entry = hooks["SessionStart"][0]
    assert entry["matcher"] == ""
    hook = entry["hooks"][0]
    assert hook["type"] == "command"
    assert "run-hook" in hook["command"]
    assert "--hook session_start" in hook["command"]


def test_claude_code_adapter_pre_edit_has_matcher(tmp_path: Path):
    ws = _setup_workspace(tmp_path)
    config = load_hooks_config(ws)
    hooks = generate_claude_code_hooks(ws, config)
    entry = hooks["PreToolUse"][0]
    assert entry["matcher"] == "Edit|Write"
    hook = entry["hooks"][0]
    assert hook["type"] == "command"
    assert "run-hook" in hook["command"]


def test_claude_code_adapter_user_prompt_is_prompt_type(tmp_path: Path):
    ws = _setup_workspace(tmp_path)
    config = load_hooks_config(ws)
    hooks = generate_claude_code_hooks(ws, config)
    entry = hooks["UserPromptSubmit"][0]
    assert entry["matcher"] == ""
    hook = entry["hooks"][0]
    assert hook["type"] == "prompt"
    assert "$ARGUMENTS" in hook["prompt"] or "Determine" in hook["prompt"]


def test_claude_code_adapter_skips_off_mode(tmp_path: Path):
    ws = _setup_workspace(tmp_path)
    config = load_hooks_config(ws)
    config["hooks"]["session_start"]["mode"] = "off"
    hooks = generate_claude_code_hooks(ws, config)
    # Off-mode hooks should not appear in generated output
    assert "SessionStart" not in hooks


def test_claude_code_write_settings(tmp_path: Path):
    ws = _setup_workspace(tmp_path)
    output_path = tmp_path / "settings.local.json"
    result_path = write_claude_code_settings(ws, output_path=output_path)
    assert result_path.exists()
    data = json.loads(result_path.read_text(encoding="utf-8"))
    assert "hooks" in data
    assert "SessionStart" in data["hooks"]


def test_claude_code_write_settings_preserves_existing(tmp_path: Path):
    ws = _setup_workspace(tmp_path)
    output_path = tmp_path / "settings.local.json"
    # Write existing settings with permissions
    existing = {"permissions": {"allow": ["Bash(git *)"]}, "hooks": {}}
    output_path.write_text(json.dumps(existing), encoding="utf-8")
    result_path = write_claude_code_settings(ws, output_path=output_path)
    data = json.loads(result_path.read_text(encoding="utf-8"))
    # Permissions should still be present
    assert "permissions" in data
    assert data["permissions"]["allow"] == ["Bash(git *)"]
    # Hooks should be replaced
    assert "SessionStart" in data["hooks"]


def test_codex_adapter_generates_scripts(tmp_path: Path):
    ws = _setup_workspace(tmp_path)
    output_dir = tmp_path / "codex-hooks"
    scripts = generate_codex_scripts(ws, output_dir=output_dir)
    assert len(scripts) > 0
    # Check at least one script exists and contains run-hook
    for script in scripts:
        content = script.read_text(encoding="utf-8")
        assert "memory-center" in content or "suggest" in content


def test_cursor_adapter_generates_rules(tmp_path: Path):
    ws = _setup_workspace(tmp_path)
    output_path = tmp_path / ".cursorrules"
    rules_path = generate_cursor_rules(ws, output_path=output_path)
    assert rules_path.exists()
    content = rules_path.read_text(encoding="utf-8")
    assert "Memory Center" in content