"""4.x B-01 capability **contract catalog** — fields and error semantics only.

.. warning::

   **This module is not an entry-point registry and does not declare any
   entry point.** It existed in 4.x to describe what each capability returns
   (``core_fields``) and how it degrades (``error_semantics``); regression
   tests in ``tests/regression/test_b01_behavior_matrix.py`` still assert
   those contracts against the engine functions.

   In 5.0 the 35 legacy ``entries`` declarations (17 ``/workspace/*`` HTTP
   paths, 4 ``mc_context_pack``-style tools and 14 ``mc_admin`` actions) were
   **removed**, because none of them is reachable from the service. A matrix
   that lists unreachable entry points is worse than no matrix: it invites
   callers to invent commands that do not exist.

   For the user-reachable surface use
   ``core.foundation.entry_registry.ENTRY_POINTS`` (17 MCP tools, ``/mcp``,
   ``/admin/``, ``/api/v1/*`` routes and 5 CLI launchers), which is verified
   against the running service by ``tests/entrypoints/test_entry_registry.py``.

   逐项确认归属的结论：下列 18 个 B-01 能力在 5.0 **都没有同名公开入口**。
   少数能力有「相关但不等价」的 5.0 工具（见 ``RELATED_5_0_TOOLS``），
   它们只覆盖部分查询意图，不返回 B-01 声明的完整字段集，因此不构成替代关系。
   其余能力仍是 ``core/`` 内部被回归测试覆盖的引擎能力，或已彻底退役。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Capability:  # noqa: UP006 – keep explicit generics for Py 3.9 compat
    """A B-01 engine contract: what it returns and how it degrades."""

    name: str
    core_fields: list[str] = field(default_factory=list)
    error_semantics: str = ""


# Related (not equivalent) 5.0 tools. Kept as prose-level guidance only — no
# caller should treat these as drop-in replacements for the B-01 contracts.
RELATED_5_0_TOOLS: dict[str, tuple[str, ...]] = {
    "context-pack": ("mc_lookup",),       # 不返回 token_estimate / checklist / freshness 等字段
    "freshness": ("mc_service_status",),  # 只返回就绪、版本与索引预算，没有 freshness banner
    "runtime-audit": ("mc_service_status",),  # 无 audit_record / findings / score
}


# ---------------------------------------------------------------------------
# The B-01 capability contracts (18 entries; no entry-point declarations)
# ---------------------------------------------------------------------------

CAPABILITIES: list[Capability] = [
    Capability(
        name="change-review",
        core_fields=["workflow", "status", "scope_checked", "refresh", "summary", "actions", "invocation_budget"],
        error_semantics="no changes -> no_changes; refresh failure -> stale/unknown evidence with fallback",
    ),
    Capability(
        name="cochange-evaluation",
        core_fields=["benchmark", "ground_truth_mode", "algorithm_version", "status", "summary"],
        error_semantics="git execution failures -> environment_error and excluded from aggregates",
    ),
    Capability(
        name="context-pack",
        core_fields=["workflow", "query", "intent", "entrypoints", "relationships",
                      "snippets", "risks", "checklist", "freshness", "token_estimate"],
        error_semantics="empty workspace -> diagnostics with status; builder failure -> diagnostics with safe_reason",
    ),
    Capability(
        name="freshness",
        core_fields=["workflow", "banner", "freshness"],
        error_semantics="missing workspace -> error dict with status=not_found",
    ),
    Capability(
        name="onboard",
        core_fields=["workflow", "tour"],
        error_semantics="missing workspace -> error dict; unsupported persona -> empty tour",
    ),
    Capability(
        name="domain",
        core_fields=["workflow", "domains", "domain_count"],
        error_semantics="missing graph -> empty domains list with diagnostics",
    ),
    Capability(
        name="business-flow",
        core_fields=["flows", "flow_count"],
        error_semantics="missing workspace -> error dict; no seed -> empty flows",
    ),
    Capability(
        name="business-flow-impact",
        core_fields=["impact", "flow_impact"],
        error_semantics="missing node_id -> error; node not found -> empty impact",
    ),
    Capability(
        name="verification-loop",
        core_fields=["checklist", "status"],
        error_semantics="missing intent -> uses default; loop failure -> diagnostics",
    ),
    Capability(
        name="workflow-profile",
        core_fields=["name", "description", "steps", "applicable_when", "tools_sequence"],
        error_semantics="unknown profile name -> error with valid options",
    ),
    Capability(
        name="runtime-audit",
        core_fields=["audit_record", "findings", "quality", "score"],
        error_semantics="missing hooks.yaml -> empty audit with diagnostics",
    ),
    Capability(
        name="regression-alerts",
        core_fields=["alerts", "total_regressions", "critical_count", "warning_count", "health"],
        error_semantics="missing benchmark data -> empty alerts",
    ),
    Capability(
        name="parser-benchmark",
        core_fields=["workspace", "files_scanned", "projects", "tree_sitter", "summary", "regressions", "improvements", "score", "quality"],
        error_semantics="tree-sitter unavailable -> diagnostics in tree_sitter; no Java files -> empty status",
    ),
    Capability(
        name="java-call-resolution",
        core_fields=["summary", "thresholds", "cases"],
        error_semantics="missing graph/cases -> validation error; unresolved calls -> explicit unresolved_rate",
    ),
    Capability(
        name="backend-consistency",
        core_fields=["consistent", "comparisons", "divergences"],
        error_semantics="missing graph.db or exported JSONL -> diagnostics",
    ),
    Capability(
        name="drill-ref",
        core_fields=["ref", "content", "summary"],
        error_semantics="missing ref_path -> error; ref not found -> not_found",
    ),
    Capability(
        name="drill-timeline",
        core_fields=["events", "event_count"],
        error_semantics="no events -> empty list; missing session_id uses recent",
    ),
    Capability(
        name="drill-task",
        core_fields=["task", "artifacts", "history"],
        error_semantics="missing task_id -> error; task not found -> not_found",
    ),
]

# Convenient look-up by capability name
CAPABILITY_MAP: dict[str, Capability] = {c.name: c for c in CAPABILITIES}


def all_cli_commands() -> list[str]:
    """Return an empty list: 5.0 has no CLI **subcommands**.

    ``memory-center`` only launches the resident service. The real console
    scripts are launchers, not subcommands, and are listed in
    ``core.foundation.entry_registry.CLI_LAUNCHERS`` (verified against
    ``pyproject.toml``). Kept as a compatibility shim so a phantom subcommand
    cannot creep back in unnoticed.
    """
    return []
