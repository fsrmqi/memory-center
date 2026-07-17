"""hooks.yaml schema, validation, loading, and default generation.

Follows the same pattern as core/rules.py (DEFAULT_* constants + ensure_default_* + load function).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ..core.storage.workspace import WorkspaceStore

_VALID_MODES = ("soft", "guard", "suggest", "off")
_VALID_FACADES = (
    "mc_start", "mc_lookup", "mc_analyze", "mc_sync",
    "mc_resume", "mc_handoff", "mc_close", "mc_admin",
)
_VALID_PARAM_FROM = ("event", "tool_input_file", "file", "static")
_HOOK_EVENT_NAMES = ("session_start", "pre_edit", "session_stop", "user_prompt_submit")
_SESSION_ID_FILE = Path.home() / ".cache" / "memory-center" / "session-id"

DEFAULT_HOOKS = {
    "version": "1.0",
    "hooks": {
        "session_start": {
            "enabled": True,
            "facade": "mc_start",
            "mode": "soft",
            "params": {
                "intent_from": "event",
                "auto_sync_mode": "balanced",
                "budget": "small",
                "view": "compact",
            },
            "timeout": 30,
            "async": True,
        },
        "pre_edit": {
            "enabled": True,
            "facade": "mc_analyze",
            "mode": "guard",
            "params": {
                "target_from": "tool_input_file",
                "depth": "quick",
                "change_type": "general",
            },
            "filter": {
                "tool_matcher": "Edit|Write",
                "file_patterns": [
                    "**/common-api/**/*.java",
                    "**/*Feign*.java",
                    "**/*Message.java",
                    "**/*DTO.java",
                ],
            },
            "timeout": 15,
            "async": True,
        },
        "session_stop": {
            "enabled": True,
            "facade": "mc_close",
            "mode": "soft",
            "params": {
                "session_id_from": "file",
                "outcome": "session ended",
            },
            "cleanup": ["delete_session_id_file"],
            "timeout": 15,
            "async": True,
        },
        "user_prompt_submit": {
            "enabled": True,
            "facade": "mc_start",
            "mode": "suggest",
            "record_only": True,
            "prompt_template": (
                "The user submitted a prompt. Always treat this hook as advisory only: "
                "do not block, stop, or deny the operation solely because the prompt is short, "
                "ambiguous, or open-ended.\n\n"
                "If the prompt is a continuation phrase such as: 下一步, 继续, 接着, 继续这个, 往下做, 继续处理, continue, next step, keep going — "
                "respond with: {\"decision\":\"allow\",\"reason\":\"Continuation request detected — prefer mc_resume to continue the current task/session context; if no active context exists, then mc_start may be used.\"}.\n\n"
                "If the prompt clearly involves modifying code, understanding architecture, tracing call chains, analyzing impact, debugging, or Spring Cloud/backend engineering work — "
                "respond with: {\"decision\":\"allow\",\"reason\":\"Coding task detected — recommend calling mc_start first to load workspace context.\"}.\n\n"
                "If the prompt contains Class#method and asks for 全链路, 到底层, 最底层, full chain, or trace to sink — "
                "recommend mc_lookup(mode=\"walkthrough\") or mc_lookup(mode=\"auto\") and follow the returned summary_lines / continuations. "
                "When walkthrough returns absolute_file_path, read that path directly; do not use find, grep -l, rg --files, or IDE search to locate the same Controller/ServiceImpl.\n\n"
                "For simple questions or non-code topics — respond with: "
                "{\"decision\":\"allow\",\"reason\":\"Not a coding task, no Memory Center context needed.\"}.\n\n"
                "The prompt content: $ARGUMENTS"
            ),
            "timeout": 10,
        },
    },
}


def _default_hooks_yaml_path() -> Path:
    return Path(__file__).parent / "default_hooks.yaml"


def load_default_hooks() -> dict[str, Any]:
    """Load the shipped default hooks.yaml."""
    path = _default_hooks_yaml_path()
    if path.exists():
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return DEFAULT_HOOKS


def load_hooks_config(workspace_file: str | Path) -> dict[str, Any]:
    """Load hooks.yaml from workspace, falling back to shipped default.

    Workspace hooks.yaml lives at .memory-center/hooks.yaml alongside workspace.yaml.
    """
    ws_dir = Path(workspace_file).expanduser().resolve().parent
    ws_hooks = ws_dir / "hooks.yaml"
    if ws_hooks.exists():
        return yaml.safe_load(ws_hooks.read_text(encoding="utf-8")) or {}
    return load_default_hooks()


def validate_hooks_config(config: dict[str, Any]) -> list[str]:
    """Validate a hooks.yaml config. Returns list of error strings (empty = valid)."""
    errors: list[str] = []
    version = config.get("version")
    if version and version != "1.0":
        errors.append(f"Unsupported hooks.yaml version: {version}")

    hooks = config.get("hooks", {})
    if not hooks:
        errors.append("hooks.yaml has no hooks defined")
        return errors

    for name, spec in hooks.items():
        if not isinstance(spec, dict):
            errors.append(f"Hook '{name}' is not a dict")
            continue
        facade = spec.get("facade", "")
        if facade and facade not in _VALID_FACADES:
            errors.append(f"Hook '{name}' has invalid facade: {facade}")
        mode = spec.get("mode", "")
        if mode and mode not in _VALID_MODES:
            errors.append(f"Hook '{name}' has invalid mode: {mode}")
        params = spec.get("params", {})
        if isinstance(params, dict):
            for key, val in params.items():
                if key.endswith("_from") and val not in _VALID_PARAM_FROM:
                    errors.append(f"Hook '{name}' param '{key}' has invalid *_from: {val}")

    return errors


def ensure_default_hooks(store: WorkspaceStore) -> Path:
    """Write hooks.yaml into workspace if it does not already exist.

    Follows the same pattern as ensure_default_rules in core/rules.py.
    """
    hooks_file = store.base_dir / "hooks.yaml"
    if not hooks_file.exists():
        default = load_default_hooks()
        hooks_file.write_text(
            yaml.safe_dump(default, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
    return hooks_file
