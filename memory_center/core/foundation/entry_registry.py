"""5.0 入口注册表 / 5.0 entry-point registry.

这是 **5.0 唯一的用户可达入口清单**：17 个 MCP 工具、``/mcp`` 传输端点、
``/admin/`` 管理页、``/api/v1/*`` HTTP 路由与 5 个命令行启动器。

本模块位于 ``core.foundation``（系统最低层），因此**只保存纯数据，不导入
``service`` / ``platform`` / ``application``**。真值由
``tests/entrypoints/test_entry_registry.py`` 在运行态校验：把这里声明的工具名
与真实的 ``tools/list``、把 HTTP 路径与真实的 FastAPI 路由表逐一比对，任何
漂移都会让测试失败。

历史资产请勿写回这里：``core/foundation/capabilities.py`` 是 4.x B-01 的
**能力契约目录**（``core_fields`` / ``error_semantics``），已不再声明任何入口；
4.x 的 ``/workspace/*`` 路由、``mc_context_pack`` 等工具名与 ``mc_admin``
actions 只在下面的 ``RETIRED_*`` 名单中作为**已退役标识的否定清单**保留，供
测试确认它们没有悄悄变成 5.0 入口。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EntryPoint:
    """One user-reachable 5.0 entry point."""

    kind: str            # see LIVE_ENTRY_KINDS
    identifier: str      # MCP tool name, HTTP path, page path or console script
    method: str = ""     # HTTP method; empty for non-HTTP kinds
    source: str = ""     # authoritative definition site
    note: str = ""       # short clarification / non-equivalence warning


KIND_MCP_TOOL = "mcp_tool"
KIND_MCP_ENDPOINT = "mcp_endpoint"
KIND_HTTP = "http"
KIND_ADMIN_PAGE = "admin_page"
KIND_CLI_LAUNCHER = "cli_launcher"

LIVE_ENTRY_KINDS: frozenset[str] = frozenset({
    KIND_MCP_TOOL,
    KIND_MCP_ENDPOINT,
    KIND_HTTP,
    KIND_ADMIN_PAGE,
    KIND_CLI_LAUNCHER,
})

_APP = "memory_center/service/app.py"
_PLATFORM_MCP = "memory_center/service/platform_mcp.py::register_tools"
_GOVERNANCE_MCP = "memory_center/service/governance_mcp.py::register_governance"
_WORKSPACE_ROUTES = "memory_center/service/workspace_routes.py::workspace_router"
_PLATFORM_ROUTES = "memory_center/service/platform_routes.py::platform_router"
_GOVERNANCE_ROUTES = "memory_center/service/governance_routes.py::governance_router"


def _tool(identifier: str, source: str = _PLATFORM_MCP, note: str = "") -> EntryPoint:
    return EntryPoint(kind=KIND_MCP_TOOL, identifier=identifier, source=source, note=note)


def _http(method: str, identifier: str, source: str, note: str = "") -> EntryPoint:
    return EntryPoint(kind=KIND_HTTP, identifier=identifier, method=method, source=source, note=note)


# ---------------------------------------------------------------------------
# 1. MCP tool surface (17 tools, authoritative source: live tools/list)
# ---------------------------------------------------------------------------

MCP_TOOLS: tuple[EntryPoint, ...] = (
    _tool("mc_service_status", _APP, "无参数、只读；服务状态 / 版本 / 能力 / 索引预算"),
    _tool("mc_workspaces"),
    _tool("mc_lookup"),
    _tool("mc_analyze"),
    _tool("mc_start"),
    _tool("mc_resume"),
    _tool("mc_close"),
    _tool("mc_ref"),
    _tool("mc_memory_write"),
    _tool("mc_wiki_write"),
    _tool("mc_index"),
    _tool("mc_job_status"),
    _tool("mc_job_cancel"),
    _tool("assistant_admin", _GOVERNANCE_MCP, "只支持 validate / scan / index，不是 4.x mc_admin 的替代品"),
    _tool("assistant_knowledge", _GOVERNANCE_MCP),
    _tool("assistant_memory", _GOVERNANCE_MCP),
    _tool("assistant_skill", _GOVERNANCE_MCP),
)

MCP_ENDPOINTS: tuple[EntryPoint, ...] = (
    EntryPoint(kind=KIND_MCP_ENDPOINT, identifier="/mcp", source=_APP,
               note="官方 SDK Streamable HTTP；挂载于 /，由 MCPBoundary 转发"),
)

ADMIN_PAGES: tuple[EntryPoint, ...] = (
    EntryPoint(kind=KIND_ADMIN_PAGE, identifier="/admin/", source=_APP,
               note="静态管理页；项目登记、知识治理与 Skill 管理在此操作"),
    EntryPoint(kind=KIND_ADMIN_PAGE, identifier="/", source=_APP,
               note="根路径重定向到 /admin/"),
)

# ---------------------------------------------------------------------------
# 2. HTTP surface (user-facing subset; the full table is the OpenAPI schema)
#
# 这里刻意只列「用户/宿主会直接调用」的路由，不复制 90 余条管理 API。测试断言
# 每条声明都存在于真实路由表中；完整路由以服务实际 OpenAPI 为准，避免本清单
# 变成第二份需要同步维护的路由定义。
# ---------------------------------------------------------------------------

HTTP_ENDPOINTS: tuple[EntryPoint, ...] = (
    _http("GET", "/health/live", _APP),
    _http("GET", "/health/ready", _APP),
    _http("GET", "/api/v1/service/status", _APP),
    _http("GET", "/api/v1/workspaces", _WORKSPACE_ROUTES),
    _http("POST", "/api/v1/workspaces", _WORKSPACE_ROUTES, "项目登记需要管理员令牌"),
    _http("POST", "/api/v1/workspaces/preview", _WORKSPACE_ROUTES, "只读预览，对应 4.x init --dry-run"),
    _http("GET", "/api/v1/workspaces/{workspace_id}", _WORKSPACE_ROUTES),
    _http("PATCH", "/api/v1/workspaces/{workspace_id}", _WORKSPACE_ROUTES),
    _http("DELETE", "/api/v1/workspaces/{workspace_id}", _WORKSPACE_ROUTES),
    _http("POST", "/api/v1/workspaces/{workspace_id}/pause", _WORKSPACE_ROUTES),
    _http("POST", "/api/v1/workspaces/{workspace_id}/resume", _WORKSPACE_ROUTES),
    _http("GET", "/api/v1/jobs", _PLATFORM_ROUTES),
    _http("POST", "/api/v1/jobs/{job_id}/retry", _PLATFORM_ROUTES),
    _http("POST", "/api/v1/jobs/{job_id}/cancel", _PLATFORM_ROUTES),
    _http("POST", "/api/v1/workspaces/{workspace_id}/index", _PLATFORM_ROUTES),
    _http("GET", "/api/v1/workspaces/{workspace_id}/index", _PLATFORM_ROUTES),
    _http("POST", "/api/v1/workspaces/{workspace_id}/search", _PLATFORM_ROUTES),
    _http("POST", "/api/v1/workspaces/{workspace_id}/analyze", _PLATFORM_ROUTES),
    _http("GET", "/api/v1/governance/skill-sources", _GOVERNANCE_ROUTES),
    _http("GET", "/api/v1/governance/discovered-skills", _GOVERNANCE_ROUTES),
)

# ---------------------------------------------------------------------------
# 3. CLI launchers (console scripts from pyproject.toml [project.scripts])
#
# 5.0 的命令行只有「启动器」，没有任何子命令：memory-center 与
# memory-center-service 指向同一入口。测试直接与 pyproject.toml 比对。
# ---------------------------------------------------------------------------

CLI_LAUNCHERS: tuple[EntryPoint, ...] = (
    EntryPoint(kind=KIND_CLI_LAUNCHER, identifier="memory-center", source="pyproject.toml",
               note="只启动常驻服务，无子命令"),
    EntryPoint(kind=KIND_CLI_LAUNCHER, identifier="memory-center-service", source="pyproject.toml",
               note="前台启动常驻服务"),
    EntryPoint(kind=KIND_CLI_LAUNCHER, identifier="memory-center-mcp", source="pyproject.toml",
               note="stdio 代理；只读取 MEMORY_CENTER_URL / MEMORY_CENTER_TOKEN"),
    EntryPoint(kind=KIND_CLI_LAUNCHER, identifier="memory-center-maintenance", source="pyproject.toml",
               note="仅 backup / restore"),
    EntryPoint(kind=KIND_CLI_LAUNCHER, identifier="memory-center-integrations", source="pyproject.toml",
               note="打印宿主配置模板，不修复绑定"),
)

ENTRY_POINTS: tuple[EntryPoint, ...] = (
    MCP_TOOLS + MCP_ENDPOINTS + ADMIN_PAGES + HTTP_ENDPOINTS + CLI_LAUNCHERS
)


# ---------------------------------------------------------------------------
# 4. Retired 4.x identifiers — a denylist, NOT entry declarations
#
# 这些名字来自旧 capabilities.py 的 17 条 http / 4 条 mcp_tool /
# 14 条 mcp_admin_action 声明。它们只用于断言「5.0 没有把它们重新暴露」，
# 任何消费方都不得把它们当作可调用的入口。
# ---------------------------------------------------------------------------

RETIRED_4X_MCP_TOOLS: frozenset[str] = frozenset({
    "mc_context_pack", "mc_freshness", "mc_onboard", "mc_domain",
    "mc_sync", "mc_handoff", "mc_admin",
})

RETIRED_4X_HTTP_PATHS: frozenset[str] = frozenset({
    "/workspace/change-review", "/workspace/eval-cochange", "/workspace/context-pack",
    "/workspace/freshness", "/workspace/onboard", "/workspace/business-flow",
    "/workspace/business-flow-impact", "/workspace/verification-loop",
    "/workspace/workflow-profile", "/workspace/runtime-audit",
    "/workspace/regression-alerts", "/workspace/eval-parser-benchmark",
    "/workspace/eval-java-call-resolution", "/workspace/backend-consistency",
    "/workspace/drill-ref", "/workspace/drill-timeline", "/workspace/drill-task",
})

RETIRED_4X_HTTP_PREFIXES: tuple[str, ...] = ("/workspace/", "/ui/", "/app")

RETIRED_4X_ADMIN_ACTIONS: frozenset[str] = frozenset({
    "change_review", "eval_cochange", "business_flow", "business_flow_impact",
    "verification_loop", "workflow_profile", "runtime_audit", "regression_alerts",
    "eval_parser_benchmark", "eval_java_call_resolution", "backend_consistency",
    "drill_ref", "drill_timeline", "drill_task",
})


def entry_points_by_kind(kind: str) -> tuple[EntryPoint, ...]:
    """Return all declared entry points of ``kind`` (empty for unknown kinds)."""
    return tuple(e for e in ENTRY_POINTS if e.kind == kind)


def mcp_tool_names() -> tuple[str, ...]:
    """Return declared MCP tool names in declaration order."""
    return tuple(e.identifier for e in MCP_TOOLS)


def http_endpoints() -> tuple[tuple[str, str], ...]:
    """Return ``(method, path)`` pairs for declared HTTP entry points."""
    return tuple((e.method, e.identifier) for e in HTTP_ENDPOINTS)


def cli_launcher_names() -> tuple[str, ...]:
    """Return declared console-script names in declaration order."""
    return tuple(e.identifier for e in CLI_LAUNCHERS)
