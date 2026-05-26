"""Claude Code adapter — generate settings.json hooks from hooks.yaml.

Maps hooks.yaml events to Claude Code hook names and generates the
settings.local.json 'hooks' section. This replaces fragile inline
shell commands with a single clean `memory-center run-hook` call.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from ..spec import load_hooks_config

_EVENT_TO_CLAUDE_HOOK = {
    "session_start": "SessionStart",
    "pre_edit": "PreToolUse",
    "session_stop": "Stop",
    "user_prompt_submit": "UserPromptSubmit",
}


def generate_claude_code_hooks(
    workspace: str,
    hooks_config: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Generate Claude Code settings.json hooks section from hooks.yaml.

    Returns the 'hooks' dict ready to merge into settings.local.json.
    """
    if hooks_config is None:
        hooks_config = load_hooks_config(workspace)

    hooks_spec = hooks_config.get("hooks", {})
    result: Dict[str, Any] = {}

    for event_name, spec in hooks_spec.items():
        claude_hook_name = _EVENT_TO_CLAUDE_HOOK.get(event_name)
        if not claude_hook_name:
            continue  # unknown event, skip

        mode = spec.get("mode", "soft")
        if mode == "off":
            continue  # disabled hooks are not generated

        timeout = spec.get("timeout", 15)
        is_async = spec.get("async", True)
        filter_spec = spec.get("filter", {})
        matcher = filter_spec.get("tool_matcher", "")

        hook_entry: Dict[str, Any] = {
            "matcher": matcher,
            "hooks": [],
        }

        if mode == "suggest":
            # Suggest mode: inject a prompt, no shell command
            prompt_template = spec.get("prompt_template", "")
            hook_entry["hooks"].append({
                "type": "prompt",
                "prompt": prompt_template,
                "timeout": timeout,
                "statusMessage": f"Memory Center: {event_name}",
            })
        else:
            # Soft/guard mode: run a shell command via run-hook
            command = f"memory-center run-hook --workspace {workspace} --hook {event_name}"
            hook_entry["hooks"].append({
                "type": "command",
                "command": command,
                "timeout": timeout,
                "statusMessage": f"Memory Center: {event_name}",
                "async": is_async,
            })

        result[claude_hook_name] = [hook_entry]

    return result


def write_claude_code_settings(
    workspace: str,
    output_path: str | Path | None = None,
    hooks_config: Dict[str, Any] | None = None,
) -> Path:
    """Generate and write Claude Code settings.local.json with hooks.

    Merges generated hooks into an existing settings.local.json,
    preserving any non-hook configuration (permissions, env, etc.).

    Default output path: .claude/settings.local.json relative to workspace root.
    """
    # Resolve workspace root from workspace.yaml path
    ws_path = Path(workspace).expanduser().resolve()
    ws_root = ws_path.parent.parent  # .memory-center/workspace.yaml → workspace root

    if output_path is None:
        output_path = ws_root / ".claude" / "settings.local.json"
    output_path = Path(output_path).expanduser().resolve()

    # Load existing settings if present
    existing: Dict[str, Any] = {}
    if output_path.exists():
        try:
            existing = json.loads(output_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            existing = {}

    # Generate hooks section
    generated_hooks = generate_claude_code_hooks(workspace, hooks_config)

    # Merge: replace only the 'hooks' key, preserve everything else
    existing["hooks"] = generated_hooks

    # Write back
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(existing, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return output_path