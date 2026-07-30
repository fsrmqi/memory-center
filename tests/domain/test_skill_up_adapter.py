from __future__ import annotations

import json
import subprocess
from pathlib import Path

from memory_center.core.storage.workspace import WorkspaceStore
from memory_center.core.tasks.skill_up import initialize_skill_up_eval, run_skill_up_eval, skill_up_status


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / ".memory-center" / "workspace.yaml"
    workspace.parent.mkdir(parents=True)
    workspace.write_text("workspace: demo\nservices: []\n", encoding="utf-8")
    return workspace


def _published_skill(workspace: Path) -> str:
    store = WorkspaceStore(workspace)
    skill_id = "delivery-demo"
    path = store.artifacts_dir / "skills" / "delivery-published" / skill_id / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text("# Demo\n", encoding="utf-8")
    registry = store.artifacts_dir / "skills" / "delivery-skill-registry.json"
    registry.write_text(json.dumps({"skills": [{"skill_id": skill_id, "lifecycle": "published", "published_path": str(path)}]}), encoding="utf-8")
    return skill_id


def test_skill_up_status_is_diagnostic_when_binary_is_missing(monkeypatch) -> None:
    monkeypatch.setattr("memory_center.core.tasks.skill_up.shutil.which", lambda _name: None)
    assert skill_up_status()["available"] is False


def test_skill_up_init_creates_bounded_skeleton_for_published_skill(tmp_path: Path, monkeypatch) -> None:
    workspace = _workspace(tmp_path)
    skill_id = _published_skill(workspace)
    monkeypatch.setattr("memory_center.core.tasks.skill_up.shutil.which", lambda _name: None)

    result = initialize_skill_up_eval(workspace, skill_id=skill_id)

    assert result["initialized"] is True
    assert Path(result["eval_config"]).exists()
    assert Path(result["cases_dir"], "README.md").exists()


def test_skill_up_dry_run_never_executes_external_binary(tmp_path: Path, monkeypatch) -> None:
    workspace = _workspace(tmp_path)
    skill_id = _published_skill(workspace)
    monkeypatch.setattr("memory_center.core.tasks.skill_up.shutil.which", lambda _name: "/usr/local/bin/skill-up")
    calls = []
    monkeypatch.setattr(
        "memory_center.core.tasks.skill_up.subprocess.run",
        lambda argv, **_kwargs: (calls.append(argv), subprocess.CompletedProcess(argv, 0, "skill-up 1.0", ""))[1],
    )
    initialize_skill_up_eval(workspace, skill_id=skill_id)
    calls.clear()

    result = run_skill_up_eval(workspace, skill_id=skill_id)

    assert result["executed"] is False
    assert result["apply"] is False
    assert calls == [["/usr/local/bin/skill-up", "--version"]]
