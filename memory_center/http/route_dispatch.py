"""HTTP route dispatch for the local Memory Center bridge.

The public builder composes independently testable route-family Modules while
preserving the existing path and query-parameter interface.
"""

from __future__ import annotations

from memory_center.core.dispatch import CommandRegistry
from memory_center.http.routes import (
    register_analysis_routes,
    register_workspace_routes,
    register_workflow_routes,
)
from memory_center.http.routes.params import (
    RouteParams,
    _parse_int,
    _require_one,
    _require_workspace,
)

__all__ = [
    "build_http_route_registry",
    "_require_workspace",
    "_require_one",
    "_parse_int",
    "RouteParams",
]


def _create_http_route_registry() -> CommandRegistry:
    registry = CommandRegistry(label="HTTP route")
    register_workspace_routes(registry)
    register_workflow_routes(registry)
    register_analysis_routes(registry)
    return registry


_HTTP_ROUTE_REGISTRY = _create_http_route_registry()


def build_http_route_registry(params: dict | None = None, default_workspace: str | None = None) -> CommandRegistry:
    """Return the process-wide immutable HTTP route table.

    ``params`` and ``default_workspace`` remain accepted for source compatibility;
    request values are supplied to ``dispatch`` as a ``RouteParams`` adapter.
    """
    return _HTTP_ROUTE_REGISTRY
