"""B-01 (4.x) capability matrix: features, core fields and error semantics.

.. warning::

   **This is a historical contract matrix, not the 5.0 entry-point registry.**

   ``core_fields`` and ``error_semantics`` are still the canonical description
   of what each capability returns and how it degrades, and regression tests
   assert them. The ``entries`` column, however, is only partly live:

   ======================  =====================================================
   kind                    5.0 status
   ======================  =====================================================
   ``mcp_admin_action``    **live** — registered by
                           ``application.admin.build_admin_registry()``
   ``http``                legacy — ``/workspace/*`` paths were replaced by
                           ``/api/v1/*`` routers in ``service/``
   ``mcp_tool``            legacy — ``mc_context_pack`` / ``mc_freshness`` /
                           ``mc_onboard`` / ``mc_domain`` are not on the
                           5.0 tool surface (see ``service/platform_mcp.py``)
   ``cli``                 retired — ``memory-center`` has no subcommands at
                           all; it only launches the service. No ``cli``
                           entries remain in this matrix.
   ======================  =====================================================

   For the real 5.0 surfaces use ``service/platform_mcp.register_tools`` (MCP
   tools), ``service/*_routes.py`` (HTTP) and ``application.admin`` (admin
   actions). Never add a ``cli`` entry here: ``tests/entrypoints/
   test_capability_matrix.py`` asserts there are none.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EntryPoint:
    """One entry point for a capability."""
    kind: str          # "http", "mcp_tool" or "mcp_admin_action" (see module docstring)
    identifier: str    # HTTP path, MCP tool name, or mc_admin action


@dataclass(frozen=True)
class Capability:  # noqa: UP006 – keep explicit generics for Py 3.9 compat
    """A user-facing capability with its entry-point coverage."""
    name: str
    core_fields: list[str] = field(default_factory=list)
    error_semantics: str = ""
    entries: list[EntryPoint] = field(default_factory=list)


def _http(path: str) -> EntryPoint:
    return EntryPoint(kind="http", identifier=path)


def _mcp_tool(name: str) -> EntryPoint:
    return EntryPoint(kind="mcp_tool", identifier=name)


def _mcp_admin(action: str) -> EntryPoint:
    return EntryPoint(kind="mcp_admin_action", identifier=action)


# Which declared kinds are still wired to a real 5.0 entry point. Tests use
# these sets to turn "this matrix is partly historical" into an assertion:
# LIVE entries must resolve against the real registry, and nothing outside
# LIVE | LEGACY may be declared without a deliberate contract change.
LIVE_ENTRY_KINDS: frozenset[str] = frozenset({"mcp_admin_action"})
LEGACY_ENTRY_KINDS: frozenset[str] = frozenset({"http", "mcp_tool"})
DECLARED_ENTRY_KINDS: frozenset[str] = LIVE_ENTRY_KINDS | LEGACY_ENTRY_KINDS


# ---------------------------------------------------------------------------
# The B-01 capability contracts (18 entries, 14 of them required by the suite)
# ---------------------------------------------------------------------------

CAPABILITIES: list[Capability] = [
    Capability(
        name="change-review",
        core_fields=["workflow", "status", "scope_checked", "refresh", "summary", "actions", "invocation_budget"],
        error_semantics="no changes -> no_changes; refresh failure -> stale/unknown evidence with fallback",
        entries=[
            _http("/workspace/change-review"),
            _mcp_admin("change_review"),
        ],
    ),
    Capability(
        name="cochange-evaluation",
        core_fields=["benchmark", "ground_truth_mode", "algorithm_version", "status", "summary"],
        error_semantics="git execution failures -> environment_error and excluded from aggregates",
        entries=[
            _http("/workspace/eval-cochange"),
            _mcp_admin("eval_cochange"),
        ],
    ),
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
            _http("/workspace/business-flow"),
            _mcp_admin("business_flow"),
        ],
    ),
    Capability(
        name="business-flow-impact",
        core_fields=["impact", "flow_impact"],
        error_semantics="missing node_id -> error; node not found -> empty impact",
        entries=[
            _http("/workspace/business-flow-impact"),
            _mcp_admin("business_flow_impact"),
        ],
    ),
    Capability(
        name="verification-loop",
        core_fields=["checklist", "status"],
        error_semantics="missing intent -> uses default; loop failure -> diagnostics",
        entries=[
            _http("/workspace/verification-loop"),
            _mcp_admin("verification_loop"),
        ],
    ),
    Capability(
        name="workflow-profile",
        core_fields=["name", "description", "steps", "applicable_when", "tools_sequence"],
        error_semantics="unknown profile name -> error with valid options",
        entries=[
            _http("/workspace/workflow-profile"),
            _mcp_admin("workflow_profile"),
        ],
    ),
    Capability(
        name="runtime-audit",
        core_fields=["audit_record", "findings", "quality", "score"],
        error_semantics="missing hooks.yaml -> empty audit with diagnostics",
        entries=[
            _http("/workspace/runtime-audit"),
            _mcp_admin("runtime_audit"),
        ],
    ),
    Capability(
        name="regression-alerts",
        core_fields=["alerts", "total_regressions", "critical_count", "warning_count", "health"],
        error_semantics="missing benchmark data -> empty alerts",
        entries=[
            _http("/workspace/regression-alerts"),
            _mcp_admin("regression_alerts"),
        ],
    ),
    Capability(
        name="parser-benchmark",
        core_fields=["workspace", "files_scanned", "projects", "tree_sitter", "summary", "regressions", "improvements", "score", "quality"],
        error_semantics="tree-sitter unavailable -> diagnostics in tree_sitter; no Java files -> empty status",
        entries=[
            _http("/workspace/eval-parser-benchmark"),
            _mcp_admin("eval_parser_benchmark"),
        ],
    ),
    Capability(
        name="java-call-resolution",
        core_fields=["summary", "thresholds", "cases"],
        error_semantics="missing graph/cases -> validation error; unresolved calls -> explicit unresolved_rate",
        entries=[
            _http("/workspace/eval-java-call-resolution"),
            _mcp_admin("eval_java_call_resolution"),
        ],
    ),
    Capability(
        name="backend-consistency",
        core_fields=["consistent", "comparisons", "divergences"],
        error_semantics="missing graph.db or exported JSONL -> diagnostics",
        entries=[
            _http("/workspace/backend-consistency"),
            _mcp_admin("backend_consistency"),
        ],
    ),
    Capability(
        name="drill-ref",
        core_fields=["ref", "content", "summary"],
        error_semantics="missing ref_path -> error; ref not found -> not_found",
        entries=[
            _http("/workspace/drill-ref"),
            _mcp_admin("drill_ref"),
        ],
    ),
    Capability(
        name="drill-timeline",
        core_fields=["events", "event_count"],
        error_semantics="no events -> empty list; missing session_id uses recent",
        entries=[
            _http("/workspace/drill-timeline"),
            _mcp_admin("drill_timeline"),
        ],
    ),
    Capability(
        name="drill-task",
        core_fields=["task", "artifacts", "history"],
        error_semantics="missing task_id -> error; task not found -> not_found",
        entries=[
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
    """Return an empty list: 5.0 has no CLI subcommands.

    ``memory-center`` only launches the resident service (``service.main``
    parses --host/--port/--data-dir and friends). Kept as a compatibility
    shim for historical importers; the accompanying test asserts it stays
    empty so a phantom CLI cannot creep back in unnoticed.
    """
    return []


def all_http_routes() -> list[str]:
    """Return sorted unique HTTP routes across all capabilities (legacy paths)."""
    routes = set()
    for cap in CAPABILITIES:
        for e in cap.entries:
            if e.kind == "http":
                routes.add(e.identifier)
    return sorted(routes)


def all_mcp_tools() -> list[str]:
    """Return sorted unique MCP tool names across all capabilities (legacy names)."""
    tools = set()
    for cap in CAPABILITIES:
        for e in cap.entries:
            if e.kind == "mcp_tool":
                tools.add(e.identifier)
    return sorted(tools)


def all_mcp_admin_actions() -> list[str]:
    """Return sorted unique mc_admin action names across all capabilities (live)."""
    actions = set()
    for cap in CAPABILITIES:
        for e in cap.entries:
            if e.kind == "mcp_admin_action":
                actions.add(e.identifier)
    return sorted(actions)
