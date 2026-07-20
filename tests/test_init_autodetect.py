"""Tests for the auto-detect behaviour of ``memory-center init``.

Exercises ``write_default_workspace`` directly (CLI-agnostic) so the
behaviour can evolve independently of Typer surface details.

Covers:
- auto-detection walks the workspace root and emits one service per
  recognized child directory.
- auto-detection falls back to a single ``path='.'`` service when the
  root itself is a flat module (e.g. a Python package with no submodules).
- auto-detection emits an empty service list when nothing matches —
  callers must handle this gracefully.
- ``dry_run=True`` produces a report without writing anything to disk.
- Re-invoking ``write_default_workspace`` on an existing workspace does
  not overwrite the file.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from memory_center.core.workspace.config import write_default_workspace


def _touch(path: Path, content: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


# ── Multi-module detection ─────────────────────────────────────────────────


def test_detect_multi_module_spring_workspace(tmp_path: Path) -> None:
    """A Spring Cloud-style monorepo with several pom.xml submodules
    should yield one entry per submodule, each with the right kind."""
    _touch(
        tmp_path / "gateway" / "pom.xml",
        "<project>"
        "<parent><artifactId>spring-boot-starter-parent</artifactId></parent>"
        "<dependencies><dependency><artifactId>"
        "spring-cloud-starter-gateway</artifactId></dependency>"
        "</dependencies></project>",
    )
    _touch(
        tmp_path / "order-service" / "pom.xml",
        "<project><parent><artifactId>spring-boot-starter-parent"
        "</artifactId></parent></project>",
    )
    _touch(tmp_path / "common-api" / "pom.xml", "<project/>")

    workspace_file, report = write_default_workspace(tmp_path, "demo")

    assert report["detection_mode"] == "auto"
    assert report["written"] is True
    assert workspace_file.exists()

    services = {svc["name"]: svc for svc in report["services"]}
    assert services["gateway"]["type"] == "spring-cloud-gateway"
    assert services["order-service"]["type"] == "spring-boot-service"
    # common-api has no spring-boot reference, so it falls back to
    # generic-jvm. The "-api" suffix still tags it as a contract module.
    assert services["common-api"]["type"] == "generic-jvm"
    assert services["common-api"]["tags"] == ["contract"]


def test_detect_polyglot_workspace(tmp_path: Path) -> None:
    """A monorepo mixing Python, Go and Node should each be detected
    with the right kind."""
    _touch(tmp_path / "api" / "pyproject.toml", "[project]\nname='api'\n")
    _touch(tmp_path / "worker" / "go.mod", "module example.com/worker\n")
    _touch(tmp_path / "web" / "package.json", "{}")

    _, report = write_default_workspace(tmp_path, "poly")

    services = {svc["name"]: svc["type"] for svc in report["services"]}
    assert services == {
        "api": "python-package",
        "worker": "go-module",
        "web": "node-app",
    }


# ── Skip rules ─────────────────────────────────────────────────────────────


def test_detect_skips_hidden_and_build_dirs(tmp_path: Path) -> None:
    """Hidden directories and conventional build/output directories must
    never appear in the detected service list."""
    _touch(tmp_path / "service" / "pom.xml", "<project/>")
    _touch(tmp_path / ".git" / "config")
    _touch(tmp_path / "target" / "classes" / "ignored.txt")
    _touch(tmp_path / "node_modules" / "pkg" / "package.json", "{}")

    _, report = write_default_workspace(tmp_path, "x")

    names = {svc["name"] for svc in report["services"]}
    assert names == {"service"}


# ── Flat-project fallback ──────────────────────────────────────────────────


def test_detect_flat_python_project(tmp_path: Path) -> None:
    """A workspace whose root itself is a Python project (no submodules)
    should produce a single entry with ``path='.'``."""
    _touch(tmp_path / "pyproject.toml", "[project]\nname='flat'\n")
    _touch(tmp_path / "flat" / "__init__.py")

    _, report = write_default_workspace(tmp_path, "flat-ws")

    assert len(report["services"]) == 1
    svc = report["services"][0]
    assert svc["path"] == "."
    assert svc["type"] == "python-package"


# ── Unrecognized projects ──────────────────────────────────────────────────


def test_detect_unrecognized_project_yields_empty_services(tmp_path: Path) -> None:
    """A directory with no recognized build markers (e.g. the C-based
    codebase-memory-mcp) should produce an empty service list rather
    than crashing or making up entries."""
    _touch(tmp_path / "README.md", "# project")
    _touch(tmp_path / "src" / "main.c", "int main(void){ return 0; }")

    workspace_file, report = write_default_workspace(tmp_path, "c-proj")

    assert report["services"] == []
    assert report["service_count"] == 0
    # The file is still written so MCP/CLI flows have something to load;
    # users are expected to add services by hand.
    assert workspace_file.exists()
    data = yaml.safe_load(workspace_file.read_text(encoding="utf-8"))
    assert data["services"] == []


# ── Dry run ────────────────────────────────────────────────────────────────


def test_dry_run_does_not_touch_filesystem(tmp_path: Path) -> None:
    _touch(tmp_path / "svc" / "pom.xml", "<project/>")

    workspace_file, report = write_default_workspace(
        tmp_path, "ws", dry_run=True
    )

    assert report["dry_run"] is True
    assert report["written"] is False
    # The .memory-center directory must not be created either, so a
    # dry-run can be safely run against an untouched repo.
    assert not workspace_file.exists()
    assert not workspace_file.parent.exists()
    # Yet the report still surfaces the services that would have been
    # written, so callers can preview the result.
    assert [svc["name"] for svc in report["services"]] == ["svc"]


# ── Idempotency ────────────────────────────────────────────────────────────


def test_existing_workspace_is_not_overwritten(tmp_path: Path) -> None:
    _touch(tmp_path / "svc" / "pom.xml", "<project/>")
    # First call creates the file.
    workspace_file, first_report = write_default_workspace(tmp_path, "v1")
    assert first_report["written"] is True

    # Manual edit the user might make.
    custom = "workspace: edited-by-user\nroot: /tmp/x\nservices: []\n"
    workspace_file.write_text(custom, encoding="utf-8")

    # Second call must not clobber the manual edit.
    _, second_report = write_default_workspace(tmp_path, "v2")
    assert second_report["written"] is False
    assert second_report["already_exists"] is True
    assert workspace_file.read_text(encoding="utf-8") == custom
