from __future__ import annotations

import ast
import inspect
from pathlib import Path


def _function_size(function) -> int:
    source = inspect.getsource(function)
    node = ast.parse(source).body[0]
    return node.end_lineno - node.lineno + 1


def test_walkthrough_runner_does_not_import_query_facade() -> None:
    from memory_center.core.walkthrough import runner

    tree = ast.parse(inspect.getsource(runner))
    imports = {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert not any(module.endswith("orchestrator.query") for module in imports)


def test_http_registry_is_composed_from_route_families() -> None:
    from memory_center.http import route_dispatch

    route_package = Path(route_dispatch.__file__).with_name("routes")
    family_modules = list(route_package.glob("*.py"))
    assert len(family_modules) >= 3
    assert _function_size(route_dispatch.build_http_route_registry) < 80
    assert route_dispatch.build_http_route_registry({}, None) is route_dispatch.build_http_route_registry({}, None)


def test_walkthrough_public_operations_are_thin_facades() -> None:
    from memory_center.core.orchestrator import query

    assert _function_size(query.memory_walkthrough_health) < 20
    assert _function_size(query.memory_eval_walkthrough_quality) < 20
    assert _function_size(query.memory_export_walkthrough_artifact) < 20


def test_core_domain_modules_have_canonical_paths_and_legacy_compatibility() -> None:
    from memory_center.core.artifacts import create_task_space as legacy_create_task_space
    from memory_center.core.contracting.static import build_contract_snapshot
    from memory_center.core.contracts import build_contract_snapshot as legacy_build_contract_snapshot
    from memory_center.core.cross_shard import route_cross_service_shards as legacy_route_cross_service_shards
    from memory_center.core.index_control import index_control_status as legacy_index_control_status
    from memory_center.core.indexing.control_plane import index_control_status
    from memory_center.core.retrieval.cross_service import route_cross_service_shards
    from memory_center.core.tasks.artifacts import create_task_space

    assert legacy_build_contract_snapshot is build_contract_snapshot
    assert legacy_index_control_status is index_control_status
    assert legacy_route_cross_service_shards is route_cross_service_shards
    assert legacy_create_task_space is create_task_space
