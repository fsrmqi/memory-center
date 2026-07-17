"""会话代码版本与验证快照，避免保存源码、路径或命令敏感参数。"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from memory_center.core.audit.interactions import redact_interaction_text
from memory_center.core.workspace.config import load_workspace_config

_VALIDATION_STATUSES = {"passed", "failed", "skipped", "not_run", "recorded"}


def capture_git_snapshot(workspace_file: str | Path) -> dict[str, Any]:
    """Capture a bounded, path-free Git state snapshot for one workspace."""
    root = Path(load_workspace_config(workspace_file).root_path).expanduser().resolve()
    if _git(root, "rev-parse", "--is-inside-work-tree") != "true":
        return {"available": False, "status": "not_git"}
    head = _git(root, "rev-parse", "HEAD")
    if not head:
        return {"available": False, "status": "unavailable"}
    changes = _git(root, "status", "--porcelain")
    return {
        "available": True,
        "status": "captured",
        "head": head[:64],
        "branch": _git(root, "branch", "--show-current")[:160],
        "dirty_file_count": len([line for line in changes.splitlines() if line.strip()]),
    }


def normalize_validation_snapshot(
    *,
    command: str = "",
    exit_code: int | None = None,
    summary: str = "",
    status: str = "",
) -> dict[str, Any]:
    """Normalize a reported validation result without running its command."""
    normalized_status = str(status or "").strip().lower()
    normalized_exit = _coerce_exit_code(exit_code)
    if normalized_status not in _VALIDATION_STATUSES:
        normalized_status = ""
    if not normalized_status:
        if normalized_exit == 0:
            normalized_status = "passed"
        elif normalized_exit is not None:
            normalized_status = "failed"
        elif command:
            normalized_status = "recorded"
        else:
            normalized_status = "not_run"
    return {
        "command": redact_interaction_text(command),
        "exit_code": normalized_exit,
        "status": normalized_status,
        "summary": redact_interaction_text(summary),
        "verified": normalized_status == "passed",
    }


def build_session_evidence_chain(
    events: list[dict[str, Any]],
    outcome: str = "",
) -> dict[str, Any]:
    """Build the minimal reproducible chain: code version -> validation -> outcome."""
    start_snapshot: dict[str, Any] = {}
    end_snapshot: dict[str, Any] = {}
    validation: dict[str, Any] = normalize_validation_snapshot()
    for event in events:
        payload = event.get("payload", {}) if isinstance(event.get("payload"), dict) else {}
        if event.get("event_type") == "session_start" and isinstance(payload.get("code_snapshot"), dict):
            start_snapshot = dict(payload["code_snapshot"])
        if event.get("event_type") == "session_end":
            if isinstance(payload.get("code_snapshot"), dict):
                end_snapshot = dict(payload["code_snapshot"])
            if isinstance(payload.get("validation"), dict):
                validation = dict(payload["validation"])
    changed = bool(
        start_snapshot.get("head")
        and end_snapshot.get("head")
        and start_snapshot.get("head") != end_snapshot.get("head")
    )
    return {
        "code_version": {
            "start": start_snapshot or {"available": False, "status": "not_captured"},
            "end": end_snapshot or {"available": False, "status": "not_captured"},
            "head_changed": changed,
        },
        "validation": validation,
        "outcome": redact_interaction_text(outcome),
        "state": _session_state(outcome, validation),
    }


def _git(root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _coerce_exit_code(value: int | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _session_state(outcome: str, validation: dict[str, Any]) -> str:
    lower_outcome = str(outcome or "").lower()
    if any(term in lower_outcome for term in ("reopen", "重新打开", "继续处理")):
        return "reopened"
    if validation.get("status") == "passed":
        return "verified"
    if validation.get("status") == "failed":
        return "failed"
    return "partial"
