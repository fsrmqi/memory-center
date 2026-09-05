"""AML (Agent Memory Leaderboard) adapter — Add/Search contract surface.

Exposes the two memory operations AML requires (see
docs/MEMORY_ENRICHMENT_DESIGN.md §2 与 AML api-guide):

- ``POST /aml/add``    — write a conversation/event/document/engineering history
- ``POST /aml/search`` — return relevant memory evidence for a query + scope

Search output follows the leaderboard's ``selected`` contract: an ordered list
of ``{created_at, text}`` items rendered directly into evaluation prompts.
Nothing agent-oriented (next steps, guidance, receipts) and no private paths
ever leave the surface — the privacy polarity of the Observation Inbox applies
fail-closed here too.

Deployment: bind explicitly with ``memory-center aml-serve --host 0.0.0.0
--aml-key <key>``. Non-loopback binding without a key is refused (same rule as
the main HTTP server). The key is compared with ``hmac.compare_digest``.
"""
from __future__ import annotations

import hmac
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from memory_center.core.tasks.session_notes import NoteRejected, record_note, search_notes

AML_SCHEMA_VERSION = 1
AML_ADD_MAX_MESSAGES = 200
AML_MESSAGE_MAX_CHARS = 8000
AML_SEARCH_LIMIT_DEFAULT = 10
AML_SEARCH_LIMIT_MAX = 50
# Search text length mirrors the evidence-index item cap: prompts render every
# selected line, unbounded text would blow the evaluation context.
AML_TEXT_MAX_CHARS = 240


class AmlContractError(ValueError):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def _flatten_messages(messages: list[dict[str, Any]]) -> list[str]:
    """Extract role-tagged text lines from an AML add payload."""
    lines: list[str] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role", "") or "unknown").strip().lower()
        content = message.get("content", "")
        if isinstance(content, list):
            content = " ".join(str(part.get("text", "") or "") for part in content if isinstance(part, dict))
        text = " ".join(str(content or "").split())
        if text:
            lines.append(f"{role}: {text[:AML_MESSAGE_MAX_CHARS]}")
    return lines


def _entry_topic(entry_body: str) -> str:
    for line in entry_body.splitlines():
        stripped = line.strip()
        if stripped.startswith("**Intent**:"):
            return stripped.removeprefix("**Intent**:").strip()
    return ""


def aml_add(workspace_file: str | Path, payload: dict[str, Any]) -> dict[str, Any]:
    """AML Add: store the payload as narrative memory (L0.5 notes + L0 events).

    Accepts either ``messages`` (chat-shaped: [{role, content}]) or a plain
    ``text``/``document`` field. Each non-empty message becomes one Session
    Note (kind=fact by default, override with ``kind``); the write path is the
    same fail-closed note pipeline used everywhere else, so absolute paths and
    secret-shaped content are rejected with structured errors.
    """
    if not isinstance(payload, dict):
        raise AmlContractError("invalid_payload", "body must be a JSON object")
    messages = payload.get("messages")
    text = payload.get("text") or payload.get("document") or ""
    kind = str(payload.get("kind", "") or "fact").strip().lower()
    session_id = str(payload.get("session_id", "") or "aml-ingest").strip()[:120]
    if isinstance(messages, list):
        if len(messages) > AML_ADD_MAX_MESSAGES:
            raise AmlContractError("too_many_messages", f"messages exceeds {AML_ADD_MAX_MESSAGES}")
        lines = _flatten_messages(messages)
    else:
        lines = []
    if not lines and text:
        lines = [" ".join(str(text).split())[:AML_MESSAGE_MAX_CHARS]]
    if not lines:
        raise AmlContractError("empty_payload", "provide messages[] or text")

    recorded: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for index, line in enumerate(lines):
        try:
            result = record_note(workspace_file, line, kind=kind if kind in ("decision", "preference", "rule", "next_step", "fact") else "fact", session_id=session_id, origin="agent_summary")
        except NoteRejected as exc:
            rejected.append({"index": index, "reason": exc.code})
            continue
        recorded.append(
            {
                "note_id": result.get("note_id", ""),
                "duplicate": bool(result.get("duplicate")),
            }
        )
    return {
        "schema_version": AML_SCHEMA_VERSION,
        "status": "ok",
        "recorded": recorded,
        "rejected": rejected,
        "accepted_count": sum(1 for item in recorded if not item["duplicate"]),
        "duplicate_count": sum(1 for item in recorded if item["duplicate"]),
    }


def aml_search(workspace_file: str | Path, payload: dict[str, Any]) -> dict[str, Any]:
    """AML Search: ordered ``selected`` evidence for a query (leaderboard contract).

    Sources are the hybrid graph index (via the evidence-index projection) and
    L0.5 Session Notes, merged and ranked by score. Each item carries only
    ``created_at``/``text`` plus provenance metadata AML tolerates but does not
    require; text is path-redacted fail-closed.
    """
    if not isinstance(payload, dict):
        raise AmlContractError("invalid_payload", "body must be a JSON object")
    query = str(payload.get("query", "") or "").strip()
    if not query:
        raise AmlContractError("empty_query", "query is required")
    try:
        limit = max(1, min(int(payload.get("limit") or AML_SEARCH_LIMIT_DEFAULT), AML_SEARCH_LIMIT_MAX))
    except (TypeError, ValueError):
        limit = AML_SEARCH_LIMIT_DEFAULT

    from memory_center.core.orchestrator.evidence_index import build_evidence_index
    from memory_center.core.orchestrator.query import memory_query_hybrid
    from memory_center.core.storage.workspace import WorkspaceStore

    store = WorkspaceStore(workspace_file)
    try:
        query_result = memory_query_hybrid(workspace_file, query, limit=limit, view="evidence-index")
    except Exception as exc:  # 评测面 fail-soft：索引问题不应 500 整个评测批次
        query_result = build_evidence_index({"results": [], "workspace": store.base_dir.name}, store=store, query=query)
        query_result["query_error"] = str(exc)[:160]
    selected: list[dict[str, Any]] = []
    seen_texts: set[str] = set()
    for item in query_result.get("selected", []) or []:
        text = str(item.get("text", "") or "").strip()
        if not text or text in seen_texts:
            continue
        seen_texts.add(text)
        selected.append(
            {
                "created_at": str(item.get("created_at", "") or ""),
                "text": text[:AML_TEXT_MAX_CHARS],
                "source_layer": str(item.get("source_layer", "") or ""),
                "score": item.get("score", 0.0),
            }
        )
        if len(selected) >= limit:
            break
    for hit in search_notes(workspace_file, query, limit=limit):
        text = str(hit.get("text", "") or "").strip()
        if not text or text in seen_texts:
            continue
        seen_texts.add(text)
        selected.append(
            {
                "created_at": str(hit.get("created_at", "") or ""),
                "text": text[:AML_TEXT_MAX_CHARS],
                "source_layer": "L0.5_session_notes",
                "score": hit.get("score", 0.0),
            }
        )
        if len(selected) >= limit:
            break
    selected.sort(key=lambda item: (-float(item.get("score", 0.0) or 0.0), str(item.get("created_at", ""))))
    return {
        "schema_version": AML_SCHEMA_VERSION,
        "query": query,
        "selected": selected[:limit],
        "returned": len(selected[:limit]),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def check_aml_key(provided: str, required_key: str) -> bool:
    """Constant-time key comparison; empty required key disables the surface."""
    if not required_key:
        return False
    return hmac.compare_digest(str(provided or ""), str(required_key))


def read_aml_payload(handler) -> dict[str, Any]:
    """Read and validate a JSON object body from a BaseHTTPRequestHandler."""
    length = int(handler.headers.get("Content-Length", 0) or 0)
    if length <= 0:
        raise AmlContractError("empty_body", "JSON body required")
    if length > 1_000_000:
        raise AmlContractError("request_too_large", "body exceeds 1MB")
    raw = handler.rfile.read(length)
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise AmlContractError("invalid_payload", "body must be a JSON object")
    return payload


__all__ = [
    "AML_SCHEMA_VERSION",
    "AmlContractError",
    "aml_add",
    "aml_search",
    "check_aml_key",
    "read_aml_payload",
]
