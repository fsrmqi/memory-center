"""HTTP route dispatch for the local Memory Center bridge.

The public builder composes independently testable route-family Modules while
preserving the existing path and query-parameter interface.
"""

from __future__ import annotations

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
    "_require_workspace",
    "_require_one",
    "_parse_int",
    "RouteParams",
]

# HTTP GET is a strictly read-only contract. Paths below may persist workspace
# state, execute approved external actions, or compact/export artifacts.
_MUTATING_HTTP_PATHS = frozenset({
    "/workspace/work-start", "/workspace/work-sync", "/workspace/work-close",
    "/workspace/provider-action", "/workspace/mcp-bridge-action", "/workspace/provider-evidence-fuse",
    "/workspace/change-impact-confirm", "/workspace/assertion-status", "/workspace/sniff",
    "/workspace/asset/register", "/workspace/asset/sync", "/workspace/asset/share",
    "/workspace/asset/approve", "/workspace/asset/bind", "/workspace/wiki/document-ingest",
    "/workspace/artifact/update", "/workspace/change-log/append", "/workspace/change-log/compact",
    "/workspace/task-space/create", "/workspace/delivery/init", "/workspace/delivery/contract",
    "/workspace/delivery/policy", "/workspace/delivery/execute-validation", "/workspace/delivery/matrix",
    "/workspace/delivery/subtask-status", "/workspace/delivery/validation", "/workspace/delivery/transition",
    "/workspace/delivery/skill/canary", "/workspace/delivery/skill/contract",
    "/workspace/delivery/skill/observe", "/workspace/delivery/skill/rollback",
    "/workspace/delivery/skill/synthesize", "/workspace/task-artifact/update",
    "/workspace/task-change-log/append", "/workspace/task-space/archive",
    "/workspace/task-space/status", "/workspace/task-space/touch-activity",
    "/workspace/task-spaces/auto-archive", "/workspace/artifacts/sync-sniff",
    "/workspace/artifacts/sync-case", "/workspace/walkthrough-export",
    "/workspace/memory-plan-write", "/workspace/memory-execute-write",
    "/workspace/pattern-promotion", "/workspace/heuristics", "/workspace/verification-loop",
    "/workspace/bundle-export", "/workspace/eval-golden",
})


def is_mutating_http_route(path: str, params: dict | None = None) -> bool:
    """Whether the route may change local state and therefore requires POST."""
    if path == "/workspace/query":
        return bool((params or {}).get("session_id", [""])[0])
    return path in _MUTATING_HTTP_PATHS


def _create_http_route_registry() -> CommandRegistry:
    registry = CommandRegistry(label="HTTP route")
    register_workspace_routes(registry)
    register_workflow_routes(registry)
    register_analysis_routes(registry)
    return registry


_HTTP_ROUTE_REGISTRY = _create_http_route_registry()


def build_http_route_registry(params: dict | None = None, default_workspace: str | None = None) -> CommandRegistry:
    """Return the process-wide immutable HTTP route table.

    Request values are supplied to ``dispatch`` as a ``RouteParams`` adapter.
    The unused arguments are retained only because the HTTP server passes them
    during routing.
    """
    return _HTTP_ROUTE_REGISTRY
