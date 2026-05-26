"""Cursor adapter placeholder — generates .cursorrules additions.

Cursor uses .cursorrules and task-level hooks. This adapter generates
a .cursorrules snippet referencing Memory Center's recommended workflow.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from ..spec import load_hooks_config


def generate_cursor_rules(
    workspace: str,
    output_path: str | Path | None = None,
    hooks_config: Dict[str, Any] | None = None,
) -> Path:
    """Generate .cursorrules additions for Memory Center integration.

    Returns the path to the generated .cursorrules file.
    """
    if hooks_config is None:
        hooks_config = load_hooks_config(workspace)

    ws_path = Path(workspace).expanduser().resolve()
    ws_root = ws_path.parent.parent

    if output_path is None:
        output_path = ws_root / ".cursorrules"
    output_path = Path(output_path).expanduser().resolve()

    hooks_spec = hooks_config.get("hooks", {})

    active_hooks = []
    for event_name, spec in hooks_spec.items():
        mode = spec.get("mode", "soft")
        if mode == "off":
            continue
        facade = spec.get("facade", "")
        active_hooks.append(f"- {event_name}: {facade} (mode={mode})")

    hook_list = "\n".join(active_hooks)

    content = f"""# Memory Center Integration (Cursor)
#
# This workspace uses Memory Center as project memory service.
# Hook lifecycle mapping:
{hook_list}
#
# Before editing code: call mc_analyze for impact and rules check.
# After session ends: call mc_close to sync and record experience.
# Use mc_start to begin any coding task with workspace context.

<!-- memory-center:start -->
{hook_list}
<!-- memory-center:end -->
"""

    # Append to existing .cursorrules if it has a managed block
    if output_path.exists():
        existing = output_path.read_text(encoding="utf-8")
        if "<!-- memory-center:start -->" in existing:
            start = existing.index("<!-- memory-center:start -->")
            end = existing.index("<!-- memory-center:end -->") + len("<!-- memory-center:end -->")
            output_path.write_text(existing[:start] + content + existing[end:], encoding="utf-8")
        else:
            output_path.write_text(existing.rstrip() + "\n\n" + content, encoding="utf-8")
    else:
        output_path.write_text(content, encoding="utf-8")

    return output_path