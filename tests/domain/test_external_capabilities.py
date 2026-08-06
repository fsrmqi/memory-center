from __future__ import annotations

from pathlib import Path


def test_external_capability_audit_is_metadata_only_and_detects_drift(tmp_path: Path, monkeypatch) -> None:
    from memory_center.application.external_capabilities import (
        audit_external_capabilities,
        snapshot_external_capabilities,
    )
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    home = tmp_path / "home"
    skill = home / ".codex" / "skills" / "demo" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("# demo\nsecret-like text stays hashed\n", encoding="utf-8")
    monkeypatch.setattr("memory_center.application.external_capabilities.Path.home", lambda: home)

    first = audit_external_capabilities(workspace)
    assert first["mode"] == "read_only"
    assert first["summary"]["skills"] == 1
    assert "secret-like text" not in str(first)
    snapshot_external_capabilities(workspace)
    skill.write_text("# demo changed\n", encoding="utf-8")
    second = audit_external_capabilities(workspace)

    assert second["drift"]["baseline_available"] is True
    assert second["drift"]["changed"] == ["codex:global:skill:demo"]
