from __future__ import annotations

from pathlib import Path


def test_runtime_governance_is_read_only_and_available_from_all_entrypoints(tmp_path: Path) -> None:
    from memory_center.application.admin import build_admin_registry
    from memory_center.application.runtime_governance import workspace_runtime_governance
    from memory_center.http.route_dispatch import build_http_route_registry, is_mutating_http_route
    from memory_center.http.routes.params import RouteParams
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    before = sorted(path.relative_to(workspace.parent).as_posix() for path in workspace.parent.rglob("*"))
    report = workspace_runtime_governance(workspace)
    route = build_http_route_registry().dispatch(
        "/workspace/runtime-governance", RouteParams({"workspace": [str(workspace)]}, str(workspace))
    )
    admin = build_admin_registry(workspace_file=str(workspace)).dispatch("runtime_governance")
    after = sorted(path.relative_to(workspace.parent).as_posix() for path in workspace.parent.rglob("*"))

    assert report["mode"] == "read_only"
    assert {"performance", "scoped_refresh", "storage", "index", "vector_ann", "active_jobs"}.issubset(report)
    assert route["mode"] == "read_only"
    assert admin["mode"] == "read_only"
    assert is_mutating_http_route("/workspace/runtime-governance") is False
    assert before == after
