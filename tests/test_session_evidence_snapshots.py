from __future__ import annotations

import subprocess
from pathlib import Path

from memory_center.core.orchestrator.session import (
    workspace_end_session,
    workspace_session_summary,
    workspace_start_session,
)


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
