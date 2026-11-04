"""Import sanitized agent-host events and derive local execution summaries."""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from memory_center.core.storage.workspace import WorkspaceStore

EXECUTION_EVENTS_FILE = "agent-execution-events.jsonl"
INBOX_DIR = "agent-execution-inbox"
SCHEMA_VERSION = 1
_ALLOWED_SEVERITIES = {"info", "warn", "error"}
_ALLOWED_CHANNELS = {"ledger", "ops"}


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _iso_from_millis(value: int) -> str:
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat()


def _normalize_event(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict) or int(raw.get("schema_version", 0) or 0) != SCHEMA_VERSION:
        return None
    event_id = str(raw.get("event_id", "") or "").strip()[:240]
    source_session_id = str(raw.get("source_session_id", "") or "").strip()[:240]
    event_type = str(raw.get("event_type", "") or "").strip()[:120]
    time_ms = int(raw.get("time_ms", 0) or 0)
    if not event_id or not source_session_id or not event_type or time_ms <= 0:
        return None
    channel = str(raw.get("channel", "ledger") or "ledger")
    severity = str(raw.get("severity", "info") or "info")
    if channel not in _ALLOWED_CHANNELS or severity not in _ALLOWED_SEVERITIES:
        return None
    event = {
        "schema_version": SCHEMA_VERSION,
        "id": event_id,
        "type": "agent_execution_event",
        "source": "dsh",
        "session_id": source_session_id,
        "source_session_id": source_session_id,
        "event_type": event_type,
        "channel": channel,
        "severity": severity,
        "time_ms": time_ms,
        "created_at": _iso_from_millis(time_ms),
    }
    for key, limit in (
        ("agent_id", 240), ("model", 240), ("provider", 120), ("tool", 160),
        ("call_id", 240), ("status", 80), ("error_class", 160), ("body_sha256", 64),
    ):
        value = str(raw.get(key, "") or "").strip()
        if value:
            event[key] = value[:limit]
    for key in ("seq", "turn", "step", "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "reasoning_tokens"):
        value = raw.get(key)
        if value is not None:
            try:
                event[key] = max(0, int(value))
            except (TypeError, ValueError):
                return None
    return event


def _existing_event_ids(store: WorkspaceStore, event_ids: list[str]) -> set[str]:
    existing: set[str] = set()
    with store.memory_backend().connect() as conn:
        for start in range(0, len(event_ids), 500):
            batch = event_ids[start:start + 500]
            placeholders = ",".join("?" for _ in batch)
            rows = conn.execute(
                f"SELECT record_id FROM json_records WHERE collection=? AND record_id IN ({placeholders})",
                [EXECUTION_EVENTS_FILE, *batch],
            ).fetchall()
            existing.update(str(row["record_id"]) for row in rows)
    return existing


def import_agent_execution_inbox(
    workspace_file: str | Path,
    *,
    inbox_dir: str | Path = "",
    max_files: int = 50,
    max_events: int = 20_000,
) -> dict[str, Any]:
    """Import bounded local DSH inbox files; repeated imports are idempotent."""
    store = WorkspaceStore(workspace_file)
    inbox = Path(inbox_dir).expanduser().resolve() if str(inbox_dir) else store.memory_dir / INBOX_DIR
    files = sorted(inbox.glob("*.jsonl"))[: max(1, min(max_files, 500))] if inbox.exists() else []
    candidates: dict[str, dict[str, Any]] = {}
    scanned = invalid = duplicate = 0
    bounded_events = max(1, min(max_events, 100_000))
    for path in files:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if scanned >= bounded_events:
                    break
                scanned += 1
                try:
                    event = _normalize_event(json.loads(line))
                except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
                    event = None
                if event is None:
                    invalid += 1
                    continue
                event_id = str(event["id"])
                if event_id in candidates:
                    duplicate += 1
                    continue
                candidates[event_id] = event
            if scanned >= bounded_events:
                break
    existing = _existing_event_ids(store, list(candidates))
    duplicate += len(existing)
    accepted = [event for event_id, event in candidates.items() if event_id not in existing]
    inserted = store.append_jsonl_batch(EXECUTION_EVENTS_FILE, accepted)
    return {
        "schema_version": SCHEMA_VERSION,
        "workspace": store.workspace_file.stem,
        "inbox_present": inbox.exists(),
        "file_count": len(files),
        "scanned_count": scanned,
        "inserted_count": inserted,
        "duplicate_count": duplicate,
        "invalid_count": invalid,
        "truncated": scanned >= bounded_events,
        "next_action": "运行 agent-execution-summary 查看本地执行树聚合。" if inserted or duplicate else "当前 inbox 没有可导入事件。",
    }


def _duration(start: int | None, end: int) -> int:
    return max(0, end - start) if start is not None else 0


def summarize_agent_execution(
    workspace_file: str | Path,
    *,
    limit_events: int = 20_000,
    limit_sessions: int = 20,
) -> dict[str, Any]:
    """Build bounded per-session execution summaries from imported metadata."""
    store = WorkspaceStore(workspace_file)
    events = store.read_jsonl_prefer_backend(EXECUTION_EVENTS_FILE, limit=max(1, min(limit_events, 100_000)))
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        session_id = str(event.get("source_session_id", "") or "")
        if session_id:
            grouped[session_id].append(event)
    sessions: list[dict[str, Any]] = []
    model_totals: dict[str, dict[str, int]] = defaultdict(lambda: {"calls": 0, "input_tokens": 0, "output_tokens": 0, "duration_ms": 0})
    tool_totals: dict[str, dict[str, int]] = defaultdict(lambda: {"calls": 0, "errors": 0, "duration_ms": 0})
    for session_id, rows in grouped.items():
        rows.sort(key=lambda item: (int(item.get("time_ms", 0) or 0), int(item.get("seq", 0) or 0)))
        turn_starts: dict[int, int] = {}
        step_starts: dict[tuple[int, int], int] = {}
        tool_starts: dict[str, tuple[int, str]] = {}
        turn_ms = model_ms = tool_ms = first_token_ms = 0
        input_tokens = output_tokens = errors = turns = steps = tool_calls = 0
        models: set[str] = set()
        tools: set[str] = set()
        for event in rows:
            event_type = str(event.get("event_type", "") or "")
            time_ms = int(event.get("time_ms", 0) or 0)
            turn = int(event.get("turn", 0) or 0)
            step = int(event.get("step", 0) or 0)
            key = (turn, step)
            if event.get("severity") == "error" or event.get("error_class"):
                errors += 1
            if event_type == "turn/start":
                turn_starts[turn] = time_ms
                turns += 1
            elif event_type == "turn/end":
                turn_ms += _duration(turn_starts.get(turn), time_ms)
            elif event_type == "step/start":
                step_starts[key] = time_ms
                steps += 1
            elif event_type == "assistant/chunk":
                if key in step_starts and first_token_ms == 0:
                    first_token_ms = _duration(step_starts.get(key), time_ms)
            elif event_type == "assistant/message":
                duration = _duration(step_starts.get(key), time_ms)
                model_ms += duration
                model = str(event.get("model", "") or "unknown")
                models.add(model)
                model_row = model_totals[model]
                model_row["calls"] += 1
                model_row["duration_ms"] += duration
                for field in ("input_tokens", "output_tokens"):
                    value = int(event.get(field, 0) or 0)
                    model_row[field] += value
                input_tokens += int(event.get("input_tokens", 0) or 0)
                output_tokens += int(event.get("output_tokens", 0) or 0)
            elif event_type == "tool/call":
                call_id = str(event.get("call_id", "") or f"{turn}:{step}:{time_ms}")
                tool = str(event.get("tool", "") or "unknown")
                tool_starts[call_id] = (time_ms, tool)
                tools.add(tool)
                tool_calls += 1
                tool_totals[tool]["calls"] += 1
            elif event_type == "tool/result":
                call_id = str(event.get("call_id", "") or "")
                started = tool_starts.get(call_id)
                tool = str(event.get("tool", "") or (started[1] if started else "unknown"))
                duration = _duration(started[0] if started else None, time_ms)
                tool_ms += duration
                tool_totals[tool]["duration_ms"] += duration
                if event.get("error_class") or event.get("severity") == "error":
                    tool_totals[tool]["errors"] += 1
        sessions.append({
            "session_id_sha256": _hash(session_id),
            "event_count": len(rows),
            "turn_count": turns,
            "step_count": steps,
            "tool_call_count": tool_calls,
            "error_count": errors,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "turn_duration_ms": turn_ms,
            "model_duration_ms": model_ms,
            "tool_duration_ms": tool_ms,
            "first_token_ms": first_token_ms,
            "models": sorted(models),
            "tools": sorted(tools),
            "last_event_at": rows[-1].get("created_at", ""),
        })
    sessions.sort(key=lambda item: str(item.get("last_event_at", "")), reverse=True)
    bounded_sessions = sessions[: max(1, min(limit_sessions, 200))]
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "agent_execution_summary",
        "event_count": len(events),
        "session_count": len(sessions),
        "sessions": bounded_sessions,
        "models": [{"model": name, **values} for name, values in sorted(model_totals.items())],
        "tools": [{"tool": name, **values} for name, values in sorted(tool_totals.items())],
        "privacy": "prompt, tool arguments, tool results, cwd, and message bodies are not ingested",
    }
