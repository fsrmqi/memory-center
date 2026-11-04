"""Handoff Claim — 有状态的会话交接协议（提案 11.9）。

handoff 不是提示词约定而是有状态协议：
    draft → handed_off → claimed → closed|expired|cancelled

- claim 必须携带 handoff_id + expected_revision（CAS）；
- 同一 handoff 只允许一个成功 claim；
- stale revision 返回冲突，不覆盖先到接手者；
- handoff 可以关联 Task Shadow，但不自动创建正式 task。

所有状态迁移使用 cas_session_state：revision 条件检查与写入在同一个
SQLite 事务内完成，跨进程并发下 CAS 保证 claim-once。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from memory_center.core.tasks.receipts import build_write_receipt, persist_write_receipt
from memory_center.core.storage.workspace import WorkspaceStore
from memory_center.core.workspace.config import load_workspace_config

HANDOFF_STATE_TYPE = "task_shadow_handoff_v1"
HANDOFF_STATUSES = ("draft", "handed_off", "claimed", "closed", "expired", "cancelled")
TERMINAL_STATUSES = ("closed", "expired", "cancelled")
DEFAULT_EXPIRE_HOURS = 72


class HandoffConflict(ValueError):
    def __init__(self, code: str, reason: str):
        super().__init__(reason)
        self.code = code
        self.reason = reason


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _handoff_key(handoff_id: str) -> str:
    return f"{HANDOFF_STATE_TYPE}:{handoff_id}"


def _load(store: WorkspaceStore, handoff_id: str) -> dict[str, Any] | None:
    payload = store.memory_backend().get_session_state(HANDOFF_STATE_TYPE, handoff_id)
    return payload if isinstance(payload, dict) else None


def _save(store: WorkspaceStore, state: dict[str, Any]) -> None:
    """Insert-only save for a freshly created draft（初建 revision=1）；
    后续所有状态迁移必须走 _cas_transition，不得直接覆盖。"""
    store.memory_backend().upsert_session_state(
        HANDOFF_STATE_TYPE, str(state["handoff_id"]), state, updated_at=_now_iso()
    )


def _cas_transition(
    store: WorkspaceStore,
    state: dict[str, Any],
    *,
    mutate: Any,
) -> tuple[dict[str, Any] | None, int]:
    """原子状态迁移：在 SQLite 事务内校验 revision 并写入。

    mutate(state) 就地修改状态；返回 (new_state, None) 成功，
    (None, current_revision) 并发败者。revision 检查与写入在同一个
    cas_session_state 事务里，两个进程读到同一 revision 只有一个成功。
    """
    current_revision = int(state.get("revision", 0) or 0)
    next_state = dict(state)
    mutate(next_state)
    # cas_session_state 在事务内写入 revision=current+1；这里同步递增，
    # 使调用方拿到的 new_state["revision"] 与落库值一致。
    next_state["revision"] = current_revision + 1
    next_state["updated_at"] = _now_iso()
    if store.memory_backend().cas_session_state(
        HANDOFF_STATE_TYPE,
        str(state["handoff_id"]),
        next_state,
        expected_revision=current_revision,
        updated_at=next_state["updated_at"],
    ):
        return next_state, None
    latest = _load(store, str(state["handoff_id"])) or {}
    return None, int(latest.get("revision", 0) or 0)


def create_handoff(
    workspace_file: str | Path,
    *,
    from_session_id: str,
    shadow_id: str = "",
    to_agent_hint: str = "",
    expire_hours: int = DEFAULT_EXPIRE_HOURS,
) -> dict[str, Any]:
    """创建 handoff draft。shadow_id 只做关联，不触发任何 L2 写入。"""
    _, store = load_workspace_config(workspace_file), WorkspaceStore(workspace_file)
    from memory_center.core.tasks.shadow import load_shadow_state

    shadow_id = (shadow_id or "").strip()
    if shadow_id and load_shadow_state(store, shadow_id) is None:
        raise ValueError(f"unknown task shadow: {shadow_id}")
    # uuid4 nonce：同 session 同秒重复创建不会覆盖已有 draft（主键唯一）
    handoff_id = f"handoff:{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}:{from_session_id[:40]}:{uuid4().hex[:8]}"
    state = {
        "handoff_id": handoff_id,
        "shadow_id": shadow_id,
        "from_session_id": from_session_id,
        "to_agent_hint": (to_agent_hint or "").strip()[:160],
        "revision": 1,
        "status": "draft",
        "claimed_by_session_id": "",
        "claimed_at": "",
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=max(1, expire_hours))).isoformat(),
    }
    _save(store, state)
    receipt = persist_write_receipt(
        store,
        build_write_receipt(
            layer="L1_task_shadow",
            action="task_shadow_handoff_create",
            scope="task_shadow",
            target=handoff_id,
            target_file=f"session_state/{_handoff_key(handoff_id)}",
            session_id=from_session_id,
            bytes_written=len(json.dumps(state, ensure_ascii=False).encode("utf-8")),
        ),
    )
    return {**state, "write_receipt": receipt}


def mark_handed_off(
    workspace_file: str | Path,
    handoff_id: str,
    *,
    expected_revision: int,
) -> dict[str, Any]:
    """draft → handed_off（CAS）。只有 draft 状态允许交接。"""
    _, store = load_workspace_config(workspace_file), WorkspaceStore(workspace_file)
    state = _load(store, handoff_id)
    if state is None:
        raise HandoffConflict("handoff_not_found", f"unknown handoff: {handoff_id}")
    if state["status"] != "draft":
        return {"handed_off": False, "reason": f"invalid_status_{state['status']}", "handoff_id": handoff_id, "status": state["status"]}
    if expected_revision != int(state["revision"]):
        return {
            "handed_off": False,
            "reason": "stale_revision",
            "handoff_id": handoff_id,
            "expected_revision": expected_revision,
            "current_revision": int(state["revision"]),
        }

    def _mutate(next_state: dict[str, Any]) -> None:
        next_state["status"] = "handed_off"

    new_state, current_revision_after = _cas_transition(store, state, mutate=_mutate)
    if new_state is None:
        return {
            "handed_off": False,
            "reason": "stale_revision",
            "handoff_id": handoff_id,
            "expected_revision": expected_revision,
            "current_revision": current_revision_after,
        }
    receipt = persist_write_receipt(
        store,
        build_write_receipt(
            layer="L1_task_shadow",
            action="task_shadow_handoff_handed_off",
            scope="task_shadow",
            target=handoff_id,
            target_file=f"session_state/{_handoff_key(handoff_id)}",
            session_id=state["from_session_id"],
            bytes_written=0,
        ),
    )
    return {"handed_off": True, "handoff_id": handoff_id, "revision": new_state["revision"], "status": new_state["status"], "write_receipt": receipt}


def claim_handoff(
    workspace_file: str | Path,
    handoff_id: str,
    *,
    claimed_by_session_id: str,
    expected_revision: int,
) -> dict[str, Any]:
    """handed_off → claimed（claim-once CAS）。stale revision 返回冲突。"""
    _, store = load_workspace_config(workspace_file), WorkspaceStore(workspace_file)
    state = _load(store, handoff_id)
    if state is None:
        raise HandoffConflict("handoff_not_found", f"unknown handoff: {handoff_id}")
    if not claimed_by_session_id.strip():
        raise HandoffConflict("missing_claimant", "claimed_by_session_id is required")
    if state["status"] in TERMINAL_STATUSES:
        return {"claimed": False, "reason": f"handoff_{state['status']}", "handoff_id": handoff_id, "status": state["status"]}
    if state["status"] == "claimed":
        return {
            "claimed": False,
            "reason": "already_claimed",
            "handoff_id": handoff_id,
            "claimed_by_session_id": state.get("claimed_by_session_id", ""),
        }
    if state["status"] == "draft":
        return {"claimed": False, "reason": "handoff_not_handed_off_yet", "handoff_id": handoff_id, "status": "draft"}
    if _expired(state):
        # 过期是状态变更：同样走 CAS + receipt（提案"所有状态变更写 receipt"）
        def _expire(next_state: dict[str, Any]) -> None:
            next_state["status"] = "expired"

        new_state, _ = _cas_transition(store, state, mutate=_expire)
        if new_state is not None:
            persist_write_receipt(
                store,
                build_write_receipt(
                    layer="L1_task_shadow",
                    action="task_shadow_handoff_expire",
                    scope="task_shadow",
                    target=handoff_id,
                    target_file=f"session_state/{_handoff_key(handoff_id)}",
                    bytes_written=0,
                ),
            )
        return {"claimed": False, "reason": "handoff_expired", "handoff_id": handoff_id, "expires_at": state["expires_at"]}
    if expected_revision != int(state["revision"]):
        return {
            "claimed": False,
            "reason": "stale_revision",
            "handoff_id": handoff_id,
            "expected_revision": expected_revision,
            "current_revision": int(state["revision"]),
        }

    def _claim(next_state: dict[str, Any]) -> None:
        next_state["status"] = "claimed"
        next_state["claimed_by_session_id"] = claimed_by_session_id.strip()[:120]
        next_state["claimed_at"] = _now_iso()

    new_state, current_revision_after = _cas_transition(store, state, mutate=_claim)
    if new_state is None:
        return {
            "claimed": False,
            "reason": "stale_revision",
            "handoff_id": handoff_id,
            "expected_revision": expected_revision,
            "current_revision": current_revision_after,
        }
    receipt = persist_write_receipt(
        store,
        build_write_receipt(
            layer="L1_task_shadow",
            action="task_shadow_handoff_claim",
            scope="task_shadow",
            target=handoff_id,
            target_file=f"session_state/{_handoff_key(handoff_id)}",
            session_id=claimed_by_session_id,
            bytes_written=0,
        ),
    )
    return {
        "claimed": True,
        "handoff_id": handoff_id,
        "claimed_by_session_id": new_state["claimed_by_session_id"],
        "revision": new_state["revision"],
        "shadow_id": new_state.get("shadow_id", ""),
        "write_receipt": receipt,
    }


def _expired(state: dict[str, Any]) -> bool:
    expires_at = str(state.get("expires_at", "") or "")
    if not expires_at:
        return False
    try:
        return datetime.fromisoformat(expires_at) < datetime.now(timezone.utc)
    except ValueError:
        return False


def close_handoff(
    workspace_file: str | Path,
    handoff_id: str,
    *,
    expected_revision: int,
    outcome: str = "completed",
) -> dict[str, Any]:
    """claimed/handed_off → closed（CAS）。close 时仅已 claim/bound 的会话可升格同一 task。"""
    _, store = load_workspace_config(workspace_file), WorkspaceStore(workspace_file)
    state = _load(store, handoff_id)
    if state is None:
        raise HandoffConflict("handoff_not_found", f"unknown handoff: {handoff_id}")
    if state["status"] in ("closed", "cancelled"):
        return {"closed": False, "reason": f"already_{state['status']}", "handoff_id": handoff_id}
    if expected_revision != int(state["revision"]):
        return {
            "closed": False,
            "reason": "stale_revision",
            "handoff_id": handoff_id,
            "current_revision": int(state["revision"]),
        }

    def _close(next_state: dict[str, Any]) -> None:
        next_state["status"] = "closed"
        next_state["outcome"] = outcome[:120]

    new_state, current_revision_after = _cas_transition(store, state, mutate=_close)
    if new_state is None:
        return {
            "closed": False,
            "reason": "stale_revision",
            "handoff_id": handoff_id,
            "current_revision": current_revision_after,
        }
    receipt = persist_write_receipt(
        store,
        build_write_receipt(
            layer="L1_task_shadow",
            action="task_shadow_handoff_close",
            scope="task_shadow",
            target=handoff_id,
            target_file=f"session_state/{_handoff_key(handoff_id)}",
            session_id=state.get("claimed_by_session_id", "") or state["from_session_id"],
            bytes_written=0,
        ),
    )
    return {
        "closed": True,
        "handoff_id": handoff_id,
        "outcome": new_state["outcome"],
        "revision": new_state["revision"],
        "write_receipt": receipt,
    }


def get_handoff(workspace_file: str | Path, handoff_id: str) -> dict[str, Any]:
    store = WorkspaceStore(workspace_file)
    state = _load(store, handoff_id)
    if state is None:
        return {"found": False, "handoff_id": handoff_id}
    if state["status"] not in TERMINAL_STATUSES and _expired(state):
        # 只读路径上的过期折叠同样走 CAS + receipt
        def _expire(next_state: dict[str, Any]) -> None:
            next_state["status"] = "expired"

        new_state, _ = _cas_transition(store, state, mutate=_expire)
        if new_state is not None:
            persist_write_receipt(
                store,
                build_write_receipt(
                    layer="L1_task_shadow",
                    action="task_shadow_handoff_expire",
                    scope="task_shadow",
                    target=handoff_id,
                    target_file=f"session_state/{_handoff_key(handoff_id)}",
                    bytes_written=0,
                ),
            )
        state = new_state or state
    return {"found": True, **state}


def list_handoffs(workspace_file: str | Path, *, status: str = "", limit: int = 20) -> dict[str, Any]:
    store = WorkspaceStore(workspace_file)
    rows = store.memory_backend().list_session_states(HANDOFF_STATE_TYPE, limit=500)
    items = []
    for row in rows:
        state = row.get("payload", {}) if isinstance(row.get("payload"), dict) else {}
        if status and state.get("status") != status:
            continue
        items.append({
            "handoff_id": state.get("handoff_id", ""),
            "shadow_id": state.get("shadow_id", ""),
            "from_session_id": state.get("from_session_id", ""),
            "status": state.get("status", ""),
            "claimed_by_session_id": state.get("claimed_by_session_id", ""),
            "updated_at": state.get("updated_at", ""),
        })
    return {"handoffs": items[-max(1, limit):], "total": len(items)}


__all__ = [
    "HANDOFF_STATE_TYPE",
    "HANDOFF_STATUSES",
    "HandoffConflict",
    "create_handoff",
    "mark_handed_off",
    "claim_handoff",
    "close_handoff",
    "get_handoff",
    "list_handoffs",
]
