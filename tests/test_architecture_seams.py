from __future__ import annotations

import ast
import inspect
from pathlib import Path


def _imports_package(path: Path, package: str) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(package):
            return True
        if isinstance(node, ast.Import) and any(alias.name.startswith(package) for alias in node.names):
            return True
    return False


def _function_size(function) -> int:
    source = inspect.getsource(function)
    node = ast.parse(source).body[0]
    return node.end_lineno - node.lineno + 1


def test_walkthrough_runner_does_not_import_query_facade() -> None:
    from memory_center.core.walkthrough import analysis

    tree = ast.parse(inspect.getsource(analysis))
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


def test_core_root_contains_only_package_initialization() -> None:
    from memory_center import core

    root = Path(core.__file__).parent
    assert sorted(path.name for path in root.glob("*.py")) == ["__init__.py"]


def test_core_domain_modules_have_one_canonical_path() -> None:
    from memory_center.core.contracting.static import build_contract_snapshot
    from memory_center.core.indexing.control_plane import index_control_status
    from memory_center.core.retrieval.cross_service import route_cross_service_shards
    from memory_center.core.tasks.artifacts import create_task_space

    assert callable(build_contract_snapshot)
    assert callable(index_control_status)
    assert callable(route_cross_service_shards)
    assert callable(create_task_space)


def test_every_core_source_directory_has_a_module_readme() -> None:
    from memory_center import core

    root = Path(core.__file__).parent
    source_dirs = [root, *[path for path in root.iterdir() if path.is_dir() and (path / "__init__.py").exists()]]
    assert not [str(path) for path in source_dirs if not (path / "README.md").exists()]


def test_ambiguous_core_module_names_do_not_return() -> None:
    from memory_center import core

    root = Path(core.__file__).parent
    forbidden = {
        "audit/completion.py",
        "benchmark/models.py",
        "indexing/runner.py",
        "orchestrator/common.py",
        "orchestrator/eval.py",
        "orchestrator/workspace.py",
        "reasoning/models.py",
        "walkthrough/artifact.py",
        "walkthrough/quality.py",
        "walkthrough/runner.py",
    }
    assert not [path for path in forbidden if (root / path).exists()]


def test_lower_core_packages_do_not_depend_on_orchestrator() -> None:
    root = Path(__file__).parents[1] / "memory_center" / "core"
    protected_packages = ("workspace", "knowledge", "retrieval")
    offenders = [
        str(path)
        for package in protected_packages
        for path in (root / package).glob("*.py")
        if _imports_package(path, "memory_center.core.orchestrator")
        or _imports_package(path, "..orchestrator")
    ]
    assert not offenders
