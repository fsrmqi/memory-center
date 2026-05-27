"""Host-agnostic hook runner — resolves params, dispatches to orchestrator, enforces modes.

The runner is the single source of behavioral truth. It reads hooks.yaml,
resolves *_from params from stdin JSON, calls orchestrator functions directly
(no subprocess), and returns structured results with exit_code guidance.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict

from .spec import (
    _SESSION_ID_FILE,
    _VALID_MODES,
    load_hooks_config,
    validate_hooks_config,
)
from ..core.orchestrator import (
    workspace_check_rules,
    workspace_end_session,
    workspace_sniff,
    workspace_start_session,
    workspace_sync_case_to_artifacts,
    workspace_sync_sniff_to_artifacts,
)


def _resolve_param(
    from_spec: str,
    stdin_json: dict | None,
    param_name: str,
    static_value: str = "",
) -> str:
    """Resolve a parameter value from its *_from declaration."""
    stdin_json = stdin_json or {}
    if from_spec == "event":
        return stdin_json.get("prompt", "") or stdin_json.get("intent", "session start")
    if from_spec == "tool_input_file":
        tool_input = stdin_json.get("tool_input", {})
        return tool_input.get("file_path", "") or tool_input.get("path", "")
    if from_spec == "file":
        _SESSION_ID_FILE.parent.mkdir(parents=True, exist_ok=True)
        if _SESSION_ID_FILE.exists():
            return _SESSION_ID_FILE.read_text(encoding="utf-8").strip()
        return ""
    if from_spec == "static":
        return static_value
    return ""


def _get_workspace_file(workspace: str) -> str:
    """Resolve workspace file path from workspace directory or file."""
    from pathlib import Path as P
    p = P(workspace).expanduser().resolve()
    if p.is_dir():
        return str(p / ".memory-center" / "workspace.yaml")
    return str(p)


def _matches_file_patterns(file_path: str, patterns: list[str]) -> bool:
    """Check if a file path matches any of the given glob patterns."""
    if not patterns:
        return True
    from fnmatch import fnmatch
    normalized = file_path.replace("\\", "/")
    for pattern in patterns:
        norm_pattern = pattern.replace("\\", "/")
        # Try matching full path against the pattern
        if fnmatch(normalized, norm_pattern):
            return True
        # Try matching just the filename
        name = normalized.rsplit("/", 1)[-1]
        if fnmatch(name, norm_pattern):
            return True
        if fnmatch(name, norm_pattern.lstrip("/")):
            return True
    return False


def _run_cleanup(cleanup_actions: list[str]) -> None:
    """Execute cleanup actions after hook completion."""
    for action in cleanup_actions:
        if action == "delete_session_id_file":
            try:
                _SESSION_ID_FILE.unlink(missing_ok=True)
            except Exception:
                pass


def _write_session_id(session_id: str) -> None:
    """Write session_id to the session-id file."""
    try:
        _SESSION_ID_FILE.parent.mkdir(parents=True, exist_ok=True)
        _SESSION_ID_FILE.write_text(session_id, encoding="utf-8")
    except Exception:
        pass


def run_hook(
    workspace: str,
    hook_name: str,
    stdin_json: dict | None = None,
) -> Dict[str, Any]:
    """Execute a hook according to hooks.yaml specification.

    Returns a dict with:
      - exit_code: 0 (allow), 2 (block in guard mode), 1 (error)
      - system_message: Human-readable message to inject into host context
      - hook_result: Raw result from the facade call
      - mode: The enforcement mode used
    """
    # Load hooks config
    config = load_hooks_config(workspace)
    errors = validate_hooks_config(config)
    if errors:
        return {
            "exit_code": 1,
            "system_message": f"[Hook] Config validation failed: {', '.join(errors)}",
            "hook_result": None,
            "mode": "error",
        }

    hooks = config.get("hooks", {})
    hook_spec = hooks.get(hook_name)
    if hook_spec is None:
        return {
            "exit_code": 1,
            "system_message": f"[Hook] Unknown hook: {hook_name}",
            "hook_result": None,
            "mode": "error",
        }

    mode = hook_spec.get("mode", "soft")
    facade = hook_spec.get("facade", "")
    params_spec = hook_spec.get("params", {})
    filter_spec = hook_spec.get("filter", {})
    cleanup_actions = hook_spec.get("cleanup", [])

    # Mode: off — skip entirely
    if mode == "off":
        return {
            "exit_code": 0,
            "system_message": f"[Hook] {hook_name} is disabled (mode=off)",
            "hook_result": None,
            "mode": "off",
        }

    # Mode: suggest — return prompt template, no command execution
    if mode == "suggest":
        prompt_template = hook_spec.get("prompt_template", "")
        arguments = ""
        local_stdin = stdin_json or {}
        if local_stdin.get("prompt"):
            arguments = local_stdin["prompt"]
        rendered = prompt_template.replace("$ARGUMENTS", arguments)
        return {
            "exit_code": 0,
            "system_message": rendered,
            "hook_result": {"type": "prompt", "prompt": rendered},
            "mode": "suggest",
        }

    # Modes: soft / guard — resolve params and dispatch to facade
    # Resolve intent
    intent_from = params_spec.get("intent_from", "static")
    intent = _resolve_param(intent_from, stdin_json, "intent", params_spec.get("intent", "session start"))

    # Resolve target (file path for pre_edit)
    target_from = params_spec.get("target_from", "static")
    target = _resolve_param(target_from, stdin_json, "target", params_spec.get("target", ""))

    # Resolve session_id
    session_id_from = params_spec.get("session_id_from", "static")
    session_id = _resolve_param(session_id_from, stdin_json, "session_id", params_spec.get("session_id", ""))

    # Resolve other static params
    budget = params_spec.get("budget", "small")
    auto_sync_mode = params_spec.get("auto_sync_mode", "balanced")
    view = params_spec.get("view", "compact")
    depth = params_spec.get("depth", "quick")
    change_type = params_spec.get("change_type", "general")
    outcome = params_spec.get("outcome", "session ended")

    # File pattern filter for pre_edit
    file_patterns = filter_spec.get("file_patterns", [])
    if hook_name == "pre_edit" and target and file_patterns:
        if not _matches_file_patterns(target, file_patterns):
            return {
                "exit_code": 0,
                "system_message": f"[Hook] {hook_name}: file {target} does not match filter patterns, skipping",
                "hook_result": None,
                "mode": mode,
            }

    # Dispatch to facade
    hook_result: Any = None
    system_message = ""
    try:
        if facade == "mc_start":
            sniff_result = workspace_sniff(
                workspace, intent,
                limit=12, auto_sync_mode=auto_sync_mode,
                view=view, budget=budget,
            )
            resolved_task = sniff_result.get("resolved_task", {}) or {}
            auto_sync = sniff_result.get("auto_sync_recommendation", {}) or {}
            synced = None
            if auto_sync.get("recommended") or resolved_task.get("task_id"):
                synced = workspace_sync_sniff_to_artifacts(
                    workspace, intent, limit=12,
                    task_id=str(resolved_task.get("task_id", "") or ""),
                    title=str(resolved_task.get("title", "") or ""),
                    auto_sync_mode=auto_sync_mode,
                )
            session = workspace_start_session(workspace, intent)
            # Write session_id to file for later hooks
            sid = session.get("session_id", "")
            if sid:
                _write_session_id(sid)
            hook_result = {
                "workflow": "mc-start",
                "sniff": sniff_result,
                "sync_sniff": synced,
                "session": session,
            }
            risk = sniff_result.get("risk_level", "unknown")
            rules_count = len(sniff_result.get("related_rules", []))
            system_message = (
                f"[Memory Center] Session started. Risk: {risk} | "
                f"Rules: {rules_count} related | session_id: {sid}"
            )

        elif facade == "mc_analyze":
            # For pre_edit guard mode, call check_rules directly
            if target:
                rules_result = workspace_check_rules(
                    workspace,
                    projects=None,
                    change_type=change_type,
                    files=[target],
                )
                hook_result = rules_result
                matched = rules_result.get("rules", [])
                system_message = (
                    f"[Memory Center] Rules check for {target}: "
                    f"{len(matched)} rules matched"
                )
                # Guard mode: block if must-severity rules match
                if mode == "guard":
                    has_must = any(
                        r.get("severity") == "must" for r in matched
                    )
                    if has_must:
                        must_rules = [
                            r.get("title", r.get("id", ""))
                            for r in matched
                            if r.get("severity") == "must"
                        ]
                        system_message += (
                            f" | BLOCKED: must-severity rules: {must_rules}"
                        )
                        return {
                            "exit_code": 2,
                            "system_message": system_message,
                            "hook_result": hook_result,
                            "mode": "guard",
                        }
            else:
                hook_result = {"message": "No target file specified for pre_edit"}
                system_message = "[Memory Center] No target file for pre_edit check"

        elif facade == "mc_lookup":
            from ..mcp.server import mc_lookup as _mc_lookup
            wf = _get_workspace_file(workspace)
            hook_result = _mc_lookup(
                query=intent,
                mode=params_spec.get("mode", "auto"),
                name=params_spec.get("name", ""),
                scope=params_spec.get("scope", ""),
                symbol=params_spec.get("symbol", ""),
                chain_direction=params_spec.get("chain_direction", "callers"),
                depth=int(params_spec.get("depth", 2)),
                entry=params_spec.get("entry", ""),
                ref_id=params_spec.get("ref_id", ""),
                limit=int(params_spec.get("limit", 20)),
            )
            system_message = f"[Memory Center] Lookup completed: mode={hook_result.get('mode_used', hook_result.get('mode', 'auto'))}"

        elif facade == "mc_sync":
            from ..mcp.server import mc_sync as _mc_sync
            wf = _get_workspace_file(workspace)
            hook_result = _mc_sync(
                intent=intent,
                session_id=session_id,
                task_id=params_spec.get("task_id", ""),
                title=params_spec.get("title", ""),
                limit=int(params_spec.get("limit", 12)),
                auto_sync_mode=auto_sync_mode,
            )
            system_message = f"[Memory Center] Sync completed: workflow={hook_result.get('workflow', 'unknown')}"

        elif facade == "mc_resume":
            from ..mcp.server import mc_resume as _mc_resume
            wf = _get_workspace_file(workspace)
            hook_result = _mc_resume(
                intent=intent,
                task_id=params_spec.get("task_id", ""),
                session_id=session_id,
                limit=int(params_spec.get("limit", 8)),
                budget=budget,
            )
            system_message = f"[Memory Center] Resume completed"

        elif facade == "mc_handoff":
            from ..mcp.server import mc_handoff as _mc_handoff
            wf = _get_workspace_file(workspace)
            hook_result = _mc_handoff(
                target_model=params_spec.get("target_model", "codex"),
                task_id=params_spec.get("task_id", ""),
                session_id=session_id,
                intent=intent,
                limit=int(params_spec.get("limit", 8)),
                budget=budget,
            )
            system_message = f"[Memory Center] Handoff completed"

        elif facade == "mc_admin":
            from ..mcp.server import mc_admin as _mc_admin
            wf = _get_workspace_file(workspace)
            action = params_spec.get("action", "status")
            hook_result = _mc_admin(
                action=action,
                view=view,
                budget=budget,
                limit=int(params_spec.get("limit", 10)),
                name=params_spec.get("name", ""),
                content=params_spec.get("content", ""),
                task_id=params_spec.get("task_id", ""),
                title=params_spec.get("title", ""),
                intent=intent,
                owner=params_spec.get("owner", ""),
                tags=params_spec.get("tags"),
                priority=params_spec.get("priority", "medium"),
                status=params_spec.get("status", ""),
                source=params_spec.get("source", ""),
                reason=params_spec.get("reason", ""),
                include_archived=params_spec.get("include_archived", False),
                create_if_missing=params_spec.get("create_if_missing", True),
                score_threshold=int(params_spec.get("score_threshold", 3)),
                entry=params_spec.get("entry", ""),
                keep_recent=int(params_spec.get("keep_recent", 30)),
                session_id=session_id,
                event_type=params_spec.get("event_type", ""),
                payload=params_spec.get("payload"),
                outcome=outcome,
                verified_by=params_spec.get("verified_by"),
                target_model=params_spec.get("target_model", "codex"),
                scope=params_spec.get("scope", "all"),
                tool_name=params_spec.get("tool_name", ""),
                model=params_spec.get("model", ""),
                text=params_spec.get("text", ""),
                prefer_layer=params_spec.get("prefer_layer", ""),
                projects=params_spec.get("projects"),
                files=params_spec.get("files"),
                group=params_spec.get("group", ""),
                direction=params_spec.get("direction", "upstream"),
                max_depth=int(params_spec.get("max_depth", 3)),
                output_dir=params_spec.get("output_dir", ""),
                collection=params_spec.get("collection", ""),
                record_id=params_spec.get("record_id", ""),
                created_after=params_spec.get("created_after", ""),
                ref_path=params_spec.get("ref_path", ""),
                payload_type=params_spec.get("payload_type", ""),
                layer=params_spec.get("layer", ""),
                action_filter=params_spec.get("action_filter", ""),
            )
            system_message = f"[Memory Center] Admin action: {action}"

        elif facade == "mc_close":
            if session_id:
                ended = workspace_end_session(workspace, session_id, outcome=outcome)
                synced = workspace_sync_case_to_artifacts(
                    workspace, session_id,
                    auto_sync_mode=auto_sync_mode,
                )
                hook_result = {
                    "workflow": "mc-close",
                    "ended": ended,
                    "sync_case": synced,
                }
                system_message = "[Memory Center] Session closed and synced."
            else:
                hook_result = {"message": "No session_id available for session_stop"}
                system_message = "[Memory Center] No session_id — session_stop skipped"

        else:
            return {
                "exit_code": 1,
                "system_message": f"[Hook] Unsupported facade for hook runner: {facade}",
                "hook_result": None,
                "mode": mode,
            }

    except Exception as exc:
        return {
            "exit_code": 1,
            "system_message": f"[Hook] {hook_name} failed: {exc}",
            "hook_result": None,
            "mode": mode,
        }

    # Run cleanup actions
    _run_cleanup(cleanup_actions)

    return {
        "exit_code": 0,
        "system_message": system_message,
        "hook_result": hook_result,
        "mode": mode,
    }


def run_hook_cli(workspace: str, hook_name: str) -> int:
    """CLI wrapper: read stdin JSON, call run_hook, output result, set process exit code."""
    stdin_json = None
    try:
        raw = sys.stdin.read()
        if raw.strip():
            stdin_json = json.loads(raw)
    except Exception:
        stdin_json = None

    result = run_hook(workspace, hook_name, stdin_json)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result.get("exit_code", 0)