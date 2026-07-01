"""Memory Center MCP server — 8 facade tools (task-level interface).

Previously exposed 82 atomic tools; now consolidated into 8 task-level facades:
  mc_start   — begin a task workflow (sniff + sync + session)
  mc_lookup  — unified knowledge lookup (auto/symbol/code/query/trace/chain/walkthrough/context/contracts/ref)
  mc_analyze — change impact analysis (quick/standard/full depth)
  mc_sync    — sync context to workspace artifacts (sniff or case)
  mc_resume  — resume a task with consolidated context
  mc_handoff — build a handoff package for another model
  mc_close   — close a task workflow (end + sync + record)
  mc_admin   — admin/router for status, artifacts, evals, sessions, groups, etc.

All underlying orchestrator/artifacts functions remain callable from Python.
CLI and HTTP server keep their fine-grained interfaces unchanged.
"""
from __future__ import annotations

import argparse
import inspect
import re
from functools import wraps
from pathlib import Path
from typing import Any

from memory_center.core.errors import normalize_exception
from memory_center.core.orchestrator import (
    _annotate_phantom_nodes,
    group_chain,
    memory_backend_query,
    memory_callees,
    memory_callers,
    memory_context,
    memory_contracts,
    memory_detect_changes,
    memory_impact,
    memory_method_walkthrough,
    memory_plan_change,
    memory_query_hybrid,
    memory_ref_batch,
    memory_ref_get,
    memory_search_code,
    memory_symbol,
    memory_tool_usage_report,
    memory_verify_checklist,
    workspace_check_contract,
    workspace_check_rules,
    workspace_end_session,
    workspace_handoff_packet,
    workspace_lookup_hint,
    workspace_next_actions,
    workspace_recent_evidence,
    workspace_record_case,
    workspace_record_close_feedback,
    workspace_resume_packet,
    workspace_sniff,
    workspace_start_session,
    workspace_status,
    workspace_suggest_case,
    workspace_sync_case_to_artifacts,
    workspace_sync_sniff_to_artifacts,
    workspace_trace,
    workspace_unresolved_items,
)
from memory_center.core.registry import load_registry
from memory_center.core.store import WorkspaceStore

_JAVA_CHAIN_SYMBOL_RE = re.compile(
    r"((?:[a-z_][\w$]*\.)+[A-Z][\w$]*(?:#[a-zA-Z_][\w$]*)?|[A-Z][\w$]*(?:#[a-zA-Z_][\w$]*)?)"
)

# Behavior-matrix tests assert that MCP keeps parity with shared backends even
# for capabilities routed through facades/admin actions instead of direct imports.
_SHARED_BACKEND_CONTRACTS = (
    "get_workflow_profile",
    "audit_agent_runtime",
    "check_regression_alerts",
    "memory_eval_parser_benchmark",
    "VerificationLoop",
    "extract_business_flows_for_workspace",
    "business_flow_impact_for_workspace",
)

def _find_workspace_name_in_registry(workspace_file: str, registry: dict[str, Any]) -> str | None:
    wf_resolved = str(Path(workspace_file).expanduser().resolve())
    for repo in registry.get("repos", []):
        if str(Path(repo.get("workspace_file", "")).expanduser().resolve()) == wf_resolved:
            return repo.get("name")
    return None

def _find_groups_for_workspace(workspace_file: str) -> list[str]:
    registry = load_registry()
    ws_name = _find_workspace_name_in_registry(workspace_file, registry)
    if not ws_name:
        return []
    groups: list[str] = []
    for group in registry.get("groups", []):
        if ws_name in group.get("members", []):
            groups.append(group.get("name", ""))
    return groups

class _WorkspaceContext:
    """Holds workspace file path per server instance, avoiding module-level global."""
    def __init__(self, workspace_file: str):
        self.workspace_input = workspace_file
        self.workspace_file = _resolve_workspace_input(workspace_file)
        self.startup_diagnostics = _build_startup_diagnostics(self.workspace_input, self.workspace_file)


def _build_startup_diagnostics(workspace_input: str, workspace_file: str) -> dict[str, Any]:
    diagnostics: dict[str, Any] = {
        "workspace_input": workspace_input,
        "workspace_file": workspace_file,
        "resolved_from_directory": str(workspace_input or "").strip() != workspace_file,
        "ok": False,
        "checks": [],
        "next_actions": [],
    }
    try:
        from memory_center.core.config import load_workspace_config
        from memory_center.core.instructions import inspect_agent_mcp_bindings

        config = load_workspace_config(workspace_file)
        bindings = inspect_agent_mcp_bindings(WorkspaceStore(workspace_file), config.root_path)
        diagnostics.update(
            {
                "ok": bool(bindings.get("ok")) and bool(bindings.get("command_available")),
                "workspace": config.workspace,
                "workspace_root": str(Path(config.root_path).expanduser().resolve()),
                "mcp_bindings": bindings,
            }
        )
        diagnostics["checks"].append({"name": "workspace_resolved", "ok": True})
        diagnostics["checks"].append({"name": "mcp_bindings", "ok": bool(bindings.get("ok"))})
        diagnostics["checks"].append({"name": "mcp_command_available", "ok": bool(bindings.get("command_available"))})
        if not bindings.get("ok"):
            diagnostics["next_actions"].append(
                "运行 `memory-center setup-agent --workspace <workspace.yaml>` 自动刷新根目录和子项目 MCP 绑定。"
            )
        if not bindings.get("command_available"):
            diagnostics["next_actions"].append("确认 memory-center-mcp 已安装且在宿主 PATH 中。")
    except Exception as exc:
        diagnostics["error"] = str(exc)
        diagnostics["checks"].append({"name": "workspace_resolved", "ok": False})
        diagnostics["next_actions"].append("确认 --workspace 指向 .memory-center/workspace.yaml，或传入聚合 workspace / 子项目目录。")
    return diagnostics


def _resolve_workspace_input(workspace_input: str) -> str:
    """Resolve a file/dir input to workspace.yaml when possible, without hard failure."""
    raw = (workspace_input or ".").strip() or "."
    path = Path(raw).expanduser()
    if path.is_file():
        return str(path.resolve())
    start = path.resolve() if path.exists() else Path.cwd().resolve()
    if start.name == ".memory-center":
        candidate = start / "workspace.yaml"
        if candidate.exists():
            return str(candidate.resolve())
    for parent in [start, *start.parents]:
        candidate = parent / ".memory-center" / "workspace.yaml"
        if candidate.exists():
            return str(candidate.resolve())
    return str(path.resolve())


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


def _parse_payload(payload_str: str) -> dict[str, Any] | None:
    """Parse a JSON string payload for MCP tool compatibility."""
    if not payload_str:
        return None
    try:
        import json
        result = json.loads(payload_str)
        return result if isinstance(result, dict) else None
    except (json.JSONDecodeError, ValueError, TypeError):
        return None


def _benchmark_trend_report(workspace_file: str, function_name: str = "") -> dict[str, Any]:
    """Generate benchmark trend report for mc_admin."""
    from ..core.benchmark.trending import generate_benchmark_report
    return generate_benchmark_report(workspace_file, function_name=function_name)


def _flatten_walkthrough_payload(result: dict[str, Any], mode_key: str = "mode_used") -> dict[str, Any]:
    summary_lines = result.get("summary_lines", []) or []
    return {
        mode_key: "walkthrough",
        "found": result.get("found", False),
        "target": result.get("target", {}),
        "answer": "\n".join(summary_lines),
        "answer_markdown": result.get("answer_markdown", ""),
        "answer_template": result.get("answer_template", {}),
        "summary_lines": summary_lines,
        "primary_flow": summary_lines,
        "read_targets": _collect_walkthrough_read_targets(result),
        "mermaid_flow": result.get("mermaid_flow", ""),
        "performance_risks": result.get("performance_risks", []),
        "data_scope_guards": result.get("data_scope_guards", []),
        "diff_context": result.get("diff_context", {}),
        "glossary_hits": result.get("glossary_hits", []),
        "schema_version": result.get("schema_version", 1),
        "fields_contract": result.get("fields_contract", {}),
        "index_freshness": result.get("index_freshness", {}),
        "completion_status": result.get("completion_status", {}),
        "branch_outline": result.get("branch_outline", []),
        "anti_patterns": result.get("anti_patterns", []),
        "cache": result.get("cache", {}),
        "agent_usage_policy": result.get("agent_usage_policy", {}),
        "next_actions": result.get("next_actions", []),
        "result": result,
    }


def _collect_walkthrough_read_targets(result: dict[str, Any]) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    seen = set()

    def add(role: str, item: dict[str, Any], label: str = "") -> None:
        abs_path = item.get("absolute_file_path") or item.get("file_path")
        if not abs_path:
            return
        key = (role, abs_path, item.get("line", 0), label)
        if key in seen:
            return
        seen.add(key)
        targets.append({
            "role": role,
            "label": label or item.get("class") or item.get("controller") or item.get("method") or "",
            "absolute_file_path": abs_path,
            "line": item.get("line", 0),
            "project": item.get("project", ""),
        })

    target = result.get("target", {}) or {}
    add("target", target, f"{target.get('class', '')}#{target.get('method', '')}")
    for impl in result.get("local_service_continuations", []) or []:
        impl_target = impl.get("target", {}) or {}
        add("local_impl", impl_target, f"{impl_target.get('class', '')}#{impl_target.get('method', '')}")
        for same in impl.get("same_class_method_continuations", []) or []:
            same_target = same.get("target", {}) or {}
            add("local_impl_same_class", same_target, f"{same_target.get('class', '')}#{same_target.get('method', '')}")
    for same in result.get("same_class_method_continuations", []) or []:
        same_target = same.get("target", {}) or {}
        add("same_class", same_target, f"{same_target.get('class', '')}#{same_target.get('method', '')}")
    for feign in result.get("feign_continuations", []) or []:
        for server in (feign.get("server_walkthroughs", []) or [])[:1]:
            add("server_controller", server, f"{server.get('controller', '')}#{server.get('method', '')}")
            for impl in (server.get("service_impl_continuations", []) or [])[:1]:
                impl_target = impl.get("target", {}) or {}
                add("server_impl", impl_target, f"{impl_target.get('class', '')}#{impl_target.get('method', '')}")
                for same in impl.get("same_class_method_continuations", []) or []:
                    same_target = same.get("target", {}) or {}
                    add("server_impl_same_class", same_target, f"{same_target.get('class', '')}#{same_target.get('method', '')}")
    return targets


def _run_audit(workspace_file: str, work_package: str = "") -> dict[str, Any]:
    """Run completion audit for mc_admin."""
    from ..core.audit.completion import run_completion_audit
    return run_completion_audit(workspace_file, work_package=work_package)


def _drill_ref(workspace_file: str, ref_id: str = "") -> dict[str, Any]:
    """Expand a ref with progressive disclosure for mc_admin."""
    from ..core.navigation.drilldown import DrillDownNavigator
    with DrillDownNavigator(workspace_file) as nav:
        return nav.expand_ref(ref_id)


def _drill_timeline(workspace_file: str, session_id: str = "", task_id: str = "", limit: int = 50) -> dict[str, Any]:
    """Drill into timeline for mc_admin."""
    from ..core.navigation.drilldown import DrillDownNavigator
    with DrillDownNavigator(workspace_file) as nav:
        return nav.drill_timeline(session_id=session_id, task_id=task_id, limit=limit)


def _drill_task(workspace_file: str, task_id: str = "") -> dict[str, Any]:
    """Drill into task context for mc_admin."""
    from ..core.navigation.drilldown import DrillDownNavigator
    with DrillDownNavigator(workspace_file) as nav:
        return nav.drill_task(task_id)


def _backend_consistency(workspace_file: str) -> dict[str, Any]:
    """Check backend consistency for mc_admin."""
    from ..core.backend.query import UnifiedBackendQuery
    from ..core.store import WorkspaceStore
    store = WorkspaceStore(workspace_file)
    with UnifiedBackendQuery(store.memory_db_path) as backend:
        return backend.check_consistency(store.base_dir)


def _constraint_action(context: str = "", template: str = "coding_agent") -> dict[str, Any]:
    """Show constraint template or auto-select action for mc_admin."""
    from ..core.templates import auto_select_action, get_constraint_template
    if context:
        action = auto_select_action(context, template)
        return {"context": context, "template": template, "recommended_action": action}
    tmpl = get_constraint_template(template)
    return tmpl or {"error": f"Unknown template: {template}"}

def _build_context_pack_recommendation(wf: str, intent: str, sniff_result: dict) -> dict:
    """D-02: Recommend context pack based on intent and risk level."""
    risk = sniff_result.get("risk_level", "low")
    intent_lower = intent.lower()
    arch_keywords = {"architecture", "design", "refactor", "migrate", "module", "service", "struct", "设计", "架构", "重构", "迁移"}
    change_keywords = {"change", "modify", "fix", "update", "impact", "affect", "break", "修改", "变更", "影响"}
    is_arch = any(k in intent_lower for k in arch_keywords)
    is_change = any(k in intent_lower for k in change_keywords) or risk in ("medium", "high")
    recommended = is_arch or is_change
    if not recommended:
        return {"recommended": False, "reason": "Intent does not suggest architecture or change-impact questions."}
    reason = "Architecture understanding intent" if is_arch else "Change-impact or elevated risk detected"
    return {
        "recommended": True,
        "reason": reason,
        "tool": "mc_context_pack",
        "suggested_query": intent,
        "suggested_budget": "medium" if risk == "low" else "large",
    }


def _mcp_error_boundary(fn):
    """Wrap an MCP tool without changing its registered schema."""
    if inspect.iscoroutinefunction(fn):
        @wraps(fn)
        async def async_wrapped(*args, **kwargs):
            try:
                return await fn(*args, **kwargs)
            except Exception as exc:
                return normalize_exception(exc).to_mcp_dict()

        return async_wrapped

    @wraps(fn)
    def wrapped(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            return normalize_exception(exc).to_mcp_dict()

    return wrapped


def _safe_mcp_tool(mcp):
    """Register an MCP tool with the unified error boundary."""
    def decorator(fn):
        return mcp.tool()(_mcp_error_boundary(fn))

    return decorator


def create_server(workspace_file: str):
    try:
        from mcp.server.fastmcp import FastMCP
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("Please install MCP dependency: pip install -e .[mcp]") from exc

    ctx = _WorkspaceContext(workspace_file)
    mcp = FastMCP("Memory Center")

    # Import workflow templates for guidance
    from memory_center.core.templates import get_workflow_guidance

    # ===================== FACADE 1: mc_start =====================
    @_safe_mcp_tool(mcp)
    def mc_start(
        intent: str,
        limit: int = 12,
        auto_sync_mode: str = "balanced",
        sync_task_space: bool = True,
        budget: str = "medium",
    ):
        """Start a new task workflow. Sniffs workspace context, optionally syncs to task space, and starts a session. Returns consolidated context with services, files, rules, risk level, session_id, and task_id."""
        wf = ctx.workspace_file
        sniff_result = workspace_sniff(wf, intent, limit=limit, auto_sync_mode=auto_sync_mode, view="compact", budget=budget)
        synced = None
        resolved_task = sniff_result.get("resolved_task", {}) or {}
        auto_sync = sniff_result.get("auto_sync_recommendation", {}) or {}
        if sync_task_space and (auto_sync.get("recommended") or resolved_task.get("task_id")):
            synced = workspace_sync_sniff_to_artifacts(
                wf, intent, limit=limit,
                task_id=str(resolved_task.get("task_id", "") or ""),
                title=str(resolved_task.get("title", "") or ""),
                auto_sync_mode=auto_sync_mode,
            )
        session = workspace_start_session(wf, intent)
        guidance = get_workflow_guidance("work-start", {"risk_level": sniff_result.get("risk_level", ""), "task_id": resolved_task.get("task_id", "")})
        # D-01: Freshness enters mc_start main chain
        try:
            from memory_center.core.freshness.integration import get_freshness_with_actions
            _freshness = get_freshness_with_actions(wf)
        except Exception:
            _freshness = {"status": "unknown", "recommended_actions": [], "semantics": ""}
        # D-02: Context Pack recommendation for architecture/change intents
        _cp_rec = _build_context_pack_recommendation(wf, intent, sniff_result)
        return {"workflow": "mc-start", "sniff": sniff_result, "sync_sniff": synced, "session": session, "_workflow_guidance": guidance, "freshness": _freshness, "context_pack_recommendation": _cp_rec}

    # ===================== FACADE 2: mc_lookup =====================
    @_safe_mcp_tool(mcp)
    def mc_lookup(
        query: str,
        mode: str = "auto",
        intent: str = "",
        name: str = "",
        scope: str = "",
        symbol: str = "",
        chain_direction: str = "callers",
        depth: int = 2,
        entry: str = "",
        ref_id: str = "",
        ref_ids: list[str] | None = None,
        limit: int = 20,
        project: str = "",
        report_level: str = "standard",
        enable_vector: bool = False,
        vector_weight: float = 0.15,
    ):
        """Unified knowledge lookup. Mode selects strategy: auto (system decides via lookup_hint), symbol (resolve name), code (keyword search), query (graph-aware multi-source), trace (cross-service by class/Feign/endpoint/MQ), chain (caller/callee analysis, use chain_direction), walkthrough (method-level indexed walkthrough), context (360-degree context for a service/symbol), contracts (list all Feign/API/MQ contracts), ref (resolve short memory reference IDs). For Class#method requests that say full chain/全链路/到底层, prefer mode='walkthrough' or auto; walkthrough returns summary_lines, local_service_continuations, feign_continuations.server_walkthroughs, service_impl_continuations, and absolute_file_path. If absolute_file_path is present, read that path directly and do not run find/grep/IDEA search to locate the same controller or impl. Use project to disambiguate when multiple modules contain the same symbol name."""
        wf = ctx.workspace_file
        resolved_symbol = _extract_symbol_like_token(symbol, name, entry, query)
        resolved_depth = max(depth, 4) if _wants_deep_chain(query, intent, symbol, name, entry) else depth
        if mode == "auto":
            hint = workspace_lookup_hint(wf, query=query, intent=intent, limit=limit)
            preferred = hint.get("preferred_tools", [])
            decision_fields = {
                "lookup_hint": hint,
                "candidate_paths": hint.get("candidate_paths", []),
                "recommended_path": hint.get("recommended_candidate_path", {}),
            }
            # preferred_tools returns names with "_tool" suffix (e.g. "memory_symbol_tool")
            # Strip suffix for cleaner matching
            preferred_bare = [t.replace("_tool", "") for t in preferred]
            if _wants_deep_chain(query, intent, symbol, name, entry) and "#" in resolved_symbol:
                result = memory_method_walkthrough(wf, resolved_symbol, depth=resolved_depth, limit=limit, project=project, view="compact", budget="small", report_level=report_level)
                payload = _flatten_walkthrough_payload(result, mode_key="mode_used")
                payload["routing_note"] = "auto selected walkthrough for Class#method full-chain query; use top-level answer/summary_lines/read_targets directly."
                return payload
            if "memory_callers" in preferred_bare and resolved_symbol:
                matching_groups = _find_groups_for_workspace(wf)
                if len(matching_groups) == 1:
                    result = group_chain(matching_groups[0], resolved_symbol, direction="callers", depth=resolved_depth, limit=limit)
                    return {"mode_used": "chain-group", "result": result, **decision_fields}
                result = memory_callers(wf, resolved_symbol, resolved_depth, limit, project=project, view="compact", budget="small")
                _annotate_phantom_nodes(result, wf)
                if len(matching_groups) > 1:
                    return {"mode_used": "chain-callers", "result": result, "matching_groups": matching_groups, "_hint": f"Workspace 属于多个 group ({', '.join(matching_groups)})，请用 mc_admin(action='group_chain', group=...) 显式指定。", **decision_fields}
                return {"mode_used": "chain-callers", "result": result, **decision_fields}
            if "memory_callees" in preferred_bare and resolved_symbol:
                matching_groups = _find_groups_for_workspace(wf)
                if len(matching_groups) == 1:
                    result = group_chain(matching_groups[0], resolved_symbol, direction="callees", depth=resolved_depth, limit=limit)
                    return {"mode_used": "chain-group", "result": result, **decision_fields}
                result = memory_callees(wf, resolved_symbol, resolved_depth, limit, project=project, view="compact", budget="small")
                _annotate_phantom_nodes(result, wf)
                if len(matching_groups) > 1:
                    return {"mode_used": "chain-callees", "result": result, "matching_groups": matching_groups, "_hint": f"Workspace 属于多个 group ({', '.join(matching_groups)})，请用 mc_admin(action='group_chain', group=...) 显式指定。", **decision_fields}
                return {"mode_used": "chain-callees", "result": result, **decision_fields}
            if "memory_symbol" in preferred_bare and (name or resolved_symbol or query):
                return {"mode_used": "symbol", "result": memory_symbol(wf, name or resolved_symbol or query, limit, project=project, view="compact", budget="small"), **decision_fields}
            if "memory_search_code" in preferred_bare:
                return {"mode_used": "code", "result": memory_search_code(wf, query, scope, limit, project=project), **decision_fields}
            if "memory_context" in preferred_bare and (name or resolved_symbol or query):
                return {"mode_used": "context", "result": memory_context(wf, name or resolved_symbol or query, resolved_depth, project=project, view="compact", budget="small"), **decision_fields}
            if "workspace_trace" in preferred_bare and (entry or resolved_symbol or query):
                return {"mode_used": "trace", "result": workspace_trace(wf, entry or resolved_symbol or query), **decision_fields}
            return {
                "mode_used": "query",
                "result": memory_query_hybrid(
                    wf,
                    query,
                    limit,
                    project=project,
                    enable_vector=enable_vector,
                    vector_weight=vector_weight,
                ),
                **decision_fields,
            }
        if mode == "symbol":
            return {"mode": "symbol", "result": memory_symbol(wf, name or query, limit, project=project, view="compact", budget="small")}
        if mode == "code":
            return {"mode": "code", "result": memory_search_code(wf, query, scope, limit, project=project)}
        if mode == "query":
            return {
                "mode": "query",
                "result": memory_query_hybrid(
                    wf,
                    query,
                    limit,
                    project=project,
                    enable_vector=enable_vector,
                    vector_weight=vector_weight,
                ),
            }
        if mode == "trace":
            return {"mode": "trace", "result": workspace_trace(wf, entry or query)}
        if mode == "chain":
            cross_types = ["CALLS_SERVICE", "IMPLEMENTS_FEIGN"] if scope == "cross-service" else None
            matching_groups = _find_groups_for_workspace(wf)
            if len(matching_groups) == 1:
                result = group_chain(matching_groups[0], symbol or query,
                                      direction=chain_direction, depth=depth, limit=limit)
                return {"mode": "chain-group", "result": result}
            if len(matching_groups) > 1:
                if chain_direction == "callees":
                    result = memory_callees(wf, symbol or query, depth, limit, edge_type_filter=cross_types, project=project, view="compact", budget="small")
                else:
                    result = memory_callers(wf, symbol or query, depth, limit, edge_type_filter=cross_types, project=project, view="compact", budget="small")
                _annotate_phantom_nodes(result, wf)
                return {
                    "mode": f"chain-{chain_direction}",
                    "result": result,
                    "matching_groups": matching_groups,
                    "_hint": f"Workspace 属于多个 group ({', '.join(matching_groups)})，请用 mc_admin(action='group_chain', group=...) 显式指定。",
                }
            if chain_direction == "callees":
                result = memory_callees(wf, symbol or query, depth, limit, edge_type_filter=cross_types, project=project, view="compact", budget="small")
            else:
                result = memory_callers(wf, symbol or query, depth, limit, edge_type_filter=cross_types, project=project, view="compact", budget="small")
            _annotate_phantom_nodes(result, wf)
            return {"mode": f"chain-{chain_direction}", "result": result}
        if mode == "walkthrough":
            result = memory_method_walkthrough(wf, symbol or resolved_symbol or query, depth=depth, limit=limit, project=project, view="compact", budget="small", report_level=report_level)
            return _flatten_walkthrough_payload(result, mode_key="mode")
        if mode == "context":
            return {"mode": "context", "result": memory_context(wf, name or query, depth, project=project, view="compact", budget="small")}
        if mode == "contracts":
            return {"mode": "contracts", "result": memory_contracts(wf)}
        if mode == "ref":
            if ref_ids:
                return {"mode": "ref-batch", "result": memory_ref_batch(wf, ref_ids)}
            return {"mode": "ref-get", "result": memory_ref_get(wf, ref_id=ref_id)}
        if mode == "backend":
            return {"mode": "backend", "result": memory_backend_query(wf, collection="", record_id="", created_after="", ref_path="", project=scope, payload_type="", limit=limit)}
        raise ValueError(f"Unknown mc_lookup mode: {mode}. Valid: auto, symbol, code, query, trace, chain, walkthrough, context, contracts, ref, backend")

    # ===================== FACADE 3: mc_analyze =====================
    @_safe_mcp_tool(mcp)
    def mc_analyze(
        target: str,
        depth: str = "standard",
        direction: str = "upstream",
        max_depth: int = 3,
        project: str = "",
        contract_file: str = "",
        change_type: str = "modify",
        projects: list[str] | None = None,
        files: list[str] | None = None,
        scope: str = "staged",
    ):
        """Analyze change impact and generate action plans. Depth quick: impact only. Depth standard: impact + change plan + rules check. Depth full: standard + contract check + verification checklist. If target is empty, runs detect-changes instead of impact."""
        wf = ctx.workspace_file
        project_filter = project or ((projects or [None])[0] or "")
        if target:
            impact_result = memory_impact(wf, target, direction, max_depth, project=project_filter, view="compact", budget="small")
        else:
            impact_result = memory_detect_changes(wf, scope)
        result = {"workflow": "mc-analyze", "depth": depth, "impact": impact_result}
        if target:
            result["candidate_paths"] = impact_result.get("candidate_paths", [])
            result["recommended_path"] = impact_result.get("recommended_path", {})
        if depth in ("standard", "full") and target:
            result["plan"] = memory_plan_change(wf, target, direction, max_depth)
            result["rules"] = workspace_check_rules(wf, projects, change_type, files)
        if depth == "full" and target:
            if contract_file:
                result["contract"] = workspace_check_contract(wf, contract_file, change_type)
            result["checklist"] = memory_verify_checklist(wf, target)
        return result

    # ===================== FACADE 4: mc_sync =====================
    @_safe_mcp_tool(mcp)
    def mc_sync(
        intent: str = "",
        session_id: str = "",
        task_id: str = "",
        title: str = "",
        limit: int = 12,
        auto_sync_mode: str = "balanced",
    ):
        """Sync task context to workspace artifacts. Provide intent for sniff-sync, or session_id for case-sync. session_id takes precedence if both provided."""
        wf = ctx.workspace_file
        if session_id.strip():
            return {"workflow": "mc-sync", "mode": "case", "result": workspace_sync_case_to_artifacts(wf, session_id, task_id=task_id, title=title, auto_sync_mode=auto_sync_mode)}
        if intent.strip():
            return {"workflow": "mc-sync", "mode": "sniff", "result": workspace_sync_sniff_to_artifacts(wf, intent, limit=limit, task_id=task_id, title=title, auto_sync_mode=auto_sync_mode)}
        raise ValueError("mc_sync requires intent or session_id")

    # ===================== FACADE 5: mc_resume =====================
    @_safe_mcp_tool(mcp)
    def mc_resume(
        intent: str = "",
        task_id: str = "",
        session_id: str = "",
        limit: int = 8,
        budget: str = "medium",
    ):
        """Resume a task with consolidated context. Returns resume packet, next actions, unresolved items, and recent evidence. Provide intent, task_id, or session_id to focus the resume."""
        wf = ctx.workspace_file
        return {
            "workflow": "mc-resume",
            "resume_packet": workspace_resume_packet(wf, task_id=task_id, session_id=session_id, intent=intent, limit=limit, view="compact", budget=budget),
            "next_actions": workspace_next_actions(wf, task_id=task_id, session_id=session_id, intent=intent, limit=limit),
            "unresolved_items": workspace_unresolved_items(wf, task_id=task_id, session_id=session_id, intent=intent, limit=limit),
            "recent_evidence": workspace_recent_evidence(wf, task_id=task_id, session_id=session_id, limit=min(limit, 5), budget=budget, view="compact"),
        }

    # ===================== FACADE 6: mc_handoff =====================
    @_safe_mcp_tool(mcp)
    def mc_handoff(
        target_model: str,
        task_id: str = "",
        session_id: str = "",
        intent: str = "",
        limit: int = 8,
        budget: str = "medium",
    ):
        """Build a handoff package for another model or session. Returns handoff packet, recent evidence, and tool usage report. Essential for multi-model workflows and context transfer."""
        wf = ctx.workspace_file
        return {
            "workflow": "mc-handoff",
            "handoff_packet": workspace_handoff_packet(wf, target_model=target_model, task_id=task_id, session_id=session_id, intent=intent, limit=limit, view="compact", budget=budget),
            "recent_evidence": workspace_recent_evidence(wf, task_id=task_id, session_id=session_id, limit=min(limit, 5), budget=budget, view="compact"),
            "tool_usage_report": memory_tool_usage_report(wf, limit=50),
        }

    # ===================== FACADE 7: mc_close =====================
    @_safe_mcp_tool(mcp)
    def mc_close(
        session_id: str,
        outcome: str = "",
        task_id: str = "",
        title: str = "",
        auto_sync_mode: str = "balanced",
        record_case: bool = True,
        verified_by: list[str] | None = None,
    ):
        """Close a task workflow. Ends session, syncs case to artifacts, suggests case record, and optionally records it to cross-service memory."""
        wf = ctx.workspace_file
        ended = workspace_end_session(wf, session_id, outcome, verified_by)
        synced = workspace_sync_case_to_artifacts(wf, session_id, task_id=task_id, title=title, auto_sync_mode=auto_sync_mode)
        draft = workspace_suggest_case(wf, session_id)
        recorded = None
        candidate_feedback = None
        case = draft.get("draft_case", {}) if draft.get("found") else {}
        if record_case and case.get("projects") and case.get("files"):
            recorded = workspace_record_case(
                wf, case.get("task", outcome or "mc-close"),
                case.get("projects", []), case.get("files", []),
                case.get("flow", ""), case.get("risk_points", []),
                verified_by=case.get("verified_by", []) or verified_by,
                source_session_id=session_id, source_task_id=task_id,
            )
        candidate_feedback = workspace_record_close_feedback(
            wf,
            session_id,
            task_id=task_id,
            source="mc_close_auto",
        )
        return {
            "workflow": "mc-close",
            "ended": ended,
            "sync_case": synced,
            "suggested_case": draft,
            "record_case": recorded,
            "candidate_feedback": candidate_feedback,
        }

    # ===================== FACADE 8: mc_admin =====================
    @_safe_mcp_tool(mcp)
    def mc_admin(
        action: str,
        view: str = "compact",
        budget: str = "medium",
        limit: int = 10,
        name: str = "",
        content: str = "",
        task_id: str = "",
        title: str = "",
        intent: str = "",
        owner: str = "",
        tags: list[str] | None = None,
        priority: str = "medium",
        status: str = "",
        source: str = "",
        reason: str = "",
        include_archived: bool = False,
        create_if_missing: bool = True,
        score_threshold: int = 3,
        limit_candidates: int = 3,
        entry: str = "",
        keep_recent: int = 30,
        session_id: str = "",
        event_type: str = "",
        payload: str = "",
        outcome: str = "",
        verified_by: list[str] | None = None,
        target_model: str = "codex",
        scope: str = "all",
        tool_name: str = "",
        model: str = "",
        text: str = "",
        prefer_layer: str = "",
        projects: list[str] | None = None,
        files: list[str] | None = None,
        group: str = "",
        direction: str = "upstream",
        max_depth: int = 3,
        output_dir: str = "",
        collection: str = "",
        record_id: str = "",
        created_after: str = "",
        ref_path: str = "",
        project: str = "",
        payload_type: str = "",
        layer: str = "",
        action_filter: str = "",
        force: bool = False,
    ):
        """Admin and utility operations. Action selects sub-operation: status, dashboard, continuity, health, audit, discover, constraint, drill_ref, drill_timeline, drill_task, backend_consistency, artifact_list, artifact_get, artifact_outline, artifact_context, artifact_update, change_log_append, change_log_compact, task_create, task_list, task_health, task_health_all, task_repair_plan, task_resume_check, task_resolve, task_get, task_update, task_change_log_append, task_archive, task_auto_archive, task_status, task_activity_touch, session_start, session_log, session_end, session_recent, session_summary, model_profile, handoff_history, write_judge, write_plan, write_execute, receipts, replay, backend_query, eval_write_quality, eval_resume, eval_handoff, eval_regression_suite, eval_index_freshness, eval_tool_adoption, eval_context_weight, eval_workflow_orchestration, eval_token_gain, eval_parser_benchmark, eval_java_call_resolution, eval_token_benchmark, eval_token_benchmark_trend, tool_usage_report, generate_wiki, generate_skills, group_status, group_query, group_impact, group_chain, method_walkthrough, walkthrough_health, walkthrough_export, eval_walkthrough_quality."""
        wf = ctx.workspace_file
        from memory_center.mcp.admin_actions import build_admin_registry
        registry = build_admin_registry(
            workspace_file=wf,
            action=action,
            view=view,
            budget=budget,
            limit=limit,
            name=name,
            content=content,
            task_id=task_id,
            title=title,
            intent=intent,
            owner=owner,
            tags=tags,
            priority=priority,
            status=status,
            source=source,
            reason=reason,
            include_archived=include_archived,
            create_if_missing=create_if_missing,
            score_threshold=score_threshold,
            limit_candidates=limit_candidates,
            entry=entry,
            keep_recent=keep_recent,
            session_id=session_id,
            event_type=event_type,
            payload=payload,
            outcome=outcome,
            verified_by=verified_by,
            target_model=target_model,
            scope=scope,
            tool_name=tool_name,
            model=model,
            text=text,
            prefer_layer=prefer_layer,
            projects=projects,
            files=files,
            group=group,
            direction=direction,
            max_depth=max_depth,
            output_dir=output_dir,
            collection=collection,
            record_id=record_id,
            created_after=created_after,
            ref_path=ref_path,
            project=project,
            payload_type=payload_type,
            layer=layer,
            action_filter=action_filter,
            force=force,
        )
        return {"action": action, "result": registry.dispatch(action)}

    # ===================== Resources (unchanged) =====================
    @mcp.resource("memory-center://status")
    def status_resource():
        return workspace_status(ctx.workspace_file)

    @mcp.resource("memory-center://startup-diagnostics")
    def startup_diagnostics_resource():
        return ctx.startup_diagnostics

    @mcp.resource("memory-center://contracts")
    def contracts_resource():
        return memory_contracts(ctx.workspace_file)

    @mcp.resource("memory-center://topology")
    def topology_resource():
        return workspace_status(ctx.workspace_file).get("topology", {})

    # ===================== Prompts (updated tool names) =====================
    @mcp.prompt()
    def detect_impact(target: str) -> str:
        return (
            "Use Memory Center before editing. Call mc_analyze for the target "
            "to get impact analysis, change plan, and rules check. "
            f"Target: {target}"
        )

    @mcp.prompt()
    def spring_cloud_safe_change(task: str) -> str:
        return (
            "For this Spring Cloud task, call mc_start first. "
            "Then use mc_lookup or mc_analyze for important contracts. "
            "Use mc_sync to save progress, and mc_close when done. "
            f"Task: {task}"
        )

    @mcp.prompt()
    def onboard_new_dev(scope: str = "workspace") -> str:
        return (
            "You are onboarding a new developer to this project. "
            "Call mc_onboard with persona='developer' to get a guided "
            "architecture tour. Then call mc_domain to understand business "
            "domains and flows. Finally call mc_freshness to check if "
            "the index is up to date."
        )

    @mcp.prompt()
    def check_mq_safety(topic: str = "") -> str:
        base = (
            "Check MQ consumer safety for this project. "
            "Call mc_lookup to find MQ consumers and topics. "
            "Verify each consumer has idempotent handling. "
            "Check message format compatibility. "
        )
        return base + (f"Focus topic: {topic}" if topic else "Check all MQ consumers in the workspace.")

    @mcp.prompt()
    def analyze_dto_impact(dto_class: str = "") -> str:
        base = (
            "Analyze the impact of changing a DTO class. "
            "Call mc_analyze to get the full impact analysis. "
            "Check serialization compatibility, MQ message bodies, "
            "and Feign client contracts. "
        )
        return base + (f"Target DTO: {dto_class}" if dto_class else "Analyze all DTOs in the workspace.")

    @mcp.prompt()
    def cross_service_trace(service: str = "") -> str:
        base = (
            "Trace cross-service call chains. "
            "If the input contains Class#method or asks for full chain/全链路/到底层, call mc_lookup with mode='walkthrough' first. "
            "Use mode='chain' only for generic caller/callee graph exploration. "
            "For walkthrough results, follow summary_lines, local_service_continuations, feign_continuations.server_walkthroughs, and service_impl_continuations. "
            "When absolute_file_path is present, read that path directly; do not run find/grep/IDEA search to locate the same controller or impl. "
            "Then map Feign clients, MQ producers/consumers, and shared configs as needed. "
        )
        return base + (f"Starting from: {service}" if service else "Trace all cross-service interactions.")

    @mcp.prompt()
    def config_propagation_check(key: str = "") -> str:
        base = (
            "Check configuration key propagation across services. "
            "Call mc_lookup to find ConfigKey nodes. "
            "Identify which services read the same config keys. "
            "Flag potential configuration drift. "
        )
        return base + (f"Focus key: {key}" if key else "Check all shared configuration keys.")

    @mcp.prompt()
    def freshness_check() -> str:
        return (
            "Check index freshness before making code changes. "
            "Call mc_freshness to see if the graph index is up to date. "
            "If status is 'pending' or 'stale', read live files before editing. "
            "Never edit based on stale index data."
        )

    @mcp.prompt()
    def domain_overview() -> str:
        return (
            "Get a business domain overview of this project. "
            "Call mc_domain to extract business domains and flows. "
            "Understand how code maps to business concepts. "
            "Use this for product/business stakeholder discussions."
        )

    @mcp.prompt()
    def diff_impact_analysis(diff_summary: str = "") -> str:
        base = (
            "Analyze the impact of a git diff. "
            "Call mc_context_pack to get a compact context package. "
            "Then call mc_analyze for detailed impact analysis. "
            "Generate a change checklist with risk assessment. "
        )
        return base + (f"Diff summary: {diff_summary}" if diff_summary else "Analyze the current working tree changes.")

    # ===================== FACADE 9-12: V3 MCP Tools (§20.6) =====================

    @_safe_mcp_tool(mcp)
    def mc_context_pack(
        query: str,
        intent: str = "auto",
        budget_tokens: int = 8000,
        limit: int = 10,
    ):
        """Return a compact, evidence-backed context package for coding agents. Assembles entrypoints, relationships, risk patterns, and checklist into a single response to reduce agent grep/read cycles. Use this before mc_lookup for architecture or change-impact questions."""
        from memory_center.core.context.pack import ContextPackBuilder
        wf = ctx.workspace_file
        builder = ContextPackBuilder(wf)
        pack = builder.build(query=query, intent=intent, budget_tokens=budget_tokens, limit=limit)
        return {
            "workflow": "mc-context-pack",
            "query": pack.query,
            "intent": pack.intent,
            "entrypoints": pack.entrypoints,
            "relationships": pack.relationships[:20],
            "snippets": pack.snippets,
            "risks": pack.risks,
            "checklist": pack.checklist,
            "freshness": pack.freshness,
            "token_estimate": pack.token_estimate,
            "progressive": pack.progressive,
        }

    @_safe_mcp_tool(mcp)
    def mc_onboard(
        scope: str = "workspace",
        persona: str = "developer",
        target: str = "",
    ):
        """Generate a guided architecture tour for onboarding. persona: developer | architect | product | tester. Returns step-by-step walkthrough of the project structure."""
        from memory_center.core.onboarding.tour import ArchitectureTourGenerator
        from memory_center.core.storage.unified import UnifiedStore
        wf = ctx.workspace_file
        store = WorkspaceStore(wf)
        db_path = store.graph_db_path
        unified = UnifiedStore(db_path)
        try:
            gen = ArchitectureTourGenerator(unified)
            tour = gen.generate_tour(persona=persona, scope=scope, target=target or None)
            return {"workflow": "mc-onboard", "tour": tour.to_dict()}
        finally:
            unified.close()

    @_safe_mcp_tool(mcp)
    def mc_domain(
        scope: str = "workspace",
        include_flows: bool = True,
    ):
        """Extract business domains and business flows from the code knowledge graph. Shows how code entities map to business concepts like user management, order processing, payment, etc."""
        from memory_center.core.domain.extractor import BusinessDomainExtractor
        from memory_center.core.storage.unified import UnifiedStore
        wf = ctx.workspace_file
        store = WorkspaceStore(wf)
        db_path = store.graph_db_path
        unified = UnifiedStore(db_path)
        try:
            extractor = BusinessDomainExtractor(unified)
            domains = extractor.extract_domains()
            result = {
                "workflow": "mc-domain",
                "domains": [d.to_dict() for d in domains],
                "domain_count": len(domains),
            }
            if include_flows:
                flows = extractor.extract_flows()
                result["flows"] = [f.to_dict() for f in flows]
                result["flow_count"] = len(flows)
            return result
        finally:
            unified.close()

    @_safe_mcp_tool(mcp)
    def mc_freshness(
        scope: str = "workspace",
    ):
        """Return index freshness status. If pending files affect the query target, instruct the agent to read the live file before editing."""
        from memory_center.core.freshness.status import IndexFreshnessService
        wf = ctx.workspace_file
        svc = IndexFreshnessService(wf)
        banner = svc.banner()
        return {"workflow": "mc-freshness", **banner}

    return mcp


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", default=".", help="Path to workspace.yaml or a project directory")
    args = parser.parse_args()
    server = create_server(args.workspace)
    server.run()


if __name__ == "__main__":
    main()
