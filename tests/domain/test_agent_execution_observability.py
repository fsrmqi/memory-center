from __future__ import annotations

import json
from pathlib import Path

from memory_center.core.observability.agent_execution import import_agent_execution_inbox, summarize_agent_execution
from memory_center.core.storage.workspace import WorkspaceStore


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / ".memory-center" / "workspace.yaml"
    workspace.parent.mkdir(parents=True)
    workspace.write_text("workspace: execution-test\nroot: ..\nservices: []\n", encoding="utf-8")
    return workspace


def test_import_is_idempotent_and_summary_pairs_execution_boundaries(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    inbox = workspace.parent / "memory" / "agent-execution-inbox"
    inbox.mkdir(parents=True)
    rows = [
        {"schema_version": 1, "event_id": "e1", "source_session_id": "dsh-s1", "event_type": "turn/start", "channel": "ledger", "severity": "info", "time_ms": 1000, "turn": 1},
        {"schema_version": 1, "event_id": "e2", "source_session_id": "dsh-s1", "event_type": "step/start", "channel": "ledger", "severity": "info", "time_ms": 1100, "turn": 1, "step": 1},
        {"schema_version": 1, "event_id": "e3", "source_session_id": "dsh-s1", "event_type": "assistant/chunk", "channel": "ledger", "severity": "info", "time_ms": 1200, "turn": 1, "step": 1},
        {"schema_version": 1, "event_id": "e4", "source_session_id": "dsh-s1", "event_type": "assistant/message", "channel": "ledger", "severity": "info", "time_ms": 1500, "turn": 1, "step": 1, "model": "deepseek", "input_tokens": 10, "output_tokens": 4},
        {"schema_version": 1, "event_id": "e5", "source_session_id": "dsh-s1", "event_type": "tool/call", "channel": "ledger", "severity": "info", "time_ms": 1600, "turn": 1, "step": 1, "call_id": "call-1", "tool": "bash"},
        {"schema_version": 1, "event_id": "e6", "source_session_id": "dsh-s1", "event_type": "tool/result", "channel": "ledger", "severity": "error", "time_ms": 1800, "turn": 1, "step": 1, "call_id": "call-1", "tool": "bash", "error_class": "EXIT_NONZERO"},
        {"schema_version": 1, "event_id": "e7", "source_session_id": "dsh-s1", "event_type": "step/end", "channel": "ledger", "severity": "info", "time_ms": 1900, "turn": 1, "step": 1},
        {"schema_version": 1, "event_id": "e8", "source_session_id": "dsh-s1", "event_type": "turn/end", "channel": "ledger", "severity": "error", "time_ms": 2000, "turn": 1, "status": "error"},
    ]
    (inbox / "dsh-1.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    first = import_agent_execution_inbox(workspace)
    second = import_agent_execution_inbox(workspace)
    summary = summarize_agent_execution(workspace)

    assert first["inserted_count"] == 8
    assert second["inserted_count"] == 0
    assert second["duplicate_count"] == 8
    session = summary["sessions"][0]
    assert session["turn_duration_ms"] == 1000
    assert session["model_duration_ms"] == 400
    assert session["tool_duration_ms"] == 200
    assert session["first_token_ms"] == 100
    assert session["input_tokens"] == 10
    assert session["output_tokens"] == 4
    assert session["error_count"] == 2
    assert summary["tools"] == [{"tool": "bash", "calls": 1, "errors": 1, "duration_ms": 200}]


def test_import_rejects_raw_body_and_invalid_envelopes(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    inbox = workspace.parent / "memory" / "agent-execution-inbox"
    inbox.mkdir(parents=True)
    valid = {"schema_version": 1, "event_id": "ok", "source_session_id": "dsh", "event_type": "turn/start", "channel": "ledger", "severity": "info", "time_ms": 1, "body": {"prompt": "must not persist"}}
    invalid = {"schema_version": 1, "event_id": "bad", "source_session_id": "", "event_type": "turn/start", "time_ms": 1}
    (inbox / "dsh-2.jsonl").write_text(json.dumps(valid) + "\n" + json.dumps(invalid) + "\n", encoding="utf-8")

    result = import_agent_execution_inbox(workspace)
    summary = summarize_agent_execution(workspace)
    stored = WorkspaceStore(workspace).read_jsonl_prefer_backend("agent-execution-events.jsonl", limit=10)

    assert result["inserted_count"] == 1
    assert result["invalid_count"] == 1
    assert "body" not in stored[0]
    assert "must not persist" not in str(stored)
    assert "must not persist" not in str(summary)
