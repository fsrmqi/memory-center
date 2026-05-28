"""Codex adapter — generates executable shell wrapper scripts.

Codex's hook API uses lifecycle scripts. This adapter generates
executable shell wrapper scripts that call `memory-center run-hook`,
reading stdin JSON context from the host.
"""
from __future__ import annotations

import shlex
import stat
from pathlib import Path
from typing import Any, Dict

from ..spec import load_hooks_config

_EVENT_TO_SCRIPT_NAME = {
    "session_start": "mc_session_start.sh",
    "pre_edit": "mc_pre_edit.sh",
    "session_stop": "mc_session_stop.sh",
    "user_prompt_submit": "mc_prompt_submit.sh",
}


def generate_codex_scripts(
    workspace: str,
    output_dir: str | Path | None = None,
    hooks_config: Dict[str, Any] | None = None,
) -> list[Path]:
    """Generate shell wrapper scripts for Codex lifecycle events.

    Each script calls `memory-center run-hook --workspace <path> --hook <event>`.
    Returns list of generated script paths.
    """
    if hooks_config is None:
        hooks_config = load_hooks_config(workspace)

    ws_path = Path(workspace).expanduser().resolve()
    ws_root = ws_path.parent.parent

    if output_dir is None:
        output_dir = ws_root / ".codex-hooks"
    output_dir = Path(output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    hooks_spec = hooks_config.get("hooks", {})
    generated: list[Path] = []

    for event_name, spec in hooks_spec.items():
        mode = spec.get("mode", "soft")
        if mode == "off":
            continue

        script_name = _EVENT_TO_SCRIPT_NAME.get(event_name, f"mc_{event_name}.sh")
        script_path = output_dir / script_name

        if mode == "suggest":
            # Suggest mode: output the prompt template via safe heredoc
            prompt = spec.get("prompt_template", "")
            content = f"""#!/bin/bash
# Memory Center hook: {event_name} (suggest mode)
# This hook injects a prompt into the Codex session.
cat <<'__MC_PROMPT_EOF__'
{prompt}
__MC_PROMPT_EOF__
"""
        else:
            content = f"""#!/bin/bash
# Memory Center hook: {event_name} ({mode} mode)
# Reads stdin JSON and dispatches to memory-center run-hook.
memory-center run-hook --workspace {shlex.quote(workspace)} --hook {event_name}
"""

        script_path.write_text(content, encoding="utf-8")
        script_path.chmod(script_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        generated.append(script_path)

    return generated