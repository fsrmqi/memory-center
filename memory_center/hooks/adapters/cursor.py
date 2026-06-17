"""Cursor adapter — generates .cursorrules with hook lifecycle instructions.

Cursor uses .cursorrules for project-level instructions. This adapter
generates a .cursorrules snippet that instructs Cursor to use Memory Center's
MCP facade tools at the right lifecycle points.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from ..spec import load_hooks_config

_HOOK_INSTRUCTIONS = {
    "session_start": "At the start of each coding session, call mc_start with the task intent to load workspace context, candidate files, and rules.",
    "pre_edit": "Before writing or editing any code, call mc_analyze with the target file/symbol to check impact and rules. If mc_analyze returns must-severity rules, do not proceed until the user confirms.",
    "session_stop": "When ending a session or closing the conversation, call mc_close with the session_id to sync artifacts and record experience.",
    "user_prompt_submit": "When the user describes a coding task, determine if it needs Memory Center context. If so, call mc_start first. For Class#method full-chain requests, use mc_lookup(mode='walkthrough' or mode='auto') and follow returned absolute_file_path directly instead of find/grep/IDE search. For other code lookups, use mc_lookup(mode='auto').",
}


def generate_cursor_rules(
    workspace: str,
    output_path: str | Path | None = None,
    hooks_config: Dict[str, Any] | None = None,
) -> Path:
    """Generate .cursorrules with Memory Center lifecycle instructions.

    Returns the path to the generated/updated .cursorrules file.
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
    active_instructions = []
    for event_name, spec in hooks_spec.items():
        enabled = spec.get("enabled", True)
        mode = spec.get("mode", "soft")
        if not enabled or mode == "off":
            continue
        facade = spec.get("facade", "")
        active_hooks.append(f"- {event_name} → {facade} (mode={mode})")
        instruction = _HOOK_INSTRUCTIONS.get(event_name, "")
        if instruction:
            active_instructions.append(f"- **{event_name}** ({mode}): {instruction}")

    hook_list = "\n".join(active_hooks)
    instruction_list = "\n".join(active_instructions)

    content = f"""# Memory Center Integration (Cursor)

This workspace uses Memory Center as the MCP project memory service.

## Hook Lifecycle
{hook_list}

## When to Call Memory Center
{instruction_list}

## Quick Reference
- **mc_start(intent)** — Begin task with workspace context
- **mc_lookup(mode="auto", query=...)** — Find symbols, code, call chains
- **mc_lookup(mode="walkthrough", query="Class#method")** — Trace method-level flow; if absolute_file_path is returned, read it directly and do not use find/grep/IDE search for the same file
- **mc_analyze(target, depth="standard")** — Impact + rules check before editing
- **mc_sync(intent)** — Save progress to task space
- **mc_resume(intent)** — Resume a previous task
- **mc_handoff(target_model)** — Generate handoff for another model
- **mc_close(session_id)** — End session and sync case

<!-- memory-center:start -->
{hook_list}
<!-- memory-center:end -->
"""

    # Append to existing .cursorrules if it has a managed block
    if output_path.exists():
        existing = output_path.read_text(encoding="utf-8")
        if "<!-- memory-center:start -->" in existing and "<!-- memory-center:end -->" in existing:
            start = existing.index("<!-- memory-center:start -->")
            end = existing.index("<!-- memory-center:end -->") + len("<!-- memory-center:end -->")
            output_path.write_text(existing[:start] + content + existing[end:], encoding="utf-8")
        else:
            output_path.write_text(existing.rstrip() + "\n\n" + content, encoding="utf-8")
    else:
        output_path.write_text(content, encoding="utf-8")

    return output_path
