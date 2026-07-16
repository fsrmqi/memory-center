"""Capability matrix mapping each feature to its CLI / HTTP / MCP entry points.

This module is a single source of truth for "which entry covers which capability".
Tests import this matrix to verify coverage and to catch unintentional gaps.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EntryPoint:
    """One entry point for a capability."""
    kind: str          # "cli", "http", "mcp_tool", "mcp_admin_action"
    identifier: str    # CLI command name, HTTP path, MCP tool name, or mc_admin action


@dataclass(frozen=True)
class Capability:  # noqa: UP006 – keep explicit generics for Py 3.9 compat
    """A user-facing capability with its entry-point coverage."""
    name: str
    core_fields: list[str] = field(default_factory=list)
    error_semantics: str = ""
    entries: list[EntryPoint] = field(default_factory=list)


def _cli(cmd: str) -> EntryPoint:
    return EntryPoint(kind="cli", identifier=cmd)


def _http(path: str) -> EntryPoint:
    return EntryPoint(kind="http", identifier=path)


def _mcp_tool(name: str) -> EntryPoint:
    return EntryPoint(kind="mcp_tool", identifier=name)


def _mcp_admin(action: str) -> EntryPoint:
    return EntryPoint(kind="mcp_admin_action", identifier=action)


# ---------------------------------------------------------------------------
# The 14 capabilities required by B-01
# ---------------------------------------------------------------------------

CAPABILITIES: list[Capability] = [
    Capability(
        name="context-pack",
        core_fields=["workflow", "query", "intent", "entrypoints", "relationships",
                      "snippets", "risks", "checklist", "freshness", "token_estimate"],
        error_semantics="empty workspace -> diagnostics with status; builder failure -> diagnostics with safe_reason",
        entries=[_http("/workspace/context-pack"), _mcp_tool("mc_context_pack")],
    ),
    Capability(
        name="freshness",
        core_fields=["workflow", "banner", "freshness"],
        error_semantics="missing workspace -> error dict with status=not_found",
        entries=[_http("/workspace/freshness"), _mcp_tool("mc_freshness")],
    ),
    Capability(
        name="onboard",
        core_fields=["workflow", "tour"],
        error_semantics="missing workspace -> error dict; unsupported persona -> empty tour",
        entries=[_http("/workspace/onboard"), _mcp_tool("mc_onboard")],
    ),
    Capability(
        name="domain",
        core_fields=["workflow", "domains", "domain_count"],
        error_semantics="missing graph -> empty domains list with diagnostics",
        entries=[_mcp_tool("mc_domain")],
    ),
    Capability(
        name="business-flow",
        core_fields=["flows", "flow_count"],
        error_semantics="missing workspace -> error dict; no seed -> empty flows",
        entries=[
            _cli("business-flow"),
            _http("/workspace/business-flow"),
            _mcp_admin("business_flow"),
        ],
    ),
    Capability(
        name="business-flow-impact",
        core_fields=["impact", "flow_impact"],
        error_semantics="missing node_id -> error; node not found -> empty impact",
        entries=[
            _cli("business-flow-impact"),
            _http("/workspace/business-flow-impact"),
            _mcp_admin("business_flow_impact"),
        ],
    ),
    Capability(
        name="verification-loop",
        core_fields=["checklist", "status"],
        error_semantics="missing intent -> uses default; loop failure -> diagnostics",
        entries=[
            _cli("verification-loop"),
            _http("/workspace/verification-loop"),
            _mcp_admin("verification_loop"),
        ],
    ),
    Capability(
        name="workflow-profile",
        core_fields=["name", "description", "steps", "applicable_when", "tools_sequence"],
        error_semantics="unknown profile name -> error with valid options",
        entries=[
            _cli("workflow-profile"),
            _http("/workspace/workflow-profile"),
            _mcp_admin("workflow_profile"),
        ],
    ),
    Capability(
        name="runtime-audit",
        core_fields=["audit_record", "findings", "quality", "score"],
        error_semantics="missing hooks.yaml -> empty audit with diagnostics",
        entries=[
            _cli("runtime-audit"),
            _http("/workspace/runtime-audit"),
            _mcp_admin("runtime_audit"),
        ],
    ),
    Capability(
        name="regression-alerts",
        core_fields=["alerts", "total_regressions", "critical_count", "warning_count", "health"],
        error_semantics="missing benchmark data -> empty alerts",
        entries=[
            _cli("regression-alerts"),
            _http("/workspace/regression-alerts"),
            _mcp_admin("regression_alerts"),
        ],
    ),
    Capability(
        name="parser-benchmark",
        core_fields=["workspace", "files_scanned", "projects", "tree_sitter", "summary", "regressions", "improvements", "score", "quality"],
        error_semantics="tree-sitter unavailable -> diagnostics in tree_sitter; no Java files -> empty status",
        entries=[
            _cli("eval-parser-benchmark"),
            _http("/workspace/eval-parser-benchmark"),
            _mcp_admin("eval_parser_benchmark"),
        ],
    ),
    Capability(
        name="java-call-resolution",
        core_fields=["summary", "thresholds", "cases"],
        error_semantics="missing graph/cases -> validation error; unresolved calls -> explicit unresolved_rate",
        entries=[
            _cli("eval-java-call-resolution"),
            _http("/workspace/eval-java-call-resolution"),
            _mcp_admin("eval_java_call_resolution"),
        ],
    ),
    Capability(
        name="backend-consistency",
        core_fields=["consistent", "comparisons", "divergences"],
        error_semantics="missing memory.db or JSONL -> diagnostics",
        entries=[
            _cli("backend-consistency"),
            _http("/workspace/backend-consistency"),
            _mcp_admin("backend_consistency"),
        ],
    ),
    Capability(
        name="drill-ref",
        core_fields=["ref", "content", "summary"],
        error_semantics="missing ref_path -> error; ref not found -> not_found",
        entries=[
            _cli("drill-ref"),
            _http("/workspace/drill-ref"),
            _mcp_admin("drill_ref"),
        ],
    ),
    Capability(
        name="drill-timeline",
        core_fields=["events", "event_count"],
        error_semantics="no events -> empty list; missing session_id uses recent",
        entries=[
            _cli("drill-timeline"),
            _http("/workspace/drill-timeline"),
            _mcp_admin("drill_timeline"),
        ],
    ),
    Capability(
        name="drill-task",
        core_fields=["task", "artifacts", "history"],
        error_semantics="missing task_id -> error; task not found -> not_found",
        entries=[
            _cli("drill-task"),
            _http("/workspace/drill-task"),
            _mcp_admin("drill_task"),
        ],
    ),
]

# Convenient look-up by capability name
CAPABILITY_MAP: dict[str, Capability] = {c.name: c for c in CAPABILITIES}


def entries_by_kind(capability_name: str) -> dict[str, list[str]]:
    """Return a dict of kind -> list of identifiers for a capability."""
    cap = CAPABILITY_MAP.get(capability_name)
    if cap is None:
        return {}
    result: dict[str, list[str]] = {}
    for e in cap.entries:
        result.setdefault(e.kind, []).append(e.identifier)
    return result


def all_cli_commands() -> list[str]:
    """Return sorted unique CLI command names across all capabilities."""
    cmds = set()
    for cap in CAPABILITIES:
        for e in cap.entries:
            if e.kind == "cli":
                cmds.add(e.identifier)
    return sorted(cmds)


def all_http_routes() -> list[str]:
    """Return sorted unique HTTP routes across all capabilities."""
    routes = set()
    for cap in CAPABILITIES:
        for e in cap.entries:
            if e.kind == "http":
                routes.add(e.identifier)
    return sorted(routes)


def all_mcp_tools() -> list[str]:
    """Return sorted unique MCP tool names across all capabilities."""
    tools = set()
    for cap in CAPABILITIES:
        for e in cap.entries:
            if e.kind == "mcp_tool":
                tools.add(e.identifier)
    return sorted(tools)


def all_mcp_admin_actions() -> list[str]:
    """Return sorted unique mc_admin action names across all capabilities."""
    actions = set()
    for cap in CAPABILITIES:
        for e in cap.entries:
            if e.kind == "mcp_admin_action":
                actions.add(e.identifier)
    return sorted(actions)
