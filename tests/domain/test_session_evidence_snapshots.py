from __future__ import annotations

import subprocess
from pathlib import Path

from memory_center.core.orchestrator.session import (
    workspace_end_session,
    workspace_capture_dsh_delivery_summary,
    workspace_session_summary,
    workspace_start_session,
)
from memory_center.core.knowledge.wiki_promotion import wiki_promotion_preview


def _init_git_repo(root: Path) -> None:
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "tests@example.invalid"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Memory Center Tests"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-m", "fixture"], cwd=root, check=True, capture_output=True)


def test_session_records_git_and_validation_evidence_chain(tmp_path: Path) -> None:
    from tests.fixtures import setup_demo_workspace

    workspace = setup_demo_workspace(tmp_path)
    root = workspace.parent.parent
    _init_git_repo(root)

    started = workspace_start_session(str(workspace), "validate session")
    ended = workspace_end_session(
        str(workspace),
        started["session_id"],
        outcome="completed",
        validation_command="pytest -q --token=secret-value /Users/private/project",
        validation_exit_code=0,
        validation_summary="42 passed for /Users/private/project",
    )
    chain = ended["evidence_chain"]

    assert started["code_snapshot"]["status"] == "captured"
    assert chain["code_version"]["start"]["head"]
    assert chain["code_version"]["end"]["head"]
    assert chain["validation"]["status"] == "passed"
    assert chain["validation"]["verified"] is True
    assert chain["state"] == "verified"
    assert "secret-value" not in chain["validation"]["command"]
    assert "/Users/private" not in chain["validation"]["command"]
    assert "<PATH:" in chain["validation"]["summary"]

    summary = workspace_session_summary(str(workspace), started["session_id"])
    assert summary["summary"]["evidence_chain"] == chain


def test_session_snapshot_degrades_without_git_or_validation(tmp_path: Path) -> None:
    from tests.fixtures import setup_demo_workspace

    workspace = setup_demo_workspace(tmp_path)
    started = workspace_start_session(str(workspace), "non git")
    ended = workspace_end_session(str(workspace), started["session_id"], outcome="pending")

    assert started["code_snapshot"] == {"available": False, "status": "not_git"}
    assert ended["evidence_chain"]["validation"]["status"] == "not_run"
    assert ended["evidence_chain"]["state"] == "partial"


def test_explicit_human_confirmation_verifies_without_a_command(tmp_path: Path) -> None:
    from tests.fixtures import setup_demo_workspace

    workspace = setup_demo_workspace(tmp_path)
    started = workspace_start_session(str(workspace), "human review")
    ended = workspace_end_session(
        str(workspace),
        started["session_id"],
        outcome="reviewed",
        verified_by=["reviewer"],
    )

    assert ended["evidence_chain"]["validation"]["status"] == "passed"
    assert ended["evidence_chain"]["validation"]["verification_source"] == "human_confirmation"
    assert ended["evidence_chain"]["state"] == "verified"


def test_dsh_delivery_capture_writes_a_bounded_closed_l0_session(tmp_path: Path) -> None:
    from tests.fixtures import setup_demo_workspace

    workspace = setup_demo_workspace(tmp_path)
    # Session-first：delivery capture 需要可信锚点，先显式绑定 Shadow。
    from memory_center.core.tasks.artifacts import create_task_space
    from memory_center.core.tasks.shadow import bind_shadow_to_task, ensure_shadow_for_session

    task_id = create_task_space(str(workspace), title="delivery snapshot task")["task_id"]
    shadow = ensure_shadow_for_session(str(workspace), "dsh-source-1", intent="交付")
    bind_shadow_to_task(str(workspace), shadow["shadow_id"], task_id, source="explicit")
    captured = workspace_capture_dsh_delivery_summary(
        str(workspace),
        "dsh-source-1",
        "修改完成。已确认修改生效。" + "x" * 2_000,
        turn=3,
        step=2,
    )

    assert captured["captured"] is True
    assert captured["task_id"] == task_id
    assert captured["validation_status"] == "passed"
    assert captured["summary_chars"] == 1400
    session = workspace_session_summary(str(workspace), captured["session_id"])
    assert session["found"] is True
    assert any(item["event_type"] == "dsh_delivery_summary" for item in session["events"])
    duplicate = workspace_capture_dsh_delivery_summary(str(workspace), "dsh-source-1", "修改完成。", turn=3, step=2)
    assert duplicate == {"captured": False, "duplicate": True, "session_id": captured["session_id"], "source_session_id": "dsh-source-1"}
    preview = wiki_promotion_preview(str(workspace), captured["session_id"], wiki_root=tmp_path / "wiki")
    assert preview["ready"] is True
    assert preview["module"] == "kaipuyun"
    assert preview["task_id"] == task_id
    assert preview["content"].startswith("修改完成")
