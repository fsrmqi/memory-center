"""Task Shadow — Session-first 会话影子层（L1）。

按 docs/SESSION_FIRST_TASK_CONTINUITY_PROPOSAL.md 实现：
- TaskShadowSnapshot 是源 harness（DSH/其他）投递的脱敏 whole-value 快照；
- MC 内部按 (source_provider_id, source_session_id) 保存独立 contribution，
  每个 contribution 只接受严格递增的 durable 水位（source-local last-wins）；
- 对外 TaskShadow 是所有活跃 contribution 的确定性 merge projection；
- Shadow 永不直接写 L2 task artifact，只有显式 bind 之后才允许 promote；
- volatile 快照不允许进入 MC（fail-closed）。

幂等键: (shadow_id, source_provider_id, source_session_id, durable_as_of_seq)。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from memory_center.core.foundation.schemas import with_schema
from memory_center.core.tasks.receipts import build_write_receipt, persist_write_receipt
from memory_center.core.storage.workspace import WorkspaceStore
from memory_center.core.workspace.config import load_workspace_config

SHADOW_STATE_TYPE = "task_shadow_v1"
SHADOW_CONTRIB_STATE_PREFIX = "task_shadow_contrib_v1:"
SHADOW_STATE_MAX_SESSIONS = 200

SHADOW_STATE_SCHEMA_VERSION = 1

BINDING_STATUSES = ("unbound", "suggested", "bound")
CONFIDENCE_LEVELS = ("low", "medium", "high")

# source contribution 允许的脱敏字段；schema 校验 fail-closed，
# 出现在快照里的未知字段直接拒收。
CONTRIBUTION_ALLOWED_FIELDS = (
    "intent_summary",
    "candidate_tasks",
    "candidate_files",
    "evidence_refs",
    "unresolved_items",
    "next_actions",
)
CONTRIBUTION_LIST_LIMITS = {
    "candidate_tasks": 20,
    "candidate_files": 60,
    "evidence_refs": 40,
    "unresolved_items": 30,
    "next_actions": 30,
}
INTENT_SUMMARY_MAX_CHARS = 400
STRING_LIST_ITEM_MAX_CHARS = 200

DELIVERY_MODE_DURABLE = "durable"
DELIVERY_MODE_VOLATILE = "volatile"
DELIVERY_MODES = (DELIVERY_MODE_DURABLE, DELIVERY_MODE_VOLATILE)


class ShadowSnapshotRejected(ValueError):
    """快照未通过 schema/水位/隐私校验，MC 拒收并要求调用方修正。"""

    def __init__(self, code: str, reason: str):
        super().__init__(reason)
        self.code = code
        self.reason = reason


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm_str_list(value: Any, *, limit: int, item_key: str) -> list[str]:
    if not isinstance(value, list):
        raise ShadowSnapshotRejected("invalid_field", f"{item_key} must be a list")
    items: list[str] = []
    for entry in value:
        if isinstance(entry, str):
            text = " ".join(entry.split())
        elif isinstance(entry, dict):
            # 结构化候选（如带 score 的 task 候选）压成稳定 JSON 文本再入库
            try:
                text = json.dumps(entry, ensure_ascii=False, sort_keys=True)
            except (TypeError, ValueError):
                raise ShadowSnapshotRejected("invalid_field", f"{item_key} contains non-serializable entry")
        else:
            raise ShadowSnapshotRejected("invalid_field", f"{item_key} contains non-string entry")
        if not text:
            continue
        items.append(text[:STRING_LIST_ITEM_MAX_CHARS])
        if len(items) >= limit:
            break
    return items


def validate_shadow_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """校验并规范化一个入站 Shadow Snapshot（fail-closed）。

    返回规范化后的快照；不合法输入抛 ShadowSnapshotRejected，
    由 adapter 负责 receipt 与重试，MC 不做部分接受。
    """
    if not isinstance(snapshot, dict):
        raise ShadowSnapshotRejected("invalid_schema", "snapshot must be a JSON object")
    shadow_id = str(snapshot.get("shadow_id", "") or "").strip()
    provider = str(snapshot.get("source_provider_id", "") or "").strip()
    source_session_id = str(snapshot.get("source_session_id", "") or "").strip()
    if not shadow_id or not provider or not source_session_id:
        raise ShadowSnapshotRejected("invalid_schema", "shadow_id, source_provider_id, source_session_id are required")
    if any("/" in part or "\\" in part or part in (".", "..") for part in (shadow_id, provider, source_session_id)):
        raise ShadowSnapshotRejected("invalid_identity", "identity fields must not contain path separators")

    delivery_mode = str(snapshot.get("delivery_mode", DELIVERY_MODE_DURABLE) or DELIVERY_MODE_DURABLE).strip()
    if delivery_mode not in DELIVERY_MODES:
        raise ShadowSnapshotRejected("invalid_delivery_mode", f"delivery_mode must be one of {DELIVERY_MODES}")
    if delivery_mode == DELIVERY_MODE_VOLATILE:
        # 提案 11.3 约束 5：volatile 快照不得发送给 MC，仅存在于源内存/UI。
        raise ShadowSnapshotRejected("volatile_rejected", "volatile snapshots must not be delivered to Memory Center")

    observed = snapshot.get("observed_as_of_seq")
    durable = snapshot.get("durable_as_of_seq")
    if not isinstance(observed, int) or isinstance(observed, bool) or observed < 0:
        raise ShadowSnapshotRejected("invalid_watermark", "observed_as_of_seq must be a non-negative integer")
    if not isinstance(durable, int) or isinstance(durable, bool) or durable < 0:
        raise ShadowSnapshotRejected("invalid_watermark", "durable_as_of_seq must be a non-negative integer")
    if observed != durable:
        raise ShadowSnapshotRejected(
            "watermark_not_durable",
            "observed_as_of_seq must equal durable_as_of_seq for MC delivery",
        )
    event_count = snapshot.get("durable_event_count")
    if not isinstance(event_count, int) or isinstance(event_count, bool) or event_count < 0:
        raise ShadowSnapshotRejected("invalid_watermark", "durable_event_count must be a non-negative integer")
    state_version = snapshot.get("state_version", SHADOW_STATE_SCHEMA_VERSION)
    if not isinstance(state_version, int) or isinstance(state_version, bool) or state_version < 1:
        raise ShadowSnapshotRejected("invalid_state_version", "state_version must be a positive integer")

    unknown = sorted(set(snapshot) - {f for f in (
        "shadow_id", "source_provider_id", "source_instance_id", "source_session_id",
        "lineage", "observed_as_of_seq", "durable_as_of_seq", "durable_event_count",
        "source_revision_hint", "delivery_mode", "state_version", "intent_summary",
        "candidate_tasks", "candidate_files", "evidence_refs", "unresolved_items",
        "next_actions", "binding_status",
    )})
    if unknown:
        raise ShadowSnapshotRejected("unknown_field", f"snapshot carries fields outside the allowlist: {', '.join(unknown[:6])}")

    intent_summary = " ".join(str(snapshot.get("intent_summary", "") or "").split())[:INTENT_SUMMARY_MAX_CHARS]
    normalized: dict[str, Any] = {
        "shadow_id": shadow_id,
        "source_provider_id": provider,
        "source_session_id": source_session_id,
        "source_instance_id": str(snapshot.get("source_instance_id", "") or "")[:120],
        "observed_as_of_seq": observed,
        "durable_as_of_seq": durable,
        "durable_event_count": event_count,
        "source_revision_hint": str(snapshot.get("source_revision_hint", "") or "")[:120],
        "delivery_mode": delivery_mode,
        "state_version": state_version,
        "intent_summary": intent_summary,
    }
    lineage = snapshot.get("lineage") or {}
    if not isinstance(lineage, dict):
        raise ShadowSnapshotRejected("invalid_field", "lineage must be an object")
    parent = str(lineage.get("parent_session_id", "") or "")[:160]
    fork_seq = lineage.get("fork_seq", 0)
    if not isinstance(fork_seq, int) or isinstance(fork_seq, bool) or fork_seq < 0:
        raise ShadowSnapshotRejected("invalid_field", "lineage.fork_seq must be a non-negative integer")
    normalized["lineage"] = {"parent_session_id": parent, "fork_seq": fork_seq}

    binding_status = str(snapshot.get("binding_status", "") or "").strip()
    if binding_status and binding_status not in BINDING_STATUSES:
        raise ShadowSnapshotRejected("invalid_field", f"binding_status must be one of {BINDING_STATUSES}")

    for field, limit in CONTRIBUTION_LIST_LIMITS.items():
        normalized[field] = _norm_str_list(snapshot.get(field, []) or [], limit=limit, item_key=field)
    return normalized


def _shadow_id_from_source(provider: str, source_session_id: str) -> str:
    """thread/session 派生的默认 shadow_id：provider:session 维度确定性生成。"""
    return f"shadow:{provider}:{source_session_id}"


SHADOW_SOURCE_MAP_STATE_TYPE = "task_shadow_source_map_v1"


def register_shadow_source(
    store: WorkspaceStore,
    source_kind: str,
    source_session_id: str,
    shadow_id: str,
) -> None:
    """把 `(source_kind, source_session_id)` 注册到确定的 shadow_id。

    Snapshot 投递与 Observation 折叠都经由该映射解析同一个 Shadow，
    保证两条路径落在同一实体上；authority 切换因此对所有路径生效。
    source_kind 可传 provider 前缀（如 `dsh-task-shadow`）或 harness
    种类（`dsh`）；两者都会登记，kind 粒度的 key 供 Observation 查询。
    """
    now = _now_iso()
    for kind_key in {str(source_kind or "").strip(), str(source_kind or "").split("-")[0]}:
        if not kind_key:
            continue
        store.memory_backend().upsert_session_state(
            SHADOW_SOURCE_MAP_STATE_TYPE,
            f"{kind_key}::{source_session_id}",
            {"shadow_id": shadow_id},
            updated_at=now,
        )


def resolve_shadow_for_source(store: WorkspaceStore, source_kind: str, source_session_id: str) -> str:
    """查显式映射；未注册时回退确定性派生 id（observation provider）。"""
    now = _now_iso()
    for kind_key in {str(source_kind or "").strip(), str(source_kind or "").split("-")[0]}:
        if not kind_key:
            continue
        payload = store.memory_backend().get_session_state(SHADOW_SOURCE_MAP_STATE_TYPE, f"{kind_key}::{source_session_id}")
        if isinstance(payload, dict) and payload.get("shadow_id"):
            return str(payload["shadow_id"])
    return _shadow_id_from_source(f"{source_kind}-observation@1", source_session_id)


def _shadow_key(shadow_id: str) -> str:
    return f"{SHADOW_STATE_TYPE}:{shadow_id}"


def _contrib_state_type(shadow_id: str) -> str:
    return f"{SHADOW_CONTRIB_STATE_PREFIX}{shadow_id}"


def _contrib_key(provider: str, source_session_id: str) -> str:
    return f"{provider}::{source_session_id}"


def load_shadow_state(store: WorkspaceStore, shadow_id: str) -> dict[str, Any] | None:
    payload = store.memory_backend().get_session_state(SHADOW_STATE_TYPE, shadow_id)
    return payload if isinstance(payload, dict) else None


def load_contributions(store: WorkspaceStore, shadow_id: str) -> dict[str, dict[str, Any]]:
    raw = store.memory_backend().get_session_state(_contrib_state_type(shadow_id), "contributions")
    if not isinstance(raw, dict):
        return {}
    return {key: value for key, value in raw.items() if isinstance(key, str) and isinstance(value, dict)}


def save_shadow_state(store: WorkspaceStore, shadow_id: str, state: dict[str, Any]) -> None:
    store.memory_backend().upsert_session_state(SHADOW_STATE_TYPE, shadow_id, state, updated_at=_now_iso())


def save_contributions(store: WorkspaceStore, shadow_id: str, contributions: dict[str, dict[str, Any]]) -> None:
    store.memory_backend().upsert_session_state(
        _contrib_state_type(shadow_id), "contributions", contributions, updated_at=_now_iso()
    )
    store.memory_backend().prune_session_states(
        f"{SHADOW_CONTRIB_STATE_PREFIX}%", max_sessions=SHADOW_STATE_MAX_SESSIONS * 10
    )


def merge_contributions(contributions: dict[str, dict[str, Any]], *, max_files: int = 40, max_refs: int = 20) -> dict[str, Any]:
    """确定性 merge：排序后 union，与 contribution 迭代顺序无关。

    - candidate_files / evidence_refs：去重 union，保序输出；
    - unresolved_items / next_actions：去重 union（source 归属保留在条目前缀里）；
    - intent_summary：取最新 contribution 水位最高的那条；
    - candidate_tasks：JSON 文本去重 union，由调用方在展示前解析。
    """
    files: list[str] = []
    refs: list[str] = []
    unresolved: list[str] = []
    actions: list[str] = []
    tasks: list[str] = []
    for key in sorted(contributions):
        contrib = contributions[key]
        for field, sink in (
            ("candidate_files", files),
            ("evidence_refs", refs),
            ("unresolved_items", unresolved),
            ("next_actions", actions),
            ("candidate_tasks", tasks),
        ):
            for item in contrib.get(field, []) or []:
                if item and item not in sink:
                    sink.append(item)
    ordered = sorted(contributions.items(), key=lambda kv: (-int(kv[1].get("durable_as_of_seq", 0) or 0), kv[0]))
    intent_summary = ""
    for _, contrib in ordered:
        if contrib.get("intent_summary"):
            intent_summary = str(contrib["intent_summary"])
            break
    return {
        "intent_summary": intent_summary,
        "candidate_tasks": tasks[:20],
        "candidate_files": files[:max_files],
        "evidence_refs": refs[:max_refs],
        "unresolved_items": unresolved[:30],
        "next_actions": actions[:30],
    }


def build_merged_shadow(workspace_file: str | Path, shadow_id: str) -> dict[str, Any] | None:
    store = WorkspaceStore(workspace_file)
    state = load_shadow_state(store, shadow_id)
    if state is None:
        return None
    contributions = load_contributions(store, shadow_id)
    active = {key: value for key, value in contributions.items() if not value.get("disposed")}
    merged = merge_contributions(active)
    return {
        "schema_version": SHADOW_STATE_SCHEMA_VERSION,
        "kind": "task_shadow",
        "shadow_id": shadow_id,
        "workspace": state.get("workspace", ""),
        "session_ids": state.get("session_ids", []),
        "binding_status": state.get("binding_status", "unbound"),
        "bound_task_id": state.get("bound_task_id", ""),
        "confidence": state.get("confidence", "low"),
        "shadow_authority": state.get("shadow_authority", "snapshot"),
        "created_at": state.get("created_at", ""),
        "updated_at": state.get("updated_at", ""),
        "revision": int(state.get("revision", 0) or 0),
        "contributions": [
            {
                "source_provider_id": value.get("source_provider_id", ""),
                "source_session_id": value.get("source_session_id", ""),
                "durable_as_of_seq": value.get("durable_as_of_seq", 0),
                "durable_event_count": value.get("durable_event_count", 0),
                "state_version": value.get("state_version", 1),
                "disposed": bool(value.get("disposed", False)),
                "updated_at": value.get("updated_at", ""),
            }
            for key, value in sorted(contributions.items())
        ],
        "merged": merged,
    }


def record_shadow_snapshot(
    workspace_file: str | Path,
    snapshot: dict[str, Any],
    *,
    shadow_id: str = "",
) -> dict[str, Any]:
    """接收一个 durable Shadow Snapshot：校验 → 幂等去重 → 更新 contribution。

    返回 {accepted, shadow_id, durable_as_of_seq, ...}；被拒收时抛
    ShadowSnapshotRejected，调用方（adapter/MCP 边界）负责写 receipt。
    """
    normalized = validate_shadow_snapshot(snapshot)
    provider = normalized["source_provider_id"]
    source_session_id = normalized["source_session_id"]
    resolved_shadow_id = (shadow_id or "").strip() or normalized["shadow_id"] or _shadow_id_from_source(provider, source_session_id)

    _, store = load_workspace_config(workspace_file), WorkspaceStore(workspace_file)
    # Snapshot 是该 source 的权威 Shadow 写入者：注册映射，让后续 Observation
    # 折叠到同一 Shadow 并受其 shadow_authority 约束。
    register_shadow_source(store, provider.split("@")[0], source_session_id, resolved_shadow_id)
    state = load_shadow_state(store, resolved_shadow_id) or {
        "workspace": "",
        "session_ids": [],
        "binding_status": "unbound",
        "bound_task_id": "",
        "confidence": "low",
        "shadow_authority": "snapshot",
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "revision": 0,
    }
    state["workspace"] = state.get("workspace") or ""
    if source_session_id not in state["session_ids"]:
        state["session_ids"] = [*state["session_ids"], source_session_id][-20:]

    contributions = load_contributions(store, resolved_shadow_id)
    key = _contrib_key(provider, source_session_id)
    current = contributions.get(key)
    incoming_seq = normalized["durable_as_of_seq"]
    if current is not None:
        current_seq = int(current.get("durable_as_of_seq", 0) or 0)
        if incoming_seq < current_seq:
            return {
                "accepted": False,
                "duplicate": True,
                "reason": "stale_watermark",
                "shadow_id": resolved_shadow_id,
                "source_provider_id": provider,
                "source_session_id": source_session_id,
                "durable_as_of_seq": current_seq,
                "rejected_seq": incoming_seq,
            }
        if incoming_seq == current_seq:
            # 同水位重复投递：幂等 no-op（提案 11.3 约束 2）
            return {
                "accepted": False,
                "duplicate": True,
                "reason": "idempotent_noop",
                "shadow_id": resolved_shadow_id,
                "source_provider_id": provider,
                "source_session_id": source_session_id,
                "durable_as_of_seq": current_seq,
            }
        current_state_version = int(current.get("state_version", 1) or 1)
        incoming_state_version = int(normalized["state_version"] or 1)
        if incoming_state_version < current_state_version:
            # 提案 11.3 约束 8 方向性：旧 schema 快照不能覆盖新 schema 折叠结果
            return {
                "accepted": False,
                "duplicate": False,
                "reason": "state_version_regression",
                "shadow_id": resolved_shadow_id,
                "required_action": "adapter_resync_with_current_schema",
                "shadow_stale": False,
            }
        if incoming_state_version > current_state_version:
            # 新 schema：MC 无源日志不可重折叠，标记 stale 并要求 adapter 重投
            state["confidence"] = "low"
            state["shadow_stale"] = True
            state["stale_reason"] = "state_version_ahead_of_mc"
    else:
        if int(normalized["state_version"] or 1) > SHADOW_STATE_SCHEMA_VERSION:
            state["shadow_stale"] = True
            state["stale_reason"] = "state_version_ahead_of_mc"

    contributions[key] = {
        "source_provider_id": provider,
        "source_session_id": source_session_id,
        "source_instance_id": normalized["source_instance_id"],
        "lineage": normalized["lineage"],
        "durable_as_of_seq": incoming_seq,
        "durable_event_count": normalized["durable_event_count"],
        "source_revision_hint": normalized["source_revision_hint"],
        "state_version": normalized["state_version"],
        "intent_summary": normalized["intent_summary"],
        **{field: normalized[field] for field in CONTRIBUTION_LIST_LIMITS},
        "updated_at": _now_iso(),
        "disposed": False,
    }

    state["revision"] = int(state.get("revision", 0) or 0) + 1
    state["updated_at"] = _now_iso()
    state.pop("shadow_stale", None) if not state.get("shadow_stale") else None
    save_contributions(store, resolved_shadow_id, contributions)
    save_shadow_state(store, resolved_shadow_id, state)

    receipt = persist_write_receipt(
        store,
        build_write_receipt(
            layer="L1_task_shadow",
            action="task_shadow_snapshot_sync",
            scope="task_shadow",
            target=resolved_shadow_id,
            target_file=f"session_state/{_contrib_state_type(resolved_shadow_id)}",
            source_session_id=source_session_id,
            bytes_written=len(json.dumps(contributions[key], ensure_ascii=False).encode("utf-8")),
        ),
    )
    return {
        "accepted": True,
        "shadow_id": resolved_shadow_id,
        "source_provider_id": provider,
        "source_session_id": source_session_id,
        "durable_as_of_seq": incoming_seq,
        "binding_status": state.get("binding_status", "unbound"),
        "shadow_stale": bool(state.get("shadow_stale", False)),
        "write_receipt": receipt,
    }


def ensure_shadow_for_session(
    workspace_file: str | Path,
    session_id: str,
    intent: str = "",
    *,
    shadow_id: str = "",
) -> dict[str, Any]:
    """mc_start 时调用：创建或续接 session 所属的 Shadow（不写 L2）。"""
    _, store = load_workspace_config(workspace_file), WorkspaceStore(workspace_file)
    resolved_shadow_id = (shadow_id or "").strip() or _shadow_id_from_source("memory-center", session_id)
    # MC 内部 session 也是一路 source：注册映射，保证 Observation/Snapshot/
    # session 三条路径解析到同一个 Shadow。
    register_shadow_source(store, "memory-center", session_id, resolved_shadow_id)
    state = load_shadow_state(store, resolved_shadow_id)
    created = False
    if state is None:
        created = True
        state = {
            "workspace": "",
            "session_ids": [session_id],
            "binding_status": "unbound",
            "bound_task_id": "",
            "confidence": "low",
            # MC 内部 session 路径由 session 事件/intent 折叠，authority=observation；
            # snapshot 路径的 Shadow 由 record_shadow_snapshot 创建（authority=snapshot）。
            "shadow_authority": "observation",
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
            "revision": 0,
        }
    if session_id not in state["session_ids"]:
        state["session_ids"] = [*state["session_ids"], session_id][-20:]
    if intent:
        key = _contrib_key("memory-center", session_id)
        contributions = load_contributions(store, resolved_shadow_id)
        current = contributions.get(key) or {
            "source_provider_id": "memory-center",
            "source_session_id": session_id,
            "source_instance_id": "",
            "lineage": {"parent_session_id": "", "fork_seq": 0},
            "durable_as_of_seq": 0,
            "durable_event_count": 0,
            "source_revision_hint": "",
            "state_version": SHADOW_STATE_SCHEMA_VERSION,
        }
        # MC 内部自产 contribution 的水位用 session 事件数近似（无外部日志）
        current_seq = int(current.get("durable_as_of_seq", 0) or 0) + 1
        current["durable_as_of_seq"] = current_seq
        current["durable_event_count"] = current_seq
        current["intent_summary"] = " ".join(str(intent).split())[:INTENT_SUMMARY_MAX_CHARS]
        current["updated_at"] = _now_iso()
        current["disposed"] = False
        contributions[key] = current
        save_contributions(store, resolved_shadow_id, contributions)
    state["updated_at"] = _now_iso()
    state["revision"] = int(state.get("revision", 0) or 0) + 1
    save_shadow_state(store, resolved_shadow_id, state)
    receipt = persist_write_receipt(
        store,
        build_write_receipt(
            layer="L1_task_shadow",
            action="task_shadow_ensure" if not created else "task_shadow_create",
            scope="task_shadow",
            target=resolved_shadow_id,
            target_file=f"session_state/{_shadow_key(resolved_shadow_id)}",
            session_id=session_id,
            bytes_written=0,
        ),
    )
    return {
        "shadow_id": resolved_shadow_id,
        "created": created,
        "binding_status": state["binding_status"],
        "bound_task_id": state.get("bound_task_id", ""),
        "session_ids": state["session_ids"],
        "write_receipt": receipt,
    }


def bind_shadow_to_task(
    workspace_file: str | Path,
    shadow_id: str,
    task_id: str,
    *,
    expected_revision: int | None = None,
    source: str = "explicit",
    confidence: str = "high",
) -> dict[str, Any]:
    """CAS 绑定 Shadow → 正式 task。stale revision 拒绝（提案 11.2.1-6）。

    revision 条件检查与写入在同一个 SQLite 事务内完成（cas_session_state），
    两个进程读到相同 revision 时只有一个绑定成功。
    """
    _, store = load_workspace_config(workspace_file), WorkspaceStore(workspace_file)
    state = load_shadow_state(store, shadow_id)
    if state is None:
        raise ValueError(f"unknown task shadow: {shadow_id}")
    current_revision = int(state.get("revision", 0) or 0)
    if expected_revision is not None and expected_revision != current_revision:
        return {
            "bound": False,
            "reason": "stale_revision",
            "shadow_id": shadow_id,
            "expected_revision": expected_revision,
            "current_revision": current_revision,
        }
    from memory_center.core.tasks.artifacts import _resolve_task_dir

    try:
        _resolve_task_dir(store, task_id)
    except ValueError as exc:
        raise ValueError(f"unknown task space: {task_id}") from exc
    next_state = dict(state)
    next_state["binding_status"] = "bound"
    next_state["bound_task_id"] = task_id
    next_state["confidence"] = confidence if confidence in CONFIDENCE_LEVELS else "high"
    next_state["updated_at"] = _now_iso()
    # 原子 CAS：WHERE revision = current_revision，行数非 1 即并发败者
    if not store.memory_backend().cas_session_state(
        SHADOW_STATE_TYPE,
        shadow_id,
        next_state,
        expected_revision=current_revision,
        updated_at=next_state["updated_at"],
    ):
        latest = load_shadow_state(store, shadow_id) or {}
        return {
            "bound": False,
            "reason": "stale_revision",
            "shadow_id": shadow_id,
            "expected_revision": current_revision,
            "current_revision": int(latest.get("revision", 0) or 0),
        }
    state = load_shadow_state(store, shadow_id) or next_state
    receipt = persist_write_receipt(
        store,
        build_write_receipt(
            layer="L1_task_shadow",
            action=f"task_shadow_bind:{source}",
            scope="task_shadow",
            target=shadow_id,
            target_file=f"session_state/{_shadow_key(shadow_id)}",
            task_id=task_id,
            bytes_written=len(json.dumps({"bound_task_id": task_id}, ensure_ascii=False).encode("utf-8")),
        ),
    )
    return {
        "bound": True,
        "shadow_id": shadow_id,
        "task_id": task_id,
        "revision": state["revision"],
        "binding_status": state["binding_status"],
        "write_receipt": receipt,
    }


def suggest_shadow_binding(
    workspace_file: str | Path,
    shadow_id: str,
    candidate_tasks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """把候选任务写入 suggested 状态（不写 L2，不确定不写原则）。"""
    _, store = load_workspace_config(workspace_file), WorkspaceStore(workspace_file)
    state = load_shadow_state(store, shadow_id)
    if state is None:
        raise ValueError(f"unknown task shadow: {shadow_id}")
    if state.get("binding_status") == "bound":
        return {"suggested": False, "reason": "already_bound", "shadow_id": shadow_id, "bound_task_id": state.get("bound_task_id", "")}
    normalized_candidates = []
    for candidate in (candidate_tasks or [])[:10]:
        if isinstance(candidate, dict) and candidate.get("task_id"):
            normalized_candidates.append({
                "task_id": str(candidate["task_id"])[:160],
                "title": str(candidate.get("title", "") or "")[:200],
                "score": candidate.get("score", 0),
            })
    state["binding_status"] = "suggested"
    state["candidate_tasks"] = normalized_candidates
    state["confidence"] = "medium" if normalized_candidates else "low"
    state["updated_at"] = _now_iso()
    current_revision = int(state.get("revision", 0) or 0)
    if not store.memory_backend().cas_session_state(
        SHADOW_STATE_TYPE,
        shadow_id,
        state,
        expected_revision=current_revision,
        updated_at=state["updated_at"],
    ):
        return {"suggested": False, "reason": "concurrent_modification", "shadow_id": shadow_id}
    receipt = persist_write_receipt(
        store,
        build_write_receipt(
            layer="L1_task_shadow",
            action="task_shadow_suggest",
            scope="task_shadow",
            target=shadow_id,
            target_file=f"session_state/{_shadow_key(shadow_id)}",
            bytes_written=len(json.dumps(normalized_candidates, ensure_ascii=False).encode("utf-8")),
        ),
    )
    return {"suggested": True, "shadow_id": shadow_id, "candidate_tasks": normalized_candidates, "binding_status": "suggested", "write_receipt": receipt}


def discard_shadow(
    workspace_file: str | Path,
    shadow_id: str,
    *,
    reason: str = "user_requested",
) -> dict[str, Any]:
    """丢弃 Shadow：默认选项"保留为临时工作影子"的显式反面；retention 清理也走这里。"""
    _, store = load_workspace_config(workspace_file), WorkspaceStore(workspace_file)
    state = load_shadow_state(store, shadow_id)
    if state is None:
        return {"discarded": False, "reason": "shadow_not_found", "shadow_id": shadow_id}
    bound_task_id = str(state.get("bound_task_id", "") or "")
    shadow = build_merged_shadow(workspace_file, shadow_id) or {}
    receipt = persist_write_receipt(
        store,
        build_write_receipt(
            layer="L1_task_shadow",
            action=f"task_shadow_discard:{reason}",
            scope="task_shadow",
            target=shadow_id,
            target_file=f"session_state/{_shadow_key(shadow_id)}",
            task_id=bound_task_id,
            bytes_written=0,
        ),
    )
    store.memory_backend().delete_session_state(SHADOW_STATE_TYPE, shadow_id)
    store.memory_backend().delete_session_state(_contrib_state_type(shadow_id), "contributions")
    return {
        "discarded": True,
        "shadow_id": shadow_id,
        "reason": reason,
        "bound_task_id": bound_task_id,
        "session_summary_kept": True,
        "merged_at_discard": (shadow.get("merged") or {}),
        "write_receipt": receipt,
    }


def promote_shadow_to_task(
    workspace_file: str | Path,
    shadow_id: str,
    *,
    task_id: str = "",
    title: str = "",
) -> dict[str, Any]:
    """显式升格：把 Shadow 摘要/evidence 合并进 L2 task（仅 bound 后允许）。"""
    from memory_center.core.tasks.artifacts import (
        append_task_change_log,
        create_task_space,
        get_task_artifact,
        update_task_artifact,
    )
    from memory_center.core.orchestrator.shared import _merge_artifact_section

    _, store = load_workspace_config(workspace_file), WorkspaceStore(workspace_file)
    state = load_shadow_state(store, shadow_id)
    if state is None:
        raise ValueError(f"unknown task shadow: {shadow_id}")
    if state.get("binding_status") != "bound" or not state.get("bound_task_id"):
        # 物化条件：必须满足可信绑定（提案第 7 节）；未绑定时不创建 L2
        candidates = state.get("candidate_tasks", []) or []
        return {
            "promoted": False,
            "reason": "shadow_not_bound",
            "shadow_id": shadow_id,
            "binding_status": state.get("binding_status", "unbound"),
            "required_action": "bind_shadow_to_task_first",
            "candidate_tasks": candidates[:5],
        }
    resolved_task_id = (task_id or "").strip() or str(state.get("bound_task_id", "") or "")
    if not resolved_task_id:
        raise ValueError("promote requires a bound task or explicit task_id")
    try:
        get_task_artifact(workspace_file, resolved_task_id, "context")
    except ValueError:
        if (task_id or "").strip() and not (task_id or "").strip() == str(state.get("bound_task_id", "")):
            created = create_task_space(workspace_file, title=title or f"shadow:{shadow_id}", intent="")
            resolved_task_id = str(created["task_id"])
        else:
            raise

    shadow = build_merged_shadow(workspace_file, shadow_id) or {}
    merged = shadow.get("merged") or {}
    files: list[str] = []
    for item in merged.get("candidate_files", []):
        if not isinstance(item, str) or not item:
            continue
        if item.startswith("{"):
            # 结构化候选（normalize 阶段压成 JSON 文本）恢复 path 字段
            try:
                path = str(json.loads(item).get("path", "") or "")
            except (json.JSONDecodeError, AttributeError):
                path = ""
            if path:
                files.append(path)
        else:
            files.append(item)
    summary_lines = [f"### Shadow Snapshot {shadow_id}", ""]
    if merged.get("intent_summary"):
        summary_lines += [f"- intent: {merged['intent_summary']}"]
    if files:
        summary_lines += [f"- candidate files ({len(files)}): " + ", ".join(files[:10])]
    if merged.get("unresolved_items"):
        summary_lines += [f"- unresolved: {len(merged['unresolved_items'])} item(s)"]
    if merged.get("next_actions"):
        summary_lines += ["- next actions:"]
        summary_lines += [f"  - {action[:160]}" for action in merged["next_actions"][:5]]
    summary_lines += [f"- synced from shadow at {datetime.now(timezone.utc).isoformat()}"]
    existing = ""
    try:
        existing = str(get_task_artifact(workspace_file, resolved_task_id, "context").get("content", "") or "")
    except Exception:
        existing = ""
    updated = _merge_artifact_section(existing, "Task Shadow", "\n".join(summary_lines))
    update_task_artifact(workspace_file, resolved_task_id, "context", updated, source="promote_shadow_to_task")
    append_task_change_log(
        workspace_file,
        resolved_task_id,
        f"shadow {shadow_id} promoted: {len(files)} candidate files, seq watermark {_max_contribution_seq(store, shadow_id)}",
    )
    state["revision"] = int(state.get("revision", 0) or 0) + 1
    state["updated_at"] = _now_iso()
    save_shadow_state(store, shadow_id, state)
    receipt = persist_write_receipt(
        store,
        build_write_receipt(
            layer="L2_task_spaces",
            action="promote_shadow_to_task",
            scope="task_space",
            target=resolved_task_id,
            target_file=f"tasks/{resolved_task_id}",
            task_id=resolved_task_id,
            bytes_written=len(updated.encode("utf-8")),
        ),
    )
    return {
        "promoted": True,
        "shadow_id": shadow_id,
        "task_id": resolved_task_id,
        "candidate_file_count": len(files),
        "write_receipt": receipt,
    }


def _max_contribution_seq(store: WorkspaceStore, shadow_id: str) -> int:
    contributions = load_contributions(store, shadow_id)
    return max((int(value.get("durable_as_of_seq", 0) or 0) for value in contributions.values()), default=0)


def shadow_retention_cleanup(
    workspace_file: str | Path,
    *,
    older_than_days: int = 14,
    max_shadows: int = SHADOW_STATE_MAX_SESSIONS,
    apply: bool = False,
) -> dict[str, Any]:
    """未绑定且过期的 Shadow 按 retention 清理；bound/有 case 的不受影响。"""
    _, store = load_workspace_config(workspace_file), WorkspaceStore(workspace_file)
    backend = store.memory_backend()
    rows = backend.list_session_states(SHADOW_STATE_TYPE, limit=max_shadows * 4)
    cutoff = _now_iso()
    candidates: list[str] = []
    for row in rows:
        state = row.get("payload", {}) if isinstance(row.get("payload"), dict) else {}
        if state.get("binding_status") == "bound":
            continue
        updated_at = str(row.get("updated_at", "") or "")
        if not updated_at:
            continue
        try:
            age_days = (datetime.now(timezone.utc) - datetime.fromisoformat(updated_at)).days
        except ValueError:
            continue
        if age_days >= older_than_days:
            candidates.append(str(row.get("session_id", "") or ""))
    if apply:
        for shadow_id in candidates:
            discard_shadow(workspace_file, shadow_id, reason="retention")
    return {
        "workspace": "",
        "candidates": candidates,
        "candidate_count": len(candidates),
        "applied": apply,
        "cutoff_now": cutoff,
        "older_than_days": older_than_days,
    }


__all__ = [
    "SHADOW_STATE_TYPE",
    "SHADOW_STATE_SCHEMA_VERSION",
    "BINDING_STATUSES",
    "ShadowSnapshotRejected",
    "validate_shadow_snapshot",
    "record_shadow_snapshot",
    "ensure_shadow_for_session",
    "build_merged_shadow",
    "merge_contributions",
    "bind_shadow_to_task",
    "suggest_shadow_binding",
    "discard_shadow",
    "promote_shadow_to_task",
    "shadow_retention_cleanup",
]
