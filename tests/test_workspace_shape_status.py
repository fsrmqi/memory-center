from __future__ import annotations

from pathlib import Path

from memory_center.core.freshness.status import IndexFreshnessService
from memory_center.core.orchestrator import workspace_status
from memory_center.core.audit.runtime import audit_agent_runtime
from memory_center.core.validators import doctor


def _make_workspace_with_shape_risks(tmp_path: Path) -> Path:
    root = tmp_path / "workspace-root"
    (root / "apps" / "parent" / "child").mkdir(parents=True, exist_ok=True)
    (root / "libs" / "shared").mkdir(parents=True, exist_ok=True)
    workspace_dir = root / ".memory-center"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    workspace = workspace_dir / "workspace.yaml"
    workspace.write_text(
        "\n".join(
            [
                "workspace: shape-risk-demo",
                f"root: {root.as_posix()}",
                "services:",
                "  - name: app-parent",
                "    path: apps/parent",
                "    type: spring-boot-service",
                "  - name: app-child",
                "    path: apps/parent/child",
                "    type: spring-boot-service",
                "  - name: shared-a",
                "    path: libs/shared",
                "    type: shared-library",
                "  - name: shared-b",
                "    path: libs/shared",
                "    type: shared-library",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return workspace


def test_workspace_status_includes_workspace_shape_risks(tmp_path: Path):
    workspace = _make_workspace_with_shape_risks(tmp_path)

    result = workspace_status(workspace, view="full")

    assert result["workspace_shape"]["service_count"] == 4
    assert result["workspace_shape"]["unique_root_count"] == 3
    assert result["workspace_shape"]["duplicate_root_group_count"] == 1
    assert result["workspace_shape"]["nested_service_pair_count"] == 1
    assert result["workspace_shape"]["risk_level"] == "high"
    assert len(result["workspace_warnings"]) == 2
    codes = {item["code"] for item in result["workspace_warnings"]}
    assert "duplicate_service_roots" in codes
    assert "nested_service_roots" in codes


def test_freshness_banner_surfaces_workspace_shape_risks(tmp_path: Path):
    workspace = _make_workspace_with_shape_risks(tmp_path)

    banner = IndexFreshnessService(str(workspace)).banner()

    assert "freshness" in banner
    assert banner["workspace_shape"]["duplicate_root_group_count"] == 1
    assert banner["workspace_shape"]["nested_service_pair_count"] == 1
    assert len(banner["workspace_warnings"]) == 2
    assert "workspace 配置存在" in (banner.get("banner") or "")


def test_doctor_reports_workspace_shape_fixes(tmp_path: Path):
    workspace = _make_workspace_with_shape_risks(tmp_path)

    report = doctor(workspace)

    assert report["ok"] is False
    assert report["workspace_shape"]["risk_level"] == "high"
    assert any(item["name"] == "workspace_shape:service_roots" and not item["ok"] for item in report["checks"])
    assert any(item["code"] == "duplicate_service_roots" for item in report["advisories"])
    assert any(item["code"] == "nested_service_roots" for item in report["advisories"])
    assert any(item["code"] == "deduplicate_service_root_group" for item in report["suggested_fixes"])
    assert any(item["code"] == "narrow_parent_service_root" for item in report["suggested_fixes"])
    assert "service root" in report["hint"]


def test_runtime_audit_surfaces_workspace_shape_fixes(tmp_path: Path):
    workspace = _make_workspace_with_shape_risks(tmp_path)

    result = audit_agent_runtime(workspace)

    assert result["workspace_shape"]["risk_level"] == "high"
    assert any(item["code"] == "duplicate_service_roots" for item in result["findings"])
    assert any(item["code"] == "workspace_doctor_failed" for item in result["findings"])
    assert any(item["code"] == "deduplicate_service_root_group" for item in result["suggested_fixes"])
    assert "service root" in result["doctor_hint"]
