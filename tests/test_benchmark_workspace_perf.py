"""Bounded performance benchmarks for a synthetic Spring Cloud-shaped workspace.

This is intentionally not a microbenchmark: we build a workspace with many
services, controllers and Feign clients, then exercise the four hot paths
called out in the architecture backlog and assert each completes well within
a generous wall-clock budget.

The thresholds are deliberately loose so cold-start, debug builds, or CI
slowness do not flake the suite; the goal is to catch order-of-magnitude
regressions, not microsecond drift.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from memory_center.core.config import load_workspace_config
from memory_center.core.indexer import build_graph_store, reindex_workspace
from memory_center.core.store import WorkspaceStore
from memory_center.core.orchestrator.common import load_context
from memory_center.core.orchestrator.query import (
    memory_method_walkthrough,
    memory_query_hybrid,
)


SERVICES = 8
CONTROLLERS_PER_SERVICE = 6
ENDPOINTS_PER_CONTROLLER = 4
FEIGN_CLIENTS_PER_SERVICE = 3
FEIGN_METHODS_PER_CLIENT = 3


def _java_class(package: str, class_name: str, body: str) -> str:
    return f"package {package};\n\n{body}\n"


def _make_controller(package: str, service: str, idx: int) -> tuple[str, str]:
    class_name = f"{service.title().replace('-', '')}Controller{idx}"
    methods = []
    for j in range(ENDPOINTS_PER_CONTROLLER):
        methods.append(
            f"    @org.springframework.web.bind.annotation.GetMapping(\"/svc{idx}/op{j}/{{id}}\")\n"
            f"    public String handle{j}(@org.springframework.web.bind.annotation.PathVariable Long id) {{\n"
            f"        return service.lookup(id);\n"
            f"    }}\n"
        )
    body = (
        f"@org.springframework.web.bind.annotation.RestController\n"
        f"@org.springframework.web.bind.annotation.RequestMapping(\"/{service}\")\n"
        f"public class {class_name} {{\n"
        f"    @org.springframework.beans.factory.annotation.Autowired private {class_name}Service service;\n"
        + "\n".join(methods)
        + "\n}\n"
    )
    return class_name, _java_class(package, class_name, body)


def _make_service_impl(package: str, class_name: str) -> str:
    body = (
        f"@org.springframework.stereotype.Service\n"
        f"public class {class_name}Service {{\n"
        f"    public String lookup(Long id) {{ return Long.toString(id); }}\n"
        f"}}\n"
    )
    return _java_class(package, f"{class_name}Service", body)


def _make_feign_client(package: str, target_service: str, idx: int) -> str:
    class_name = f"{target_service.title().replace('-', '')}Feign{idx}"
    methods = "\n".join(
        f"    @org.springframework.web.bind.annotation.GetMapping(\"/svc{idx}/op{j}/{{id}}\")\n"
        f"    String call{j}(@org.springframework.web.bind.annotation.PathVariable Long id);\n"
        for j in range(FEIGN_METHODS_PER_CLIENT)
    )
    body = (
        f"@org.springframework.cloud.openfeign.FeignClient(name=\"{target_service}\")\n"
        f"public interface {class_name} {{\n{methods}\n}}\n"
    )
    return _java_class(package, class_name, body)


def _build_synthetic_workspace(root: Path) -> Path:
    services = [f"service-{i}" for i in range(SERVICES)]
    workspace_dir = root / ".memory-center"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    yaml_lines = [
        "workspace: synthetic-bench",
        f"root: {root.as_posix()}",
        "services:",
    ]
    for svc in services:
        yaml_lines.append(f"  - name: {svc}")
        yaml_lines.append(f"    path: {svc}")
        yaml_lines.append("    type: spring-boot-service")
        yaml_lines.append(f"    service_name: {svc}")
    (workspace_dir / "workspace.yaml").write_text("\n".join(yaml_lines) + "\n", encoding="utf-8")

    for svc in services:
        package = f"com.example.{svc.replace('-', '')}"
        java_root = root / svc / "src" / "main" / "java" / Path(*package.split("."))
        java_root.mkdir(parents=True, exist_ok=True)
        for c in range(CONTROLLERS_PER_SERVICE):
            class_name, ctrl_src = _make_controller(package, svc, c)
            (java_root / f"{class_name}.java").write_text(ctrl_src, encoding="utf-8")
            (java_root / f"{class_name}Service.java").write_text(
                _make_service_impl(package, class_name), encoding="utf-8"
            )
        for f in range(FEIGN_CLIENTS_PER_SERVICE):
            target = services[(services.index(svc) + 1 + f) % len(services)]
            feign_src = _make_feign_client(package, target, f)
            class_name = f"{target.title().replace('-', '')}Feign{f}"
            (java_root / f"{class_name}.java").write_text(feign_src, encoding="utf-8")
    return workspace_dir / "workspace.yaml"


@pytest.fixture(scope="module")
def synthetic_workspace_indexed(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("synthetic-bench")
    workspace_file = _build_synthetic_workspace(root)
    _reindex(workspace_file)
    return workspace_file


def test_reindex_completes_within_budget(tmp_path) -> None:
    root = tmp_path / "synthetic"
    root.mkdir()
    workspace_file = _build_synthetic_workspace(root)
    start = time.perf_counter()
    _reindex(workspace_file)
    elapsed = time.perf_counter() - start
    # Generous budget; the synthetic workspace has ~140 Java files.
    assert elapsed < 30.0, f"reindex too slow: {elapsed:.2f}s"


def test_graph_build_completes_within_budget(synthetic_workspace_indexed: Path) -> None:
    config, store = load_context(synthetic_workspace_indexed)
    start = time.perf_counter()
    counts = build_graph_store(config, store)
    elapsed = time.perf_counter() - start
    assert elapsed < 15.0, f"graph build too slow: {elapsed:.2f}s"
    assert counts.get("nodes", 0) > 0


def test_method_walkthrough_completes_within_budget(synthetic_workspace_indexed: Path) -> None:
    # Pick the first controller in the first service: ServiceN.handle0 etc.
    symbol = "Service0Controller0#handle0"
    start = time.perf_counter()
    result = memory_method_walkthrough(
        synthetic_workspace_indexed,
        symbol,
        depth=2,
        limit=20,
        view="compact",
        budget="small",
        report_level="standard",
    )
    elapsed = time.perf_counter() - start
    # Very generous; in practice should be sub-second on a warm cache.
    assert elapsed < 5.0, f"walkthrough too slow: {elapsed:.2f}s"
    assert result.get("found") is True
    assert result.get("local_steps") or result.get("local_service_continuations")


def test_hybrid_retrieve_completes_within_budget(synthetic_workspace_indexed: Path) -> None:
    start = time.perf_counter()
    result = memory_query_hybrid(synthetic_workspace_indexed, "Service0Controller0", limit=10)
    elapsed = time.perf_counter() - start
    assert elapsed < 5.0, f"hybrid retrieve too slow: {elapsed:.2f}s"
    assert "results" in result or "matches" in result
def _reindex(workspace_file: Path) -> None:
    config = load_workspace_config(workspace_file)
    store = WorkspaceStore(workspace_file)
    reindex_workspace(config, store)
