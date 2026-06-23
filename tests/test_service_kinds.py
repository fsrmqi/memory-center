"""Tests for memory_center.core.service_kinds.

Covers:
- Registry shape (all kinds carry the required fields).
- ``resolve_kind`` returns the spec for known names and falls back to
  ``generic`` for unknown / empty input.
- ``detect_kind_from_path`` picks the right kind from a directory's
  build markers, with the Spring-vs-generic-jvm upgrade rule.
- ``ServiceConfig.resolved_language`` defers to the explicit override
  before falling back to the registry.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from memory_center.core.models import ServiceConfig
from memory_center.core.service_kinds import (
    SERVICE_KIND_REGISTRY,
    detect_kind_from_path,
    is_known_kind,
    list_kind_names,
    resolve_kind,
)


# ── Registry shape ─────────────────────────────────────────────────────────


def test_registry_contains_canonical_kinds() -> None:
    """Spring/JVM/Python/Go/Node/Rust must all be present so that the
    documentation matrix stays in sync with the code."""
    expected = {
        "spring-cloud-gateway",
        "spring-boot-service",
        "spring-boot-task",
        "shared-library",
        "generic-jvm",
        "kotlin-module",
        "python-package",
        "node-app",
        "go-module",
        "rust-crate",
        "generic",
    }
    assert expected.issubset(set(SERVICE_KIND_REGISTRY))


def test_every_spec_has_a_description() -> None:
    """Diagnostics (memory-center status/doctor) print descriptions, so
    every kind must carry at least one localized string."""
    for name, spec in SERVICE_KIND_REGISTRY.items():
        assert spec.description_zh or spec.description_en, (
            f"kind {name} missing description"
        )


# ── resolve_kind / is_known_kind ───────────────────────────────────────────


def test_resolve_kind_known() -> None:
    spec = resolve_kind("python-package")
    assert spec.name == "python-package"
    assert spec.language == "python"


def test_resolve_kind_unknown_falls_back_to_generic() -> None:
    assert resolve_kind("dotnet-project").name == "generic"
    assert resolve_kind("").name == "generic"
    assert resolve_kind(None).name == "generic"


def test_is_known_kind() -> None:
    assert is_known_kind("spring-boot-service")
    assert not is_known_kind("dotnet-project")
    assert not is_known_kind(None)
    assert not is_known_kind("")


def test_list_kind_names_stable() -> None:
    names = list_kind_names()
    assert "spring-boot-service" in names
    assert names[-1] == "generic", "generic stays last as the fallback marker"


# ── detect_kind_from_path ──────────────────────────────────────────────────


def _touch(path: Path, content: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_detect_spring_boot_via_pom(tmp_path: Path) -> None:
    _touch(
        tmp_path / "pom.xml",
        "<project><parent><artifactId>spring-boot-starter-parent</artifactId>"
        "</parent></project>",
    )
    assert detect_kind_from_path(tmp_path) == "spring-boot-service"


def test_detect_generic_jvm_when_no_spring_signal(tmp_path: Path) -> None:
    """pom.xml without spring-boot reference should NOT trigger Spring
    detection — avoids enabling annotation extraction on plain JVM repos."""
    _touch(tmp_path / "pom.xml", "<project><artifactId>plain-jvm</artifactId></project>")
    assert detect_kind_from_path(tmp_path) == "generic-jvm"


def test_detect_python_via_pyproject(tmp_path: Path) -> None:
    _touch(tmp_path / "pyproject.toml", "[project]\nname='demo'\n")
    assert detect_kind_from_path(tmp_path) == "python-package"


def test_detect_go_via_gomod(tmp_path: Path) -> None:
    _touch(tmp_path / "go.mod", "module example.com/demo\n")
    assert detect_kind_from_path(tmp_path) == "go-module"


def test_detect_node_via_package_json(tmp_path: Path) -> None:
    _touch(tmp_path / "package.json", "{}")
    assert detect_kind_from_path(tmp_path) == "node-app"


def test_detect_rust_via_cargo(tmp_path: Path) -> None:
    _touch(tmp_path / "Cargo.toml", '[package]\nname="demo"\n')
    assert detect_kind_from_path(tmp_path) == "rust-crate"


def test_detect_returns_none_for_empty_dir(tmp_path: Path) -> None:
    assert detect_kind_from_path(tmp_path) is None


def test_detect_returns_none_for_missing_dir(tmp_path: Path) -> None:
    assert detect_kind_from_path(tmp_path / "does-not-exist") is None


def test_detect_returns_none_for_file_path(tmp_path: Path) -> None:
    target = _touch(tmp_path / "pom.xml")
    assert detect_kind_from_path(target) is None


def test_detect_kotlin_module(tmp_path: Path) -> None:
    """build.gradle.kts alone (no pom.xml) should be detected as kotlin-module
    when there's no Spring signal — otherwise as Spring."""
    _touch(tmp_path / "build.gradle.kts", "plugins { kotlin(\"jvm\") }")
    # No Spring reference, so generic-jvm/kotlin-module both candidate.
    # generic-jvm has priority 50, kotlin-module 55, so kotlin wins.
    assert detect_kind_from_path(tmp_path) == "kotlin-module"


def test_detect_spring_cloud_gateway(tmp_path: Path) -> None:
    """Only flag a project as a gateway when the build file pulls in
    ``spring-cloud-starter-gateway``. Plain Spring Boot apps must stay
    classified as ``spring-boot-service``."""
    _touch(
        tmp_path / "pom.xml",
        "<project><parent><artifactId>spring-boot-starter-parent</artifactId></parent>"
        "<dependencies><dependency><artifactId>spring-cloud-starter-gateway"
        "</artifactId></dependency></dependencies></project>",
    )
    assert detect_kind_from_path(tmp_path) == "spring-cloud-gateway"


# ── ServiceConfig.resolved_language ────────────────────────────────────────


def test_resolved_language_from_type() -> None:
    svc = ServiceConfig(name="x", path="x", type="python-package")
    assert svc.resolved_language() == "python"


def test_resolved_language_explicit_override_wins() -> None:
    svc = ServiceConfig(
        name="x", path="x", type="generic", language="scala"
    )
    assert svc.resolved_language() == "scala"


def test_resolved_language_unknown_type_falls_back_to_none() -> None:
    svc = ServiceConfig(name="x", path="x", type="dotnet-project")
    # Unknown type resolves to generic, whose language is None.
    assert svc.resolved_language() is None


@pytest.mark.parametrize(
    ("type_name", "expected_language"),
    [
        ("spring-boot-service", "java"),
        ("spring-cloud-gateway", "java"),
        ("shared-library", "java"),
        ("generic-jvm", "java"),
        ("kotlin-module", "kotlin"),
        ("python-package", "python"),
        ("node-app", "typescript"),
        ("go-module", "go"),
        ("rust-crate", "rust"),
        ("generic", None),
    ],
)
def test_language_inference_table(type_name: str, expected_language: str | None) -> None:
    assert resolve_kind(type_name).language == expected_language
