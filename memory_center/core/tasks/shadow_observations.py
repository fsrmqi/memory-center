"""Observation Inbox — 跨 harness 的最小事实收件箱（提案 11.9）。

Observation 是 L0/Shadow 的输入，不直接写 L2。adapter 用
(source_kind, source_session_id, event_seq) 幂等去重；
schema/大小/字段 allowlist fail-closed。

Observation 与 Shadow Snapshot 的 authority 关系：
- authority=observation（默认）：Observation 折叠为该 source 的 contribution；
- authority=snapshot：Observation 只保留 L0 审计证据，不覆盖 Shadow 字段。
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from filelock import FileLock

from memory_center.core.tasks.receipts import build_write_receipt, persist_write_receipt
from memory_center.core.storage.workspace import WorkspaceStore
from memory_center.core.workspace.config import load_workspace_config

OBSERVATIONS_FILE = "task-shadow-observations.jsonl"
OBSERVATION_SEQ_STATE_TYPE = "task_shadow_observation_seq_v1"
OBSERVATION_KINDS = (
    "session_boundary",
    "tool_fact",
    "candidate_file",
    "validation",
    "handoff",
    "task_hint",
)
SOURCE_KINDS = ("dsh", "codex", "claude", "other")

# payload 字段允许列表（提案 11.9）：默认拒绝完整 prompt、工具 payload、
# 源码正文、完整模型回复、绝对私有路径。
PAYLOAD_ALLOWED_KEYS = (
    "tool_name",
    "query_summary",
    "candidate_files",
    "validation_status",
    "validation_command_digest",
    "risk_level",
    "next_action_summary",
    "task_hint",
    "boundary",
    "generation",
)
QUERY_SUMMARY_MAX_CHARS = 200
PAYLOAD_MAX_BYTES = 8 * 1024
_RISK_LEVELS = ("low", "medium", "high")

# 绝对路径 heuristic：/ Unix 盘符或 Windows 盘符；允许列表里不提供路径字段，
# 出现即拒收（fail-closed），不做静默截断。
_ABSOLUTE_PATH_RE = re.compile(r"(^|[\s\"'])((?:/[A-Za-z0-9._-])|(?:[A-Za-z]:\\))")


class ObservationRejected(ValueError):
    def __init__(self, code: str, reason: str):
        super().__init__(reason)
        self.code = code
        self.reason = reason


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _check_no_absolute_paths(text: str, field: str) -> None:
    if _ABSOLUTE_PATH_RE.search(text):
        raise ObservationRejected("absolute_path_rejected", f"{field} must not contain absolute paths")


def validate_observation(observation: dict[str, Any]) -> dict[str, Any]:
    """校验并规范化一个入站 Observation（fail-closed，不做静默裁剪）。"""
    if not isinstance(observation, dict):
        raise ObservationRejected("invalid_schema", "observation must be a JSON object")
    source_kind = str(observation.get("source_kind", "") or "").strip()
    if source_kind not in SOURCE_KINDS:
        raise ObservationRejected("invalid_source_kind", f"source_kind must be one of {SOURCE_KINDS}")
    source_session_id = str(observation.get("source_session_id", "") or "").strip()
    if not source_session_id:
        raise ObservationRejected("invalid_schema", "source_session_id is required")
    if "/" in source_session_id or "\\" in source_session_id:
        raise ObservationRejected("invalid_identity", "source_session_id must not contain path separators")
    event_seq = observation.get("event_seq")
    if not isinstance(event_seq, int) or isinstance(event_seq, bool) or event_seq < 0:
        raise ObservationRejected("invalid_seq", "event_seq must be a non-negative integer")
    kind = str(observation.get("kind", "") or "").strip()
    if kind not in OBSERVATION_KINDS:
        raise ObservationRejected("invalid_kind", f"kind must be one of {OBSERVATION_KINDS}")

    payload = observation.get("payload")
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ObservationRejected("invalid_payload", "payload must be a JSON object")
    unknown = sorted(set(payload) - set(PAYLOAD_ALLOWED_KEYS))
    if unknown:
        raise ObservationRejected("payload_field_rejected", f"payload fields outside allowlist: {', '.join(unknown[:6])}")

    normalized_payload: dict[str, Any] = {}
    for key in PAYLOAD_ALLOWED_KEYS:
        value = payload.get(key)
        if value is None:
            continue
        if key == "candidate_files":
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise ObservationRejected("invalid_payload", "candidate_files must be a list of strings")
            files = []
            for item in value:
                text = " ".join(item.split())[:STRING_ITEM_LIMIT]
                if text:
                    _check_no_absolute_paths(text, "candidate_files[]")
                    files.append(text)
            normalized_payload[key] = files[:20]
            continue
        if key == "risk_level":
            level = str(value).strip().lower()
            if level and level not in _RISK_LEVELS:
                raise ObservationRejected("invalid_payload", f"risk_level must be one of {_RISK_LEVELS}")
            if level:
                normalized_payload[key] = level
            continue
        if isinstance(value, (dict, list)):
            raise ObservationRejected("invalid_payload", f"{key} must be a scalar")
        text = " ".join(str(value).split())
        _check_no_absolute_paths(text, key)
        if not text:
            continue
        normalized_payload[key] = text[:STRING_ITEM_LIMIT]

    try:
        payload_bytes = len(json.dumps(normalized_payload, ensure_ascii=False).encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise ObservationRejected("invalid_payload", f"payload not serializable: {exc}") from exc
    if payload_bytes > PAYLOAD_MAX_BYTES:
        raise ObservationRejected("payload_too_large", f"payload exceeds {PAYLOAD_MAX_BYTES} bytes")

    return {
        "source_kind": source_kind,
        "source_session_id": source_session_id,
        "event_seq": event_seq,
        "kind": kind,
        "payload": normalized_payload,
        "observed_at": str(observation.get("observed_at", "") or "") or _now_iso(),
    }


STRING_ITEM_LIMIT = 200


def record_observation(
    workspace_file: str | Path,
    observation: dict[str, Any],
    *,
    fold_into_shadow: bool = True,
) -> dict[str, Any]:
    """接收一个 Observation：校验 → 幂等去重 → L0 落盘 → 可选折叠进 Shadow。

    authority=snapshot 时 fold_into_shadow 被忽略（Observation 只做 L0 审计）。
    """
    normalized = validate_observation(observation)
    _, store = load_workspace_config(workspace_file), WorkspaceStore(workspace_file)
    dedup_key = f"{normalized['source_kind']}::{normalized['source_session_id']}"
    seq_state = store.memory_backend().get_session_state(OBSERVATION_SEQ_STATE_TYPE, dedup_key) or {}
    seen_seqs: dict[str, int] = seq_state.get("max_event_seq_by_kind_prefix", {}) or {}
    highest = int(seq_state.get("max_event_seq", -1) if seq_state.get("max_event_seq") is not None else -1)
    if normalized["event_seq"] <= highest:
        return {
            "recorded": False,
            "duplicate": True,
            "reason": "stale_or_duplicate_event_seq",
            "source_kind": normalized["source_kind"],
            "source_session_id": normalized["source_session_id"],
            "event_seq": normalized["event_seq"],
            "max_event_seq": highest,
        }

    record = dict(normalized)
    record["observation_id"] = f"obs:{normalized['source_kind']}:{normalized['source_session_id']}:{normalized['event_seq']}"
    stored = store.append_jsonl(OBSERVATIONS_FILE, record)
    store.memory_backend().upsert_session_state(
        OBSERVATION_SEQ_STATE_TYPE,
        dedup_key,
        {"max_event_seq": normalized["event_seq"]},
        updated_at=_now_iso(),
    )
    receipt = persist_write_receipt(
        store,
        build_write_receipt(
            layer="L0_session_events",
            action="task_shadow_observation_record",
            scope="memory",
            target=record["observation_id"],
            target_file=f"memory/{OBSERVATIONS_FILE}",
            source_session_id=normalized["source_session_id"],
            payload_ref=f"memory/{OBSERVATIONS_FILE}#{stored.get('created_at', '')}",
            bytes_written=len(json.dumps(record, ensure_ascii=False).encode("utf-8")),
        ),
    )

    folded: dict[str, Any] | None = None
    if fold_into_shadow:
        folded = _fold_observation_into_shadow(workspace_file, store, normalized)
    return {
        "recorded": True,
        "observation_id": record["observation_id"],
        "source_kind": normalized["source_kind"],
        "source_session_id": normalized["source_session_id"],
        "event_seq": normalized["event_seq"],
        "folded_into_shadow": bool(folded and folded.get("folded")),
        "shadow_fold": folded or {},
        "write_receipt": receipt,
    }


def _fold_observation_into_shadow(
    workspace_file: str | Path,
    store: WorkspaceStore,
    normalized: dict[str, Any],
) -> dict[str, Any]:
    """把 Observation 增量折叠为 source-local Shadow contribution。

    authority=snapshot 时仅返回审计标记，不覆盖 Shadow 字段。
    """
    from .shadow import (
        SHADOW_STATE_TYPE,
        _contrib_key,
        _contrib_state_type,
        load_contributions,
        load_shadow_state,
        resolve_shadow_for_source,
        save_contributions,
        save_shadow_state,
    )

    provider = f"{normalized['source_kind']}-observation@1"
    source_session_id = normalized["source_session_id"]
    # 经 source→shadow 映射解析：Snapshot/MC session 已注册的 Shadow 会在此
    # 命中，Observation 与 Snapshot 因此落在同一实体上；authority 检查对该
    # Shadow 生效。
    with FileLock(str(store.shadow_lock_file)):
        shadow_id = resolve_shadow_for_source(store, normalized["source_kind"], source_session_id)
        state = load_shadow_state(store, shadow_id)
        if state is not None and state.get("shadow_authority") == "snapshot":
            return {"folded": False, "reason": "shadow_authority_is_snapshot", "shadow_id": shadow_id}

        payload = normalized["payload"]
        contributions = load_contributions(store, shadow_id)
        key = _contrib_key(provider, source_session_id)
        current = contributions.get(key) or {
            "source_provider_id": provider,
            "source_session_id": source_session_id,
            "source_instance_id": "",
            "lineage": {"parent_session_id": "", "fork_seq": 0},
            "durable_as_of_seq": 0,
            "durable_event_count": 0,
            "source_revision_hint": "",
            "state_version": 1,
            "intent_summary": "",
            "candidate_tasks": [],
            "candidate_files": [],
            "evidence_refs": [],
            "unresolved_items": [],
            "next_actions": [],
        }
        seq = normalized["event_seq"]
        if seq <= int(current.get("durable_as_of_seq", 0) or 0):
            return {"folded": False, "reason": "stale_observation_seq", "shadow_id": shadow_id}

        kind = normalized["kind"]
        if payload.get("tool_name"):
            current["evidence_refs"] = (current.get("evidence_refs") or [])[-39:] + [
                f"{kind}:{payload['tool_name']}@seq{seq}"
            ]
        if kind == "candidate_file":
            for item in payload.get("candidate_files", []) or []:
                if item and item not in (current.get("candidate_files") or []):
                    current["candidate_files"] = (current.get("candidate_files") or [])[-59:] + [item]
        if kind == "task_hint" and payload.get("task_hint"):
            hint = payload["task_hint"]
            if hint not in (current.get("candidate_tasks") or []):
                current["candidate_tasks"] = (current.get("candidate_tasks") or [])[-19:] + [hint]
        if payload.get("next_action_summary"):
            action = payload["next_action_summary"]
            if action not in (current.get("next_actions") or []):
                current["next_actions"] = (current.get("next_actions") or [])[-29:] + [action]
        if payload.get("validation_status"):
            marker = f"validation:{payload['validation_status']}@seq{seq}"
            current["evidence_refs"] = (current.get("evidence_refs") or [])[-39:] + [marker]
        current["durable_as_of_seq"] = seq
        current["durable_event_count"] = seq + 1
        current["updated_at"] = _now_iso()
        contributions[key] = current

        if state is None:
            state = {
                "workspace": "",
                "session_ids": [source_session_id],
                "binding_status": "unbound",
                "bound_task_id": "",
                "confidence": "low",
                "shadow_authority": "observation",
                "created_at": _now_iso(),
                "updated_at": _now_iso(),
                "revision": 0,
            }
        if source_session_id not in state["session_ids"]:
            state["session_ids"] = [*state["session_ids"], source_session_id][-20:]
        state["revision"] = int(state.get("revision", 0) or 0) + 1
        state["updated_at"] = _now_iso()
        save_contributions(store, shadow_id, contributions)
        save_shadow_state(store, shadow_id, state)
    return {"folded": True, "shadow_id": shadow_id, "durable_as_of_seq": seq}


def list_observations(
    workspace_file: str | Path,
    *,
    source_kind: str = "",
    source_session_id: str = "",
    kind: str = "",
    limit: int = 50,
) -> dict[str, Any]:
    _, store = load_workspace_config(workspace_file), WorkspaceStore(workspace_file)
    rows = store.read_jsonl_via_backend(OBSERVATIONS_FILE, limit=5000)
    matched = []
    for row in rows:
        if source_kind and row.get("source_kind") != source_kind:
            continue
        if source_session_id and row.get("source_session_id") != source_session_id:
            continue
        if kind and row.get("kind") != kind:
            continue
        matched.append(row)
    return {
        "workspace": "",
        "observations": matched[-max(1, limit):],
        "summary": {
            "total": len(matched),
            "kinds": sorted({row.get("kind", "") for row in matched if row.get("kind")}),
            "source_kinds": sorted({row.get("source_kind", "") for row in matched if row.get("source_kind")}),
        },
    }


def set_shadow_authority(
    workspace_file: str | Path,
    shadow_id: str,
    authority: str,
) -> dict[str, Any]:
    """显式切换 shadow_authority（observation|snapshot）；迁移时旧 contribution 先关闭。"""
    from .shadow import _shadow_key, load_contributions, load_shadow_state, save_contributions, save_shadow_state
    from .receipts import build_write_receipt, persist_write_receipt

    if authority not in ("observation", "snapshot"):
        raise ValueError("authority must be observation or snapshot")
    store = WorkspaceStore(workspace_file)
    with FileLock(str(store.shadow_lock_file)):
        state = load_shadow_state(store, shadow_id)
        if state is None:
            raise ValueError(f"unknown task shadow: {shadow_id}")
        previous = str(state.get("shadow_authority", "snapshot") or "snapshot")
        state["shadow_authority"] = authority
        state["revision"] = int(state.get("revision", 0) or 0) + 1
        state["updated_at"] = _now_iso()
        if authority == "snapshot" and previous == "observation":
            # 迁移：关闭 observation contribution（dispose，保留 receipt 审计）
            contributions = load_contributions(store, shadow_id)
            for value in contributions.values():
                if str(value.get("source_provider_id", "")).endswith("-observation@1"):
                    value["disposed"] = True
            save_contributions(store, shadow_id, contributions)
        save_shadow_state(store, shadow_id, state)
    receipt = persist_write_receipt(
        store,
        build_write_receipt(
            layer="L1_task_shadow",
            action=f"task_shadow_authority:{authority}",
            scope="task_shadow",
            target=shadow_id,
            target_file=f"session_state/{_shadow_key(shadow_id)}",
            bytes_written=0,
        ),
    )
    return {
        "shadow_id": shadow_id,
        "shadow_authority": authority,
        "previous_authority": previous,
        "write_receipt": receipt,
        "note": "observation contributions disposed on switch to snapshot" if authority == "snapshot" and previous == "observation" else "",
    }


__all__ = [
    "OBSERVATIONS_FILE",
    "OBSERVATION_KINDS",
    "SOURCE_KINDS",
    "PAYLOAD_ALLOWED_KEYS",
    "ObservationRejected",
    "validate_observation",
    "record_observation",
    "list_observations",
    "set_shadow_authority",
]
