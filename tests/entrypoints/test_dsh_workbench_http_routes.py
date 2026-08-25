from memory_center.http.route_dispatch import build_http_route_registry


def test_dsh_workbench_read_routes_are_registered() -> None:
    registry = build_http_route_registry({}, None)

    for path in (
        "/workspace/impact",
        "/workspace/consolidation-candidates",
        "/workspace/agent-execution-summary",
    ):
        assert registry.has(path), path
