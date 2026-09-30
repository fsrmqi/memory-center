"""Host-agnostic hook runner — resolves params, dispatches to orchestrator, enforces modes.

The runner is the single source of behavioral truth. It reads hooks.yaml,
resolves *_from params from stdin JSON, calls orchestrator functions directly
(no subprocess), and returns structured results with exit_code guidance.
"""
from __future__ import annotations

import json
import re
import sys
from typing import Any

from ..core.audit.interactions import record_host_interaction
from ..core.orchestrator import (
    group_impact,
    group_query,
    group_status,
    memory_callees,
    memory_callers,
    memory_context,
    memory_contracts,
    memory_method_walkthrough,
    memory_plan_change,
    memory_query_hybrid,
    memory_search_code,
    memory_symbol,
    memory_verify_checklist,
    workspace_check_contract,
    workspace_check_rules,
    workspace_end_session,
    workspace_handoff_packet,
    workspace_lookup_hint,
    workspace_next_actions,
    workspace_recent_evidence,
    workspace_record_close_feedback,
    workspace_resume_packet,
    workspace_sniff,
    workspace_start_session,
    workspace_status,
    workspace_sync_case_to_artifacts,
    workspace_sync_sniff_to_artifacts,
    workspace_trace,
    workspace_unresolved_items,
)
from .spec import (
    load_hooks_config,
    session_id_file,
    validate_hooks_config,
)

_JAVA_CHAIN_SYMBOL_RE = re.compile(
    r"((?:[a-z_][\w$]*\.)+[A-Z][\w$]*(?:#[a-zA-Z_][\w$]*)?|[A-Z][\w$]*(?:#[a-zA-Z_][\w$]*)?)"
)


def _resolve_param(
    from_spec: str,
    stdin_json: dict | None,
    param_name: str,
    static_value: str = "",
    workspace_file: str = "",
) -> str:
    """Resolve a parameter value from its *_from declaration."""
    stdin_json = stdin_json or {}
    if from_spec == "event":
        return stdin_json.get("prompt", "") or stdin_json.get("intent", "session start")
    if from_spec == "tool_input_file":
        tool_input = stdin_json.get("tool_input", {})
        return tool_input.get("file_path", "") or tool_input.get("path", "")
    if from_spec == "file":
        target_file = session_id_file(workspace_file or None)
        target_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            return target_file.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
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


def _extract_symbol_like_token(*values: str) -> str:
    for raw in values:
        text = (raw or "").strip()
        if not text:
            continue
        matches = _JAVA_CHAIN_SYMBOL_RE.findall(text)
        if matches:
            matches.sort(key=len, reverse=True)
            return matches[0]
    return ""


def _wants_deep_chain(*values: str) -> bool:
    text = " ".join((value or "") for value in values).lower()
    return any(token in text for token in ["全链路", "到底层", "最底层", "一路到底", "full chain", "trace to sink"])


def _matches_file_patterns(file_path: str, patterns: list[str]) -> bool:
    """Check if a file path matches any of the given glob patterns, supporting **."""
    if not patterns:
        return True
    import re as _re
    norm_path = file_path.replace("\\", "/")
    for pattern in patterns:
        norm_pattern = pattern.replace("\\", "/").lstrip("/")
        regex = _glob_to_regex(norm_pattern)
        if _re.match(regex, norm_path):
            return True
    return False


def _glob_to_regex(pattern: str) -> str:
    """Convert a glob pattern with ** support to a regex string."""
    import re as _re
    parts = pattern.split("**")
    regex_parts: list[str] = []
    for i, part in enumerate(parts):
        segment = ""
        for ch in part.strip("/"):
            if ch == "*":
                segment += "[^/]*"
            elif ch == "?":
                segment += "[^/]"
            elif ch in r".+^${}|()[]\\":
                segment += _re.escape(ch)
            else:
                segment += ch
        if i > 0 and segment:
            regex_parts.append("(?:.*/)?")
        regex_parts.append(segment)
    return "^" + "".join(regex_parts) + "$"


def _run_cleanup(cleanup_actions: list[str], workspace_file: str = "") -> None:
    """Execute cleanup actions after hook completion."""
    for action in cleanup_actions:
        if action == "delete_session_id_file":
            try:
                session_id_file(workspace_file or None).unlink(missing_ok=True)
            except Exception:
                pass


def _write_session_id(session_id: str, workspace_file: str = "") -> None:
    """Write session_id to the workspace-scoped session-id file."""
    import logging
    try:
        target_file = session_id_file(workspace_file or None)
        target_file.parent.mkdir(parents=True, exist_ok=True)
        target_file.write_text(session_id, encoding="utf-8")
    except Exception as exc:
        logging.getLogger("memory_center.hooks").warning("Failed to write session_id file: %s", exc)


def run_hook(
    workspace: str,
    hook_name: str,
    stdin_json: dict | None = None,
) -> dict[str, Any]:
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

    enabled = hook_spec.get("enabled", True)
    mode = hook_spec.get("mode", "soft")
    facade = hook_spec.get("facade", "")
    params_spec = hook_spec.get("params", {})
    filter_spec = hook_spec.get("filter", {})
    cleanup_actions = hook_spec.get("cleanup", [])

    if not enabled:
        return {
            "exit_code": 0,
            "system_message": f"[Hook] {hook_name} is disabled (enabled=false)",
            "hook_result": None,
            "mode": "off",
        }

    # Tool matcher filter: if hook specifies tool_matcher, check stdin tool_name
    tool_matcher = filter_spec.get("tool_matcher", "")
    if tool_matcher and stdin_json:
        tool_name = stdin_json.get("tool_name", "") or (stdin_json.get("tool_input", {}) or {}).get("tool_name", "")
        if tool_name and tool_name not in tool_matcher.split("|"):
            return {
                "exit_code": 0,
                "system_message": f"[Hook] {hook_name}: tool_name '{tool_name}' does not match tool_matcher '{tool_matcher}', skipping",
                "hook_result": None,
                "mode": mode,
            }

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
        local_stdin = stdin_json or {}
        arguments = local_stdin.get("prompt") or local_stdin.get("text") or local_stdin.get("content") or ""
        if hook_spec.get("record_only", False):
            try:
                record_host_interaction(
                    _get_workspace_file(workspace),
                    {
                        "event_type": hook_name,
                        "source": "host_prompt",
                        "query": arguments,
                        "thread_id": str(local_stdin.get("thread_id", "") or ""),
                        "turn_id": str(local_stdin.get("turn_id", "") or ""),
                    },
                    session_id=str(local_stdin.get("session_id", "") or ""),
                )
            except Exception:
                pass
            return {
                "exit_code": 0,
                "system_message": "",
                "hook_result": {"type": "recorded", "event_type": hook_name},
                "mode": "record_only",
            }
        prompt_template = hook_spec.get("prompt_template", "")
        rendered = prompt_template.replace("$ARGUMENTS", arguments)
        return {
            "exit_code": 0,
            "system_message": rendered,
            "hook_result": {"type": "prompt", "prompt": rendered},
            "mode": "suggest",
        }

    # Modes: soft / guard — resolve params and dispatch to facade
    # workspace_file 必须先解析：session_id_from=file 需要同一份交接文件路径
    workspace_file = _get_workspace_file(workspace)
    # Resolve intent
    intent_from = params_spec.get("intent_from", "static")
    intent = _resolve_param(intent_from, stdin_json, "intent", params_spec.get("intent", "session start"), workspace_file)

    # Resolve target (file path for pre_edit)
    target_from = params_spec.get("target_from", "static")
    target = _resolve_param(target_from, stdin_json, "target", params_spec.get("target", ""), workspace_file)

    # Resolve session_id
    session_id_from = params_spec.get("session_id_from", "static")
    session_id = _resolve_param(session_id_from, stdin_json, "session_id", params_spec.get("session_id", ""), workspace_file)

    # Resolve other static params
    budget = params_spec.get("budget", "small")
    auto_sync_mode = params_spec.get("auto_sync_mode", "balanced")
    view = params_spec.get("view", "compact")
    depth = params_spec.get("depth", "quick")
    change_type = params_spec.get("change_type", "general")
    # Resolve outcome if outcome_from is specified
    outcome_from = params_spec.get("outcome_from", "static")
    if outcome_from != "static":
        outcome = _resolve_param(outcome_from, stdin_json, "outcome", params_spec.get("outcome", "session ended"), workspace_file)
    else:
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
    host_tool_name = str(
        (stdin_json or {}).get("tool_name", "")
        or ((stdin_json or {}).get("tool_input", {}) or {}).get("tool_name", "")
        or ""
    )
    try:
        record_host_interaction(
            workspace_file,
            {
                "event_type": hook_name,
                "source": "host_hook",
                "tool_name": host_tool_name,
                "query": intent,
                "target": target,
                "thread_id": str((stdin_json or {}).get("thread_id", "") or ""),
                "turn_id": str((stdin_json or {}).get("turn_id", "") or ""),
            },
            session_id=session_id,
        )
    except Exception:
        pass
    try:
        if facade == "mc_start":
            wf = _get_workspace_file(workspace)
            sniff_result = workspace_sniff(
                wf, intent,
                limit=12, auto_sync_mode=auto_sync_mode,
                view=view, budget=budget,
            )
            resolved_task = sniff_result.get("resolved_task", {}) or {}
            auto_sync = sniff_result.get("auto_sync_recommendation", {}) or {}
            synced = None
            if auto_sync.get("recommended") or resolved_task.get("task_id"):
                synced = workspace_sync_sniff_to_artifacts(
                    wf, intent, limit=12,
                    task_id=str(resolved_task.get("task_id", "") or ""),
                    title=str(resolved_task.get("title", "") or ""),
                    auto_sync_mode=auto_sync_mode,
                )
            session = workspace_start_session(wf, intent)
            # Write session_id to file for later hooks
            sid = session.get("session_id", "")
            if sid:
                _write_session_id(sid, workspace_file=workspace_file)
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
            wf = _get_workspace_file(workspace)
            # For pre_edit guard mode, call check_rules directly
            if target:
                rules_result = workspace_check_rules(
                    wf,
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
                # Depth-based dispatch: standard/full include additional analysis
                if depth in ("standard", "full"):
                    plan_result = memory_plan_change(
                        wf,
                        target=target,
                        change_type=change_type,
                        files=[target],
                    )
                    hook_result["plan"] = plan_result
                    system_message += " | Change plan generated"
                if depth == "full":
                    verify_result = memory_verify_checklist(
                        wf,
                        target=target,
                        change_type=change_type,
                        files=[target],
                    )
                    hook_result["verify"] = verify_result
                    system_message += " | Verify checklist generated"
                contract_result = workspace_check_contract(wf, target, change_type)
                hook_result["contract_semantics"] = contract_result.get("semantic_compatibility", {})
                hook_result["runtime_contract"] = contract_result.get("runtime_compatibility", {})
                contract_status = str(contract_result.get("gate_status", "pass"))
                system_message += f" | Contract: {contract_status}"
                # Guard mode: block if must-severity rules match
                if mode == "guard":
                    has_must = any(
                        r.get("severity") == "must" for r in matched
                    )
                    if has_must or contract_status == "block":
                        must_rules = [
                            r.get("title", r.get("id", ""))
                            for r in matched
                            if r.get("severity") == "must"
                        ]
                        system_message += (
                            f" | BLOCKED: must-severity rules: {must_rules}; contract_status={contract_status}"
                        )
                        _run_cleanup(cleanup_actions, workspace_file=workspace_file)
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
            wf = _get_workspace_file(workspace)
            lookup_mode = params_spec.get("mode", "auto")
            limit = int(params_spec.get("limit", 20))
            depth_value = int(params_spec.get("depth", 2))
            scope = params_spec.get("scope", "")
            name = params_spec.get("name", "") or intent
            symbol = params_spec.get("symbol", "") or intent
            entry = params_spec.get("entry", "") or intent
            resolved_symbol = _extract_symbol_like_token(symbol, name, entry, intent)
            resolved_depth = max(depth_value, 4) if _wants_deep_chain(intent, symbol, name, entry) else depth_value
            if lookup_mode == "auto":
                hint = workspace_lookup_hint(wf, query=intent, intent=intent, limit=limit)
                preferred = [t.replace("_tool", "") for t in hint.get("preferred_tools", [])]
                if _wants_deep_chain(intent, symbol, name, entry) and "#" in resolved_symbol:
                    hook_result = {
                        "mode_used": "walkthrough",
                        "result": memory_method_walkthrough(wf, resolved_symbol, resolved_depth, limit, view=view, budget=budget),
                    }
                elif "memory_callers" in preferred and resolved_symbol:
                    hook_result = {
                        "mode_used": "chain-callers",
                        "result": memory_callers(wf, resolved_symbol, resolved_depth, limit, view=view, budget=budget),
                    }
                elif "memory_callees" in preferred and resolved_symbol:
                    hook_result = {
                        "mode_used": "chain-callees",
                        "result": memory_callees(wf, resolved_symbol, resolved_depth, limit, view=view, budget=budget),
                    }
                elif "memory_symbol" in preferred and (name or resolved_symbol):
                    hook_result = {
                        "mode_used": "symbol",
                        "result": memory_symbol(wf, name or resolved_symbol, limit, view=view, budget=budget),
                    }
                elif "memory_search_code" in preferred:
                    hook_result = {"mode_used": "code", "result": memory_search_code(wf, intent, scope, limit)}
                elif "memory_context" in preferred and (name or resolved_symbol):
                    hook_result = {
                        "mode_used": "context",
                        "result": memory_context(wf, name or resolved_symbol, resolved_depth, view=view, budget=budget),
                    }
                elif "workspace_trace" in preferred and (entry or resolved_symbol):
                    hook_result = {"mode_used": "trace", "result": workspace_trace(wf, entry or resolved_symbol)}
                else:
                    hook_result = {"mode_used": "query", "result": memory_query_hybrid(wf, intent, limit), "lookup_hint": hint}
            elif lookup_mode == "symbol":
                hook_result = {"mode": "symbol", "result": memory_symbol(wf, name, limit, view=view, budget=budget)}
            elif lookup_mode == "code":
                hook_result = {"mode": "code", "result": memory_search_code(wf, intent, scope, limit)}
            elif lookup_mode == "query":
                hook_result = {"mode": "query", "result": memory_query_hybrid(wf, intent, limit)}
            elif lookup_mode == "trace":
                hook_result = {"mode": "trace", "result": workspace_trace(wf, entry)}
            elif lookup_mode == "chain":
                if params_spec.get("chain_direction", "callers") == "callees":
                    hook_result = {
                        "mode": "chain-callees",
                        "result": memory_callees(wf, symbol, depth_value, limit, view=view, budget=budget),
                    }
                else:
                    hook_result = {
                        "mode": "chain-callers",
                        "result": memory_callers(wf, symbol, depth_value, limit, view=view, budget=budget),
                    }
            elif lookup_mode == "walkthrough":
                hook_result = {"mode": "walkthrough", "result": memory_method_walkthrough(wf, symbol or resolved_symbol, depth_value, limit, view=view, budget=budget)}
            elif lookup_mode == "context":
                hook_result = {"mode": "context", "result": memory_context(wf, name, depth_value, view=view, budget=budget)}
            elif lookup_mode == "contracts":
                hook_result = {"mode": "contracts", "result": memory_contracts(wf)}
            else:
                hook_result = {"mode": "query", "result": memory_query_hybrid(wf, intent, limit)}
            system_message = f"[Memory Center] Lookup completed: mode={hook_result.get('mode_used', hook_result.get('mode', 'auto'))}"

        elif facade == "mc_sync":
            wf = _get_workspace_file(workspace)
            if session_id.strip():
                hook_result = {"workflow": "mc-sync", "mode": "case", "result": workspace_sync_case_to_artifacts(wf, session_id, task_id=params_spec.get("task_id", ""), title=params_spec.get("title", ""), auto_sync_mode=auto_sync_mode)}
            elif intent.strip():
                hook_result = {"workflow": "mc-sync", "mode": "sniff", "result": workspace_sync_sniff_to_artifacts(wf, intent, limit=int(params_spec.get("limit", 12)), task_id=params_spec.get("task_id", ""), title=params_spec.get("title", ""), auto_sync_mode=auto_sync_mode)}
            else:
                hook_result = {"workflow": "mc-sync", "error": "requires intent or session_id"}
            system_message = f"[Memory Center] Sync completed: workflow={hook_result.get('workflow', 'unknown')}"

        elif facade == "mc_resume":
            wf = _get_workspace_file(workspace)
            hook_result = {
                "workflow": "mc-resume",
                "resume_packet": workspace_resume_packet(wf, task_id=params_spec.get("task_id", ""), session_id=session_id, intent=intent, limit=int(params_spec.get("limit", 8)), view=view, budget=budget),
                "next_actions": workspace_next_actions(wf, task_id=params_spec.get("task_id", ""), session_id=session_id, intent=intent, limit=int(params_spec.get("limit", 8))),
                "unresolved_items": workspace_unresolved_items(wf, task_id=params_spec.get("task_id", ""), session_id=session_id, intent=intent, limit=int(params_spec.get("limit", 8))),
                "recent_evidence": workspace_recent_evidence(wf, task_id=params_spec.get("task_id", ""), session_id=session_id, limit=min(int(params_spec.get("limit", 8)), 5), budget=budget, view=view),
            }
            system_message = "[Memory Center] Resume completed"

        elif facade == "mc_handoff":
            wf = _get_workspace_file(workspace)
            from ..core.orchestrator import memory_tool_usage_report
            hook_result = {
                "workflow": "mc-handoff",
                "handoff_packet": workspace_handoff_packet(wf, target_model=params_spec.get("target_model", "codex"), task_id=params_spec.get("task_id", ""), session_id=session_id, intent=intent, limit=int(params_spec.get("limit", 8)), view=view, budget=budget),
                "recent_evidence": workspace_recent_evidence(wf, task_id=params_spec.get("task_id", ""), session_id=session_id, limit=min(int(params_spec.get("limit", 8)), 5), budget=budget, view=view),
                "tool_usage_report": memory_tool_usage_report(wf, limit=50),
            }
            system_message = "[Memory Center] Handoff completed"

        elif facade == "mc_admin":
            from ..core.knowledge.skill_generation import generate_skills
            from ..core.orchestrator import (
                memory_tool_usage_report,
                memory_write_judge,
                workspace_dashboard,
                workspace_model_profile,
            )
            from ..core.tasks.artifacts import (
                artifact_context,
                artifact_outline,
                create_task_space,
                get_artifact,
                list_artifacts,
                list_task_spaces,
                resolve_task_space,
                update_artifact,
            )
            wf = _get_workspace_file(workspace)
            action = params_spec.get("action", "status")
            _ADMIN_DISPATCH = {
                "status": lambda: workspace_status(wf, view=view, budget=budget),
                "dashboard": lambda: workspace_dashboard(wf, intent=intent, limit=int(params_spec.get("limit", 10)), view=view, budget=budget),
                "health": lambda: {
                    "workflow": "mc-admin-health",
                    "status": workspace_status(wf, view="compact", budget="medium"),
                    "tool_usage_report": memory_tool_usage_report(wf, limit=50),
                },
                "artifact_list": lambda: list_artifacts(wf),
                "artifact_get": lambda: get_artifact(wf, params_spec.get("name", "")),
                "artifact_outline": lambda: artifact_outline(wf, params_spec.get("name", "")),
                "artifact_context": lambda: artifact_context(wf, intent, limit=int(params_spec.get("limit", 10))),
                "artifact_update": lambda: update_artifact(wf, params_spec.get("name", ""), params_spec.get("content", "")),
                "task_create": lambda: create_task_space(wf, title=params_spec.get("title", ""), intent=intent, owner=params_spec.get("owner", ""), tags=params_spec.get("tags"), priority=params_spec.get("priority", "medium")),
                "task_list": lambda: list_task_spaces(wf, include_archived=params_spec.get("include_archived", False)),
                "task_resolve": lambda: resolve_task_space(wf, intent=intent, title=params_spec.get("title", ""), create_if_missing=params_spec.get("create_if_missing", True), include_archived=params_spec.get("include_archived", False), limit_candidates=int(params_spec.get("limit", 10)), score_threshold=int(params_spec.get("score_threshold", 3))),
                "session_start": lambda: workspace_start_session(wf, intent, session_id=session_id or None),
                "session_recent": lambda: {"action": "session_recent", "result": workspace_status(wf, view=view, budget=budget)},
                "model_profile": lambda: workspace_model_profile(params_spec.get("target_model", "codex")),
                "write_judge": lambda: memory_write_judge(wf, text=params_spec.get("text", ""), source=params_spec.get("source", ""), intent=intent, prefer_layer=params_spec.get("prefer_layer", ""), projects=params_spec.get("projects"), files=params_spec.get("files")),
                "tool_usage_report": lambda: memory_tool_usage_report(wf, limit=int(params_spec.get("limit", 50))),
                "generate_skills": lambda: generate_skills(wf, params_spec.get("output_dir", "") or None),
                "group_status": lambda: group_status(params_spec.get("group", "")),
                "group_query": lambda: group_query(params_spec.get("group", ""), query=params_spec.get("text", ""), limit=int(params_spec.get("limit", 10))),
                "group_impact": lambda: group_impact(params_spec.get("group", ""), target=intent or params_spec.get("text", ""), direction=params_spec.get("direction", "upstream"), max_depth=int(params_spec.get("max_depth", 3))),
            }
            handler = _ADMIN_DISPATCH.get(action)
            if handler is None:
                valid = ", ".join(sorted(_ADMIN_DISPATCH.keys()))
                hook_result = {"action": action, "error": f"Unknown action: {action}. Valid: {valid}"}
            else:
                hook_result = {"action": action, "result": handler()}
            system_message = f"[Memory Center] Admin action: {action}"

        elif facade == "mc_close":
            wf = _get_workspace_file(workspace)
            if session_id:
                ended = workspace_end_session(wf, session_id, outcome=outcome)
                synced = workspace_sync_case_to_artifacts(
                    wf, session_id,
                    auto_sync_mode=auto_sync_mode,
                )
                candidate_feedback = workspace_record_close_feedback(
                    wf,
                    session_id,
                    task_id=params_spec.get("task_id", ""),
                    source="hook_session_stop_auto",
                )
                hook_result = {
                    "workflow": "mc-close",
                    "ended": ended,
                    "sync_case": synced,
                    "candidate_feedback": candidate_feedback,
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
    _run_cleanup(cleanup_actions, workspace_file=workspace_file)

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
