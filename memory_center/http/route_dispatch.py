"""HTTP route dispatch for the local Memory Center bridge.

The public builder composes independently testable route-family Modules while
preserving the existing path and query-parameter interface.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from memory_center.core.foundation.dispatch import CommandRegistry
from memory_center.http.routes import (
    register_analysis_routes,
    register_workflow_routes,
    register_workspace_routes,
)
from memory_center.http.routes.params import (
    RouteParams,
    _parse_int,
    _require_one,
    _require_workspace,
)

__all__ = [
    "build_http_route_registry",
    "is_mutating_http_route",
    "http_route_spec",
    "audit_http_route_contract",
    "_require_workspace",
    "_require_one",
    "_parse_int",
    "RouteParams",
]


@dataclass(frozen=True)
class HTTPRouteSpec:
    methods: frozenset[str]
    side_effect: str = "read"


# HTTP GET is a strictly read-only contract. Paths below declare their write
# semantics centrally, instead of relying on individual route handlers.
_MUTATING_HTTP_PATHS = frozenset(
    {
        "/workspace/work-start",
        "/workspace/work-sync",
        "/workspace/work-close",
        "/workspace/provider-action",
        "/workspace/mcp-bridge-action",
        "/workspace/provider-evidence-fuse",
        "/workspace/change-impact-confirm",
        "/workspace/assertion-status",
        "/workspace/sniff",
        "/workspace/asset/register",
        "/workspace/asset/sync",
        "/workspace/asset/share",
        "/workspace/asset/approve",
        "/workspace/asset/bind",
        "/workspace/wiki/document-ingest",
        "/workspace/artifact/update",
        "/workspace/change-log/append",
        "/workspace/change-log/compact",
        "/workspace/task-space/create",
        "/workspace/delivery/init",
        "/workspace/delivery/contract",
        "/workspace/delivery/policy",
        "/workspace/delivery/execute-validation",
        "/workspace/delivery/matrix",
        "/workspace/delivery/subtask-status",
        "/workspace/delivery/validation",
        "/workspace/delivery/transition",
        "/workspace/delivery/skill/canary",
        "/workspace/delivery/skill/contract",
        "/workspace/delivery/skill/observe",
        "/workspace/delivery/skill/rollback",
        "/workspace/delivery/skill/synthesize",
        "/workspace/task-artifact/update",
        "/workspace/task-change-log/append",
        "/workspace/task-space/archive",
        "/workspace/task-space/status",
        "/workspace/task-space/touch-activity",
        "/workspace/task-spaces/auto-archive",
        "/workspace/task-shadow-record-snapshot",
        "/workspace/task-shadow-bind",
        "/workspace/task-shadow-discard",
        "/workspace/task-shadow-promote",
        "/workspace/task-shadow-observation",
        "/workspace/task-shadow-handoff",
        "/workspace/artifacts/sync-sniff",
        "/workspace/artifacts/sync-case",
        "/workspace/walkthrough-export",
        "/workspace/memory-plan-write",
        "/workspace/memory-execute-write",
        "/workspace/pattern-promotion",
        "/workspace/heuristics",
        "/workspace/verification-loop",
        "/workspace/bundle-export",
        "/workspace/eval-golden",
        "/workspace/performance-snapshot",
        "/workspace/job-cancel",
    }
)
_HTTP_ROUTE_SPECS = {path: HTTPRouteSpec(frozenset({"POST"}), "write") for path in _MUTATING_HTTP_PATHS}
_MUTATION_LIKE_ROUTE_NAME = re.compile(
    r"(?:approve|append|archive|bind|cancel|close|compact|create|execute|ingest|init|register|rollback|share|start|sync|transition|update|write)"
)
_READ_ROUTE_NAME_EXCEPTIONS = frozenset(
    {
        "/workspace/eval-write-quality",
        "/workspace/memory-write-judge",
        "/workspace/replay-write-chain",
        "/workspace/write-receipts",
    }
)


def http_route_spec(path: str, params: dict | None = None) -> HTTPRouteSpec:
    if path == "/workspace/query" and bool((params or {}).get("session_id", [""])[0]):
        return HTTPRouteSpec(frozenset({"POST"}), "audit_write")
    return _HTTP_ROUTE_SPECS.get(path, HTTPRouteSpec(frozenset({"GET"})))


def is_mutating_http_route(path: str, params: dict | None = None) -> bool:
    """Whether the route may change local state and therefore requires POST."""
    return "POST" in http_route_spec(path, params).methods


def _create_http_route_registry() -> CommandRegistry:
    registry = CommandRegistry(label="HTTP route")
    register_workspace_routes(registry)
    register_workflow_routes(registry)
    register_analysis_routes(registry)
    return registry


_HTTP_ROUTE_REGISTRY = _create_http_route_registry()

# Every registered route receives an explicit transport contract. New routes
# are audited below, including a conservative name-based guard for a write
# route that was accidentally left at the GET default.
for _path in _HTTP_ROUTE_REGISTRY.names():
    _HTTP_ROUTE_SPECS.setdefault(_path, HTTPRouteSpec(frozenset({"GET"}), "read"))


def audit_http_route_contract() -> dict[str, object]:
    """Check route registration and read/write transport declarations."""
    registered = set(_HTTP_ROUTE_REGISTRY.names())
    declared = set(_HTTP_ROUTE_SPECS)
    unknown_declared = sorted(declared - registered)
    unclassified = sorted(registered - declared)
    mutation_like_get = sorted(
        path
        for path in registered
        if _MUTATION_LIKE_ROUTE_NAME.search(path)
        and _HTTP_ROUTE_SPECS[path].side_effect == "read"
        and path not in _READ_ROUTE_NAME_EXCEPTIONS
    )
    invalid_methods = sorted(
        path
        for path in registered
        if not _HTTP_ROUTE_SPECS[path].methods or not _HTTP_ROUTE_SPECS[path].methods <= {"GET", "POST"}
    )
    passed = not (unknown_declared or unclassified or mutation_like_get or invalid_methods)
    return {
        "passed": passed,
        "registered_routes": len(registered),
        "declared_routes": len(declared),
        "write_routes": len([path for path in registered if _HTTP_ROUTE_SPECS[path].side_effect != "read"]),
        "unknown_declared": unknown_declared,
        "unclassified": unclassified,
        "mutation_like_get": mutation_like_get,
        "invalid_methods": invalid_methods,
        "next_action": "可以发布 HTTP 路由变更。" if passed else "为列出的路由补充显式读写契约后再发布。",
    }


def build_http_route_registry(params: dict | None = None, default_workspace: str | None = None) -> CommandRegistry:
    """Return the process-wide immutable HTTP route table.

    Request values are supplied to ``dispatch`` as a ``RouteParams`` adapter.
    The unused arguments are retained only because the HTTP server passes them
    during routing.
    """
    return _HTTP_ROUTE_REGISTRY
