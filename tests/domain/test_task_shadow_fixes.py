"""评审修复回归：L2 门禁、source→shadow 映射、原子 CAS、handoff nonce、receipt 审计。"""
from __future__ import annotations

import json

from memory_center.application.task_shadow_flow import (
    case_sync_with_shadow,
    resolve_close_task_id,
    sniff_sync_with_shadow_fallback,
)
from memory_center.core.tasks.shadow import (
    bind_shadow_to_task,
    build_merged_shadow,
    ensure_shadow_for_session,
    record_shadow_snapshot,
    suggest_shadow_binding,
)
from memory_center.core.tasks.shadow_observations import (
    list_observations,
    record_observation,
    set_shadow_authority,
)
from memory_center.core.tasks.shadow_handoff import (
    claim_handoff,
    create_handoff,
    mark_handed_off,
)
from memory_center.core.tasks.artifacts import create_task_space, list_task_spaces
from memory_center.core.storage.workspace import WorkspaceStore
from memory_center.core.tasks.receipts import query_write_receipts


def _snapshot(**overrides):
    base = {
        "shadow_id": "shadow:dsh:fix-1",
        "source_provider_id": "dsh-task-shadow@1",
        "source_session_id": "fix-1",
        "observed_as_of_seq": 5,
        "durable_as_of_seq": 5,
        "durable_event_count": 10,
        "delivery_mode": "durable",
        "state_version": 1,
        "intent_summary": "fix",
        "candidate_files": ["F.java"],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------- P0 门禁

def test_case_sync_blocked_for_unbound_shadow(demo_workspace):
    wf = str(demo_workspace)
    ensure_shadow = record_observation(wf, {
        "source_kind": "dsh", "source_session_id": "p0-sess", "event_seq": 1,
        "kind": "session_boundary", "payload": {"tool_name": "start"},
    })
    # session 无绑定 Shadow（observation 折叠而来，unbound）
    result = case_sync_with_shadow(wf, "p0-sess")
    assert result["write_target"] == "task_shadow"
    assert result["synced"] is False
    assert result["result"]["synced"] is False
    # L2 未被创建
    spaces = list_task_spaces(wf)
    assert all(item["task_id"] != "p0-sess" for item in spaces["active_tasks"])


def test_case_sync_allows_bound_shadow(demo_workspace):
    wf = str(demo_workspace)
    from memory_center.core.tasks.shadow import ensure_shadow_for_session

    from memory_center.core.orchestrator import workspace_start_session, workspace_end_session

    # 走真实路径：mc_start 创建 session Shadow，然后显式绑定 task
    ensured = ensure_shadow_for_session(wf, "p0-b", intent="work on bound task")
    task = create_task_space(wf, title="bound target")["task_id"]
    bind_shadow_to_task(wf, ensured["shadow_id"], task)
    workspace_start_session(wf, "work on bound task", session_id="p0-b")
    workspace_end_session(wf, "p0-b", outcome="done")
    result = case_sync_with_shadow(wf, "p0-b")
    assert result["task_id_source"] == "shadow_binding"
    # bound Shadow 允许走到 L2（即使 case sync 内部因 draft 为空而 synced=False，
    # 也不得返回 shadow-only 模式）
    assert result["write_target"] in ("task_space", "none")


def test_case_sync_explicit_task_id_passes(demo_workspace):
    wf = str(demo_workspace)
    from memory_center.core.orchestrator import workspace_start_session, workspace_end_session

    workspace_start_session(wf, "explicit work", session_id="p0-exp")
    workspace_end_session(wf, "p0-exp", outcome="done")
    task = create_task_space(wf, title="explicit target")["task_id"]
    result = case_sync_with_shadow(wf, "p0-exp", task_id=task)
    assert result["task_id_source"] == "explicit"
    assert result["write_target"] in ("task_space", "none")


def test_close_uses_only_recorded_binding_decision_or_shadow(demo_workspace):
    from memory_center.core.orchestrator import workspace_start_session

    wf = str(demo_workspace)
    task = create_task_space(wf, title="direct target")["task_id"]
    workspace_start_session(wf, "legacy task id", session_id="legacy", metadata={"task_id": task})
    assert resolve_close_task_id(wf, "legacy", "") == ("", "")

    workspace_start_session(
        wf,
        "directly anchored",
        session_id="anchored",
        metadata={"task_binding": {"mode": "auto_direct_anchor", "task_id": task}},
    )
    assert resolve_close_task_id(wf, "anchored", "") == (task, "session_binding")


# ------------------------------------------------- P1 source→shadow 映射

def test_observation_folds_into_snapshot_registered_shadow(demo_workspace):
    wf = str(demo_workspace)
    # Snapshot 先注册 (dsh, fix-obs) → shadow:dsh:fix-obs
    record_shadow_snapshot(wf, _snapshot(shadow_id="shadow:dsh:fix-obs", source_session_id="fix-obs"))
    # Observation 同 source session：必须折叠进同一个 Shadow
    folded = record_observation(wf, {
        "source_kind": "dsh", "source_session_id": "fix-obs", "event_seq": 9,
        "kind": "candidate_file", "payload": {"candidate_files": ["Obs.java"]},
    })
    # snapshot authority 默认 → Observation 不得覆盖 Shadow 字段
    assert folded["folded_into_shadow"] is False
    assert folded["shadow_fold"]["reason"] == "shadow_authority_is_snapshot"
    assert folded["shadow_fold"]["shadow_id"] == "shadow:dsh:fix-obs"
    shadow = build_merged_shadow(wf, "shadow:dsh:fix-obs")
    assert "Obs.java" not in shadow["merged"]["candidate_files"]


def test_authority_switch_blocks_mapped_observation(demo_workspace):
    wf = str(demo_workspace)
    # MC session shadow（observation authority）注册映射
    store = WorkspaceStore(wf)
    from memory_center.core.tasks.shadow import ensure_shadow_for_session, register_shadow_source

    ensure_shadow_for_session(wf, "fix-auth")
    register_shadow_source(store, "dsh", "fix-auth", "shadow:memory-center:fix-auth")
    first = record_observation(wf, {
        "source_kind": "dsh", "source_session_id": "fix-auth", "event_seq": 2,
        "kind": "tool_fact", "payload": {"tool_name": "edit"},
    })
    assert first["folded_into_shadow"] is True
    assert first["shadow_fold"]["shadow_id"] == "shadow:memory-center:fix-auth"
    # 切换 authority=snapshot 后，同 source 的 Observation 只留 L0 审计
    switched = set_shadow_authority(wf, "shadow:memory-center:fix-auth", "snapshot")
    assert switched["write_receipt"]["receipt_id"]
    second = record_observation(wf, {
        "source_kind": "dsh", "source_session_id": "fix-auth", "event_seq": 3,
        "kind": "tool_fact", "payload": {"tool_name": "edit"},
    })
    assert second["recorded"] is True
    assert second["folded_into_shadow"] is False


# ------------------------------------------------------------- P1 原子 CAS

def test_cas_rejects_concurrent_second_writer(demo_workspace):
    wf = str(demo_workspace)
    record_shadow_snapshot(wf, _snapshot(shadow_id="shadow:dsh:cas-1", source_session_id="cas-1"))
    task_a = create_task_space(wf, title="task a")["task_id"]
    # 两个"进程"读到同一 revision
    from memory_center.core.tasks.shadow import load_shadow_state

    store = WorkspaceStore(wf)
    rev = int(load_shadow_state(store, "shadow:dsh:cas-1")["revision"])
    first = bind_shadow_to_task(wf, "shadow:dsh:cas-1", task_a, expected_revision=rev)
    assert first["bound"] is True
    # 第二个写者仍持旧 revision：必须失败且不覆盖
    task_b = create_task_space(wf, title="task b")["task_id"]
    second = bind_shadow_to_task(wf, "shadow:dsh:cas-1", task_b, expected_revision=rev)
    assert second["bound"] is False
    assert second["reason"] == "stale_revision"
    shadow = build_merged_shadow(wf, "shadow:dsh:cas-1")
    assert shadow["bound_task_id"] == task_a


def test_handoff_claim_is_atomic_under_same_revision(demo_workspace):
    wf = str(demo_workspace)
    created = create_handoff(wf, from_session_id="cas-h")
    handed = mark_handed_off(wf, created["handoff_id"], expected_revision=created["revision"])
    # 两个 claimant 都持 handed_off 时的 revision
    rev = handed["revision"]
    first = claim_handoff(wf, created["handoff_id"], claimed_by_session_id="w1", expected_revision=rev)
    assert first["claimed"] is True
    second = claim_handoff(wf, created["handoff_id"], claimed_by_session_id="w2", expected_revision=rev)
    # 已被 w1 认领：无论 w2 持哪个 revision 都不能再 claim（claim-once 优先），
    # 且 claimed_by 仍是 w1——CAS 保证了不会覆盖先到接手者。
    assert second["claimed"] is False
    assert second["reason"] == "already_claimed"
    from memory_center.core.tasks.shadow_handoff import get_handoff

    assert get_handoff(wf, created["handoff_id"])["claimed_by_session_id"] == "w1"


# --------------------------------------------------------------- P1 nonce

def test_same_second_handoff_creates_do_not_collide(demo_workspace):
    wf = str(demo_workspace)
    one = create_handoff(wf, from_session_id="nonce-sess")
    two = create_handoff(wf, from_session_id="nonce-sess")
    assert one["handoff_id"] != two["handoff_id"]
    from memory_center.core.tasks.shadow_handoff import get_handoff

    assert get_handoff(wf, one["handoff_id"])["found"] is True
    assert get_handoff(wf, two["handoff_id"])["found"] is True


# ------------------------------------------------------------- P1 receipt

def test_authority_switch_and_ensure_write_receipts(demo_workspace):
    wf = str(demo_workspace)
    from memory_center.core.tasks.shadow import ensure_shadow_for_session

    ensured = ensure_shadow_for_session(wf, "receipt-sess", intent="audit me")
    assert ensured["write_receipt"]["receipt_id"]
    assert "task_shadow_ensure" in ensured["write_receipt"]["receipt_id"] or "task_shadow_create" in ensured["write_receipt"]["receipt_id"]

    switched = set_shadow_authority(wf, ensured["shadow_id"], "snapshot")
    assert switched["write_receipt"]["receipt_id"]
    receipts = query_write_receipts(wf, scope="task_shadow", limit=50)
    actions = {item["action"] for item in receipts["receipts"]}
    assert any("task_shadow_authority" in action for action in actions)
    assert any("task_shadow_ensure" in action or "task_shadow_create" in action for action in actions)


def test_suggest_binding_writes_receipt(demo_workspace):
    wf = str(demo_workspace)
    ensured = ensure_shadow_for_session(wf, "suggest-sess")
    result = suggest_shadow_binding(wf, ensured["shadow_id"], candidate_tasks=[
        {"task_id": "t1", "title": "T1", "score": 3},
    ])
    assert result["suggested"] is True
    assert result["write_receipt"]["receipt_id"]


# ------------------------------------------------- P1 intent 路径门禁

def test_sniff_sync_blocked_for_unbound(demo_workspace):
    wf = str(demo_workspace)
    result = sniff_sync_with_shadow_fallback(wf, "some exploratory intent", session_id="p1-intent")
    assert result["mode"] == "sniff"
    assert result["write_target"] == "task_shadow"
    assert result["synced"] is False
    # 未绑定且无显式 task_id 时不得创建任何 L2 task space
    spaces = list_task_spaces(wf)
    assert all(item["task_id"] != "p1-intent" for item in spaces["active_tasks"])


def test_sniff_sync_allows_explicit_task_id(demo_workspace):
    wf = str(demo_workspace)
    task = create_task_space(wf, title="explicit sniff target")["task_id"]
    result = sniff_sync_with_shadow_fallback(wf, "some intent", task_id=task)
    assert result["task_id_source"] == "explicit"
    assert result["write_target"] in ("task_space", "none")


# ------------------------------------------------- P1 snapshot 映射改绑

def test_stale_snapshot_does_not_rebind_source(demo_workspace):
    wf = str(demo_workspace)
    # 首次成功接受，source 绑定 shadow:a
    first = record_shadow_snapshot(wf, _snapshot(
        shadow_id="shadow:dsh:rb-a", source_session_id="rb-sess", durable_as_of_seq=5, observed_as_of_seq=5,
    ))
    assert first["accepted"] is True
    # 一个 stale 快照携带不同的 shadow_id：必须返回拒绝，且不改写映射
    stale = record_shadow_snapshot(wf, _snapshot(
        shadow_id="shadow:dsh:rb-b", source_session_id="rb-sess",
        durable_as_of_seq=3, observed_as_of_seq=3,
    ))
    assert stale["accepted"] is False
    assert stale["reason"] == "source_already_bound_to_other_shadow"
    assert stale["bound_shadow_id"] == "shadow:dsh:rb-a"


def test_rebind_requires_explicit_rebind_flag(demo_workspace):
    wf = str(demo_workspace)
    record_shadow_snapshot(wf, _snapshot(
        shadow_id="shadow:dsh:rb-x", source_session_id="rb2", durable_as_of_seq=1, observed_as_of_seq=1,
    ))
    # 同一 source 换新 shadow 且更高水位：也拒绝（未显式迁移）
    rejected = record_shadow_snapshot(wf, _snapshot(
        shadow_id="shadow:dsh:rb-y", source_session_id="rb2", durable_as_of_seq=9, observed_as_of_seq=9,
    ))
    assert rejected["accepted"] is False
    assert rejected["reason"] == "source_already_bound_to_other_shadow"


# ------------------------------------------------- 并发写入不得丢失 contribution

def test_concurrent_shadow_snapshots_do_not_lose_contributions(demo_workspace, monkeypatch):
    """两个 source 的快照并发写入同一 Shadow：两边都必须保留。

    此前 record_shadow_snapshot 是 read → merge → write 且无锁：A 读到空表后 B 也
    读到空表，后写者用自己的旧快照整表覆盖，先写者的 contribution 静默丢失（L2 案例
    会缺一个 source 的候选文件/意图）。这里在 save_contributions 内插入延时，把竞态
    窗口固定下来：无锁实现下 B 会在 A 写入之前读到旧表，因此必然丢一条。
    """
    import threading
    import time

    from memory_center.core.storage.workspace import WorkspaceStore
    from memory_center.core.tasks import shadow as shadow_mod
    from memory_center.core.tasks.shadow import load_contributions, load_shadow_state

    wf = str(demo_workspace)
    real_save = shadow_mod.save_contributions

    def slow_save(store, shadow_id, contributions):
        time.sleep(0.2)
        return real_save(store, shadow_id, contributions)

    monkeypatch.setattr(shadow_mod, "save_contributions", slow_save)

    results: dict[str, dict] = {}
    failures: list[BaseException] = []

    def record(source: str) -> None:
        try:
            results[source] = record_shadow_snapshot(
                wf,
                _snapshot(shadow_id="shadow:dsh:conc", source_session_id=source, durable_as_of_seq=5),
            )
        except BaseException as exc:  # noqa: BLE001 - 线程内异常必须带回主线程
            failures.append(exc)

    first = threading.Thread(target=record, args=("conc-a",))
    second = threading.Thread(target=record, args=("conc-b",))
    first.start()
    time.sleep(0.05)  # 让第二个线程落在第一个线程的读-写窗口内
    second.start()
    first.join(timeout=30)
    second.join(timeout=30)

    assert not failures, failures
    assert results["conc-a"]["accepted"] is True
    assert results["conc-b"]["accepted"] is True

    store = WorkspaceStore(wf)
    contributions = load_contributions(store, "shadow:dsh:conc")
    assert sorted(contributions) == [
        "dsh-task-shadow@1::conc-a",
        "dsh-task-shadow@1::conc-b",
    ], sorted(contributions)
    # 两次成功的 RMW 必须各推进一次 revision（无锁实现下第二次写入基于旧 revision）
    assert int(load_shadow_state(store, "shadow:dsh:conc")["revision"]) == 2


def test_concurrent_observation_folds_do_not_lose_contributions(demo_workspace, monkeypatch):
    """两个 source 的 Observation 并发折叠进同一 Shadow：两边都必须保留。"""
    import threading
    import time

    from memory_center.core.storage.workspace import WorkspaceStore
    from memory_center.core.tasks import shadow as shadow_mod
    from memory_center.core.tasks.shadow import load_contributions, register_shadow_source

    wf = str(demo_workspace)
    for source in ("fold-a", "fold-b"):
        register_shadow_source(WorkspaceStore(wf), "dsh", source, "shadow:dsh:fold")

    real_save = shadow_mod.save_contributions

    def slow_save(target_store, shadow_id, contributions):
        time.sleep(0.2)
        return real_save(target_store, shadow_id, contributions)

    monkeypatch.setattr(shadow_mod, "save_contributions", slow_save)

    results: dict[str, dict] = {}
    failures: list[BaseException] = []

    def record(source: str) -> None:
        try:
            results[source] = record_observation(
                wf,
                {
                    "source_kind": "dsh",
                    "source_session_id": source,
                    "event_seq": 1,
                    "kind": "candidate_file",
                    "payload": {"candidate_files": [f"{source}.java"]},
                },
            )
        except BaseException as exc:  # noqa: BLE001 - 线程内异常必须带回主线程
            failures.append(exc)

    first = threading.Thread(target=record, args=("fold-a",))
    second = threading.Thread(target=record, args=("fold-b",))
    first.start()
    time.sleep(0.05)
    second.start()
    first.join(timeout=30)
    second.join(timeout=30)

    assert not failures, failures
    assert results["fold-a"]["folded_into_shadow"] is True
    assert results["fold-b"]["folded_into_shadow"] is True
    contributions = load_contributions(WorkspaceStore(wf), "shadow:dsh:fold")
    assert sorted(contributions) == [
        "dsh-observation@1::fold-a",
        "dsh-observation@1::fold-b",
    ], sorted(contributions)
