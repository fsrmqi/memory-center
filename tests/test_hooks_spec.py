"""Tests for hooks.yaml spec module — schema, validation, loading, defaults."""
from pathlib import Path

from memory_center.core.store import WorkspaceStore
from memory_center.hooks.spec import (
    load_default_hooks,
    load_hooks_config,
    validate_hooks_config,
    ensure_default_hooks,
)


def _setup_workspace(tmp_path: Path) -> str:
    from tests.fixtures import setup_demo_workspace
    return str(setup_demo_workspace(tmp_path))

def test_load_default_hooks_has_4_hooks():
    config = load_default_hooks()
    hooks = config.get("hooks", {})
    assert "session_start" in hooks
    assert "pre_edit" in hooks
    assert "session_stop" in hooks
    assert "user_prompt_submit" in hooks


def test_default_hooks_version_is_1():
    config = load_default_hooks()
    assert config.get("version") == "1.0"


def test_default_hooks_modes():
    config = load_default_hooks()
    assert config["hooks"]["session_start"]["mode"] == "soft"
    assert config["hooks"]["pre_edit"]["mode"] == "guard"
    assert config["hooks"]["session_stop"]["mode"] == "soft"
    assert config["hooks"]["user_prompt_submit"]["mode"] == "suggest"


def test_default_user_prompt_submit_disabled():
    config = load_default_hooks()
    assert config["hooks"]["user_prompt_submit"]["enabled"] is False


def test_default_hooks_facades():
    config = load_default_hooks()
    assert config["hooks"]["session_start"]["facade"] == "mc_start"
    assert config["hooks"]["pre_edit"]["facade"] == "mc_analyze"
    assert config["hooks"]["session_stop"]["facade"] == "mc_close"
    assert config["hooks"]["user_prompt_submit"]["facade"] == "mc_start"


def test_validate_default_hooks_is_valid():
    config = load_default_hooks()
    errors = validate_hooks_config(config)
    assert errors == []


def test_validate_empty_hooks_returns_error():
    errors = validate_hooks_config({"hooks": {}})
    assert len(errors) > 0


def test_validate_invalid_mode():
    errors = validate_hooks_config({
        "hooks": {"test_hook": {"facade": "mc_start", "mode": "invalid_mode"}}
    })
    assert any("invalid mode" in e for e in errors)


def test_validate_invalid_facade():
    errors = validate_hooks_config({
        "hooks": {"test_hook": {"facade": "invalid_facade", "mode": "soft"}}
    })
    assert any("invalid facade" in e for e in errors)


def test_validate_invalid_from():
    errors = validate_hooks_config({
        "hooks": {"test_hook": {"facade": "mc_start", "mode": "soft", "params": {"intent_from": "invalid_from"}}}
    })
    assert any("invalid *_from" in e for e in errors)


def test_load_hooks_config_workspace_override(tmp_path: Path):
    ws = _setup_workspace(tmp_path)
    store = WorkspaceStore(ws)
    # Write a custom hooks.yaml to workspace
    custom_hooks = {"version": "1.0", "hooks": {
        "session_start": {"facade": "mc_start", "mode": "off", "params": {"intent_from": "static"}}
    }}
    hooks_file = store.base_dir / "hooks.yaml"
    import yaml
    hooks_file.write_text(yaml.safe_dump(custom_hooks, allow_unicode=True, sort_keys=False), encoding="utf-8")
    config = load_hooks_config(ws)
    assert config["hooks"]["session_start"]["mode"] == "off"


def test_load_hooks_config_fallback_to_default(tmp_path: Path):
    ws = _setup_workspace(tmp_path)
    # No hooks.yaml in workspace — should fall back to shipped default
    hooks_file = Path(ws).expanduser().resolve().parent / "hooks.yaml"
    if hooks_file.exists():
        hooks_file.unlink()
    config = load_hooks_config(ws)
    assert config["hooks"]["session_start"]["mode"] == "soft"


def test_ensure_default_hooks_creates_file(tmp_path: Path):
    ws = _setup_workspace(tmp_path)
    store = WorkspaceStore(ws)
    hooks_file = store.base_dir / "hooks.yaml"
    if hooks_file.exists():
        hooks_file.unlink()
    result = ensure_default_hooks(store)
    assert result.exists()
    import yaml
    data = yaml.safe_load(result.read_text(encoding="utf-8"))
    assert data["version"] == "1.0"


def test_ensure_default_hooks_preserves_existing(tmp_path: Path):
    ws = _setup_workspace(tmp_path)
    store = WorkspaceStore(ws)
    hooks_file = store.base_dir / "hooks.yaml"
    # Write a custom config
    custom = {"version": "1.0", "hooks": {"session_start": {"facade": "mc_start", "mode": "off"}}}
    import yaml
    hooks_file.write_text(yaml.safe_dump(custom, allow_unicode=True, sort_keys=False), encoding="utf-8")
    result = ensure_default_hooks(store)
    data = yaml.safe_load(result.read_text(encoding="utf-8"))
    # Should preserve the existing custom config (mode=off), not overwrite with default
    assert data["hooks"]["session_start"]["mode"] == "off"
