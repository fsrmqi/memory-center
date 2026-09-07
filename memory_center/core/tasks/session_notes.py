"""Session Notes — L0.5 narrative memory layer (MEMORY_ENRICHMENT_DESIGN.md capability B).

A lightweight free-text memory layer between L0 structured events and L1 case
atoms: "what we decided, why, and what to do next" that survives across tasks.

Write paths are explicit only (admin action, confirmed close-time drafts,
case promotion). Governance mirrors the proposal: same-fingerprint writes are
no-ops, refined text supersedes (never physically deletes), explicit forget
hides only the named note. Privacy is fail-closed: absolute paths and secret
shapes are rejected, ``<private>`` spans are stripped before storage.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from memory_center.core.storage.workspace import WorkspaceStore

SESSION_NOTES_FILE = "session-notes.jsonl"
SESSION_NOTE_DECISIONS_FILE = "session-note-decisions.jsonl"
NOTE_KINDS = ("decision", "preference", "rule", "next_step", "fact")
NOTE_STATUSES = ("active", "superseded", "forgotten")
NOTE_TEXT_MAX_CHARS = 2000
NOTES_LIST_DEFAULT_LIMIT = 50
NOTES_LIST_MAX_LIMIT = 200
_NOTE_FINGERPRINT_MAX = 4096

# Fail-closed privacy guards (same polarity as the Observation Inbox):
# absolute Unix/Windows/home paths and common secret shapes are rejected.
_ABSOLUTE_PATH_RE = re.compile(r"(^|[\s\"'`(])((?:/[A-Za-z0-9._-])|(?:[A-Za-z]:\\)|(?:~/?[A-Za-z0-9_.]))")
_SECRET_RE = re.compile(r"(sk-[A-Za-z0-9_-]{12,}|Bearer\s+[A-Za-z0-9._-]{12,}|(?:api[_-]?key|secret|token|password)\s*[:=]\s*\S+)", re.IGNORECASE)
_PRIVATE_SPAN_RE = re.compile(r"<private>(.*?)</private>", re.DOTALL | re.IGNORECASE)


class NoteRejected(ValueError):
    def __init__(self, code: str, reason: str):
        super().__init__(reason)
        self.code = code
        self.reason = reason


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _redact(text: str) -> str:
    """Strip <private> spans and collapse whitespace. Raises nothing."""
    cleaned = _PRIVATE_SPAN_RE.sub("[已省略私有片段]", str(text or ""))
    return " ".join(cleaned.split())


def _check_privacy(text: str) -> None:
    if _ABSOLUTE_PATH_RE.search(text):
        raise NoteRejected("absolute_path_rejected", "note text must not contain absolute paths")
    if _SECRET_RE.search(text):
        raise NoteRejected("secret_shape_rejected", "note text must not contain secret-shaped content")


def note_fingerprint(kind: str, text: str) -> str:
    normalized = " ".join(str(text or "").split()).lower()[:_NOTE_FINGERPRINT_MAX]
    return hashlib.sha256(f"{kind}\u0000{normalized}".encode("utf-8")).hexdigest()[:16]


def _load_notes(store: WorkspaceStore) -> list[dict[str, Any]]:
    return store.read_jsonl_prefer_backend(SESSION_NOTES_FILE, limit=5000)


def project_note_statuses(
    notes: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
) -> dict[str, str]:
    """按 note_id 计算 status 投影：旧行字段打底，最新决策胜出。"""
    projection: dict[str, str] = {}
    for note in notes:
        note_id = str(note.get("note_id", "")).strip()
        if note_id:
            projection[note_id] = str(note.get("status", "active") or "active")
    for decision in decisions:
        note_id = str(decision.get("note_id", "")).strip()
        if note_id not in projection:
            continue
        if decision.get("decision") == "supersede":
            projection[note_id] = "superseded"
        elif decision.get("decision") == "forget":
            projection[note_id] = "forgotten"
    return projection


def _load_notes_with_statuses(store: WorkspaceStore) -> tuple[list[dict[str, Any]], dict[str, str], dict[str, dict[str, Any]]]:
    notes = _load_notes(store)
    decisions = store.read_jsonl_prefer_backend(SESSION_NOTE_DECISIONS_FILE, limit=5000)
    latest: dict[str, dict[str, Any]] = {}
    for decision in decisions:
        note_id = str(decision.get("note_id", "")).strip()
        if note_id:
            latest[note_id] = decision
    return notes, project_note_statuses(notes, decisions), latest


def _append_note_decision(
    store: WorkspaceStore,
    *,
    note_id: str,
    decision: str,
    superseded_by: str,
    reason: str,
) -> dict[str, Any]:
    record = {
        "record_type": "note_decision",
        "decision_id": "note-decision-"
        + hashlib.sha256(f"{note_id}|{decision}|{_now_iso()}".encode("utf-8")).hexdigest()[:16],
        "note_id": note_id,
        "decision": decision,
        "superseded_by": superseded_by,
        "reason": str(reason or "").strip(),
        "decided_at": _now_iso(),
    }
    store.append_jsonl(SESSION_NOTE_DECISIONS_FILE, record)
    return record


def record_note(
    workspace_file: str | Path,
    text: str,
    *,
    kind: str = "fact",
    session_id: str = "",
    origin: str = "agent_summary",
    source_refs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Record one narrative note; fingerprint no-op, refinement supersedes."""
    cleaned = _redact(text)
    if not cleaned:
        raise NoteRejected("empty_text", "note text is required")
    if len(cleaned) > NOTE_TEXT_MAX_CHARS:
        raise NoteRejected("text_too_long", f"note text exceeds {NOTE_TEXT_MAX_CHARS} chars")
    if kind not in NOTE_KINDS:
        raise NoteRejected("invalid_kind", f"kind must be one of {NOTE_KINDS}")
    if origin not in ("agent_summary", "user_explicit", "promotion"):
        raise NoteRejected("invalid_origin", f"origin must be one of agent_summary|user_explicit|promotion")
    _check_privacy(cleaned)

    store = WorkspaceStore(workspace_file)
    notes, statuses, _ = _load_notes_with_statuses(store)
    fingerprint = note_fingerprint(kind, cleaned)
    for row in notes:
        if statuses.get(str(row.get("note_id", "")), "active") != "active":
            continue
        if row.get("fingerprint") == fingerprint:
            return {
                "recorded": False,
                "duplicate": True,
                "note_id": row.get("note_id", ""),
                "reason": "fingerprint_noop",
            }

    seq = len(notes) + 1
    note_id = f"note:{session_id or 'adhoc'}:{seq}"
    note = {
        "note_id": note_id,
        "session_id": session_id,
        "created_at": _now_iso(),
        "kind": kind,
        "text": cleaned,
        "status": "active",
        "fingerprint": fingerprint,
        "superseded_by": "",
        "origin": origin,
        "source_refs": source_refs or [],
    }
    store.append_jsonl(SESSION_NOTES_FILE, note)
    from .receipts import build_write_receipt, persist_write_receipt

    persist_write_receipt(
        store,
        build_write_receipt(
            layer="L0.5_session_notes",
            action="note_record",
            scope="memory",
            target=note_id,
            target_file=f"memory/{SESSION_NOTES_FILE}",
            session_id=session_id,
            source_session_id=session_id,
        ),
    )
    return {"recorded": True, "duplicate": False, "note_id": note_id, "kind": kind}


def supersede_note(workspace_file: str | Path, note_id: str, new_text: str, *, kind: str = "") -> dict[str, Any]:
    """Replace one active note with refined text: append the replacement plus a
    supersede decision row; the original row is never rewritten."""
    cleaned = _redact(new_text)
    if not cleaned:
        raise NoteRejected("empty_text", "note text is required")
    _check_privacy(cleaned)
    store = WorkspaceStore(workspace_file)
    notes, statuses, _ = _load_notes_with_statuses(store)
    target = next((row for row in notes if row.get("note_id") == note_id), None)
    if not target:
        return {"superseded": False, "reason": "note_not_found", "note_id": note_id}
    projected_status = statuses.get(str(note_id), "active")
    if projected_status != "active":
        return {"superseded": False, "reason": f"note_{projected_status}", "note_id": note_id}

    resolved_kind = kind if kind in NOTE_KINDS else str(target.get("kind", "fact"))
    seq = len(notes) + 1
    session_id = str(target.get("session_id", "") or "")
    new_id = f"note:{session_id or 'adhoc'}:{seq}"
    replacement = {
        "note_id": new_id,
        "session_id": session_id,
        "created_at": _now_iso(),
        "kind": resolved_kind,
        "text": cleaned,
        "status": "active",
        "fingerprint": note_fingerprint(resolved_kind, cleaned),
        "superseded_by": "",
        "origin": str(target.get("origin", "agent_summary")),
        "source_refs": list(target.get("source_refs", []) or []),
    }
    store.append_jsonl(SESSION_NOTES_FILE, replacement)
    _append_note_decision(
        store,
        note_id=note_id,
        decision="supersede",
        superseded_by=new_id,
        reason="superseded_by_refinement",
    )
    from .receipts import build_write_receipt, persist_write_receipt

    persist_write_receipt(
        store,
        build_write_receipt(
            layer="L0.5_session_notes",
            action="note_supersede",
            scope="memory",
            target=f"{note_id}->{new_id}",
            target_file=f"memory/{SESSION_NOTES_FILE}",
            session_id=session_id,
        ),
    )
    return {"superseded": True, "note_id": note_id, "new_note_id": new_id}


def forget_note(workspace_file: str | Path, note_id: str, *, reason: str = "user_requested") -> dict[str, Any]:
    """Hide exactly one named note via an appended forget decision row."""
    store = WorkspaceStore(workspace_file)
    notes, statuses, _ = _load_notes_with_statuses(store)
    target = next((row for row in notes if row.get("note_id") == note_id), None)
    if not target:
        return {"forgotten": False, "reason": "note_not_found", "note_id": note_id}
    projected_status = statuses.get(str(note_id), "active")
    if projected_status == "forgotten":
        return {"forgotten": True, "note_id": note_id, "duplicate": True}
    _append_note_decision(
        store,
        note_id=note_id,
        decision="forget",
        superseded_by=f"forget:{reason}",
        reason=reason,
    )
    from .receipts import build_write_receipt, persist_write_receipt

    persist_write_receipt(
        store,
        build_write_receipt(
            layer="L0.5_session_notes",
            action="note_forget",
            scope="memory",
            target=note_id,
            target_file=f"memory/{SESSION_NOTES_FILE}",
            session_id=str(target.get("session_id", "") or ""),
        ),
    )
    return {"forgotten": True, "note_id": note_id, "duplicate": False}


def list_notes(
    workspace_file: str | Path,
    *,
    kind: str = "",
    status: str = "active",
    session_id: str = "",
    limit: int = NOTES_LIST_DEFAULT_LIMIT,
) -> dict[str, Any]:
    """List notes with optional filters; defaults to active only.

    status 是投影值：决策行（最新胜出）叠加在存储字段之上，返回的行会
    带上投影后的 status 与 superseded_by，不改写任何存储行。
    """
    store = WorkspaceStore(workspace_file)
    notes, statuses, latest = _load_notes_with_statuses(store)
    try:
        limit = max(1, min(int(limit), NOTES_LIST_MAX_LIMIT))
    except (TypeError, ValueError):
        limit = NOTES_LIST_DEFAULT_LIMIT
    matched = []
    for row in notes:
        annotated = dict(row)
        note_id = str(annotated.get("note_id", ""))
        projected = statuses.get(note_id, str(annotated.get("status", "active") or "active"))
        annotated["status"] = projected
        if projected != "active" and not str(annotated.get("superseded_by", "")).strip():
            annotated["superseded_by"] = str(latest.get(note_id, {}).get("superseded_by", "")).strip()
        if (
            (not status or annotated.get("status") == status)
            and (not kind or annotated.get("kind") == kind)
            and (not session_id or annotated.get("session_id") == session_id)
        ):
            matched.append(annotated)
    matched.sort(key=lambda row: str(row.get("created_at", "") or ""))
    return {
        "workspace": store.base_dir.name,
        "notes": matched[-limit:],
        "total_matched": len(matched),
        "kinds": sorted({str(row.get("kind", "")) for row in matched}),
    }


def search_notes(
    workspace_file: str | Path,
    query: str,
    *,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Bounded FTS-less note search (token overlap scoring) for active notes."""
    store = WorkspaceStore(workspace_file)
    tokens = {t for t in re.split(r"[\s,，。.;；:：?？!！]+", str(query or "").lower()) if t}
    if not tokens:
        return []
    notes, statuses, _ = _load_notes_with_statuses(store)
    scored: list[tuple[float, dict[str, Any]]] = []
    for row in notes:
        if statuses.get(str(row.get("note_id", "")), "active") != "active":
            continue
        text = str(row.get("text", "")).lower()
        if not text:
            continue
        hits = sum(1 for token in tokens if token in text)
        if hits:
            scored.append((hits / len(tokens), row))
    scored.sort(key=lambda pair: (-pair[0], str(pair[1].get("created_at", ""))))
    out: list[dict[str, Any]] = []
    for score, row in scored[: max(1, min(int(limit or 10), 20))]:
        out.append(
            {
                "note_id": row.get("note_id", ""),
                "created_at": row.get("created_at", ""),
                "text": row.get("text", ""),
                "kind": row.get("kind", ""),
                "session_id": row.get("session_id", ""),
                "score": round(score, 3),
            }
        )
    return out


def draft_notes_from_session(
    workspace_file: str | Path,
    session_id: str,
    *,
    summary: dict[str, Any],
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Deterministically extract draft notes from a closing session.

    Mechanical only (no model calls): the session intent becomes a ``decision``
    draft, unresolved risk points become ``next_step`` drafts, and delivery
    validation signals become ``fact`` drafts. Drafts are returned unrecorded —
    the caller must confirm before anything is persisted.
    """
    drafts: list[dict[str, Any]] = []
    intent = _redact(str(summary.get("intent", "") or ""))
    if not intent:
        # Fresh sessions have no summary row yet; the intent lives on the
        # session_start event payload.
        for event in events:
            if str(event.get("event_type", "") or "") == "session_start":
                intent = _redact(str(event.get("intent", "") or ""))
                break
    if intent:
        drafts.append({"kind": "decision", "text": intent[:NOTE_TEXT_MAX_CHARS], "source": "session_intent"})
    for risk in list(summary.get("risk_points", []) or [])[:3]:
        text = _redact(str(risk if isinstance(risk, str) else (risk or {}).get("summary", "")))
        if text:
            drafts.append({"kind": "next_step", "text": f"待解决: {text}"[:NOTE_TEXT_MAX_CHARS], "source": "risk_points"})
    for event in events[-20:]:
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        if str(event.get("event_type", "") or "") != "delivery" and "validation" not in str(event.get("event_type", "") or ""):
            continue
        status = str(payload.get("status", "") or "")
        command_digest = _redact(str(payload.get("summary", "") or ""))[:160]
        if status in ("passed", "verified") and command_digest:
            drafts.append({"kind": "fact", "text": f"验证通过: {command_digest}", "source": "delivery_validation"})
    # Never draft text that would be rejected on record.
    return [draft for draft in drafts if not _SECRET_RE.search(draft["text"]) and not _ABSOLUTE_PATH_RE.search(draft["text"])]


__all__ = [
    "NOTE_KINDS",
    "NOTE_STATUSES",
    "NOTE_TEXT_MAX_CHARS",
    "SESSION_NOTES_FILE",
    "SESSION_NOTE_DECISIONS_FILE",
    "NoteRejected",
    "draft_notes_from_session",
    "forget_note",
    "list_notes",
    "note_fingerprint",
    "project_note_statuses",
    "record_note",
    "search_notes",
    "supersede_note",
]
