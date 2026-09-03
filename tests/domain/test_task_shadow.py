"""Task Shadow（Session-first 会话影子）领域测试。

覆盖提案 SESSION_FIRST_TASK_CONTINUITY_PROPOSAL.md 的验收要求：
幂等水位、多源确定性 merge、CAS 绑定、未绑定不污染 L2、
volatile 拒收、Observation allowlist fail-closed、Handoff claim-once。
"""
from __future__ import annotations

import json

import pytest

from memory_center.core.tasks.shadow import (
    ShadowSnapshotRejected,
    bind_shadow_to_task,
    build_merged_shadow,
    discard_shadow,
    ensure_shadow_for_session,
    merge_contributions,
    promote_shadow_to_task,
    record_shadow_snapshot,
    shadow_retention_cleanup,
    suggest_shadow_binding,
    validate_shadow_snapshot,
)
from memory_center.core.tasks.shadow_observations import (
    ObservationRejected,
    list_observations,
    record_observation,
    set_shadow_authority,
    validate_observation,
)
from memory_center.core.tasks.shadow_handoff import (
    HandoffConflict,
    claim_handoff,
    close_handoff,
    create_handoff,
    mark_handed_off,
)
from memory_center.core.tasks.artifacts import create_task_space, get_task_artifact
from memory_center.core.storage.workspace import WorkspaceStore


def _snapshot(**overrides):
    base = {
        "shadow_id": "shadow:dsh:dsh-1",
        "source_provider_id": "dsh-task-shadow@1",
        "source_session_id": "dsh-1",
        "observed_as_of_seq": 5,
        "durable_as_of_seq": 5,
        "durable_event_count": 10,
        "delivery_mode": "durable",
        "state_version": 1,
        "intent_summary": "fix login bug",
        "candidate_files": ["A.java", "B.java"],
        "next_actions": ["run tests"],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------- schema 校验

def test_snapshot_validation_rejects_volatile():
    with pytest.raises(ShadowSnapshotRejected) as exc:
        validate_shadow_snapshot(_snapshot(delivery_mode="volatile"))
    assert exc.value.code == "volatile_rejected"


def test_snapshot_validation_rejects_observed_ahead_of_durable():
    with pytest.raises(ShadowSnapshotRejected) as exc:
        validate_shadow_snapshot(_snapshot(observed_as_of_seq=9))
    assert exc.value.code == "watermark_not_durable"


def test_snapshot_validation_rejects_unknown_fields():
    snapshot = _snapshot()
    snapshot["prompt"] = "full user prompt text"
    with pytest.raises(ShadowSnapshotRejected) as exc:
        validate_shadow_snapshot(snapshot)
    assert exc.value.code == "unknown_field"


def test_snapshot_validation_rejects_bad_identity():
    with pytest.raises(ShadowSnapshotRejected) as exc:
        validate_shadow_snapshot(_snapshot(source_session_id="../escape"))
    assert exc.value.code == "invalid_identity"


# ---------------------------------------------------------------- 幂等与水位

def test_record_snapshot_idempotent_noop_on_same_seq(demo_workspace):
    wf = str(demo_workspace)
    first = record_shadow_snapshot(wf, _snapshot())
    assert first["accepted"] is True
    second = record_shadow_snapshot(wf, _snapshot())
    assert second["duplicate"] is True
    assert second["reason"] == "idempotent_noop"


def test_record_snapshot_rejects_stale_watermark(demo_workspace):
    wf = str(demo_workspace)
    record_shadow_snapshot(wf, _snapshot())
    stale = record_shadow_snapshot(wf, _snapshot(durable_as_of_seq=3, observed_as_of_seq=3))
    assert stale["reason"] == "stale_watermark"
    shadow = build_merged_shadow(wf, "shadow:dsh:dsh-1")
    # 水位仍是 5，旧快照未生效
    assert shadow["contributions"][0]["durable_as_of_seq"] == 5


def test_record_snapshot_flags_state_version_regression(demo_workspace):
    wf = str(demo_workspace)
    record_shadow_snapshot(wf, _snapshot(state_version=2))
    result = record_shadow_snapshot(wf, _snapshot(durable_as_of_seq=6, observed_as_of_seq=6, state_version=1))
    assert result["accepted"] is False
    assert result["reason"] == "state_version_regression"


def test_state_version_ahead_marks_shadow_stale(demo_workspace):
    wf = str(demo_workspace)
    result = record_shadow_snapshot(wf, _snapshot(state_version=99))
    assert result["accepted"] is True
    assert result["shadow_stale"] is True


# ------------------------------------------------------- 多源 contribution merge

def test_merge_is_deterministic_across_insertion_order():
    contribs_a = {
        "p1::s1": {"durable_as_of_seq": 3, "candidate_files": ["B.java", "A.java"], "evidence_refs": ["r1"], "unresolved_items": ["u1"], "next_actions": ["a1"], "candidate_tasks": [], "intent_summary": "from s1"},
        "p2::s2": {"durable_as_of_seq": 7, "candidate_files": ["A.java", "C.java"], "evidence_refs": [], "unresolved_items": [], "next_actions": ["a2"], "candidate_tasks": [], "intent_summary": "from s2"},
    }
    contribs_b = dict(reversed(list(contribs_a.items())))
    assert merge_contributions(contribs_a) == merge_contributions(contribs_b)


def test_merge_keeps_union_across_sources(demo_workspace):
    wf = str(demo_workspace)
    record_shadow_snapshot(wf, _snapshot())
    record_shadow_snapshot(
        wf,
        _snapshot(source_session_id="dsh-2", durable_as_of_seq=7, observed_as_of_seq=7, candidate_files=["C.java"]),
    )
    shadow = build_merged_shadow(wf, "shadow:dsh:dsh-1")
    assert shadow["merged"]["candidate_files"] == ["A.java", "B.java", "C.java"]
    assert sorted(shadow["session_ids"]) == ["dsh-1", "dsh-2"]
    assert shadow["merged"]["intent_summary"] == "fix login bug"


# ------------------------------------------------------------ 绑定与 L2 隔离

def test_unbound_shadow_cannot_promote(demo_workspace):
    wf = str(demo_workspace)
    record_shadow_snapshot(wf, _snapshot(shadow_id="shadow:dsh:dsh-free", source_session_id="dsh-free"))
    result = promote_shadow_to_task(wf, "shadow:dsh:dsh-free")
    assert result["promoted"] is False
    assert result["reason"] == "shadow_not_bound"
    assert result["required_action"] == "bind_shadow_to_task_first"


def test_bind_requires_existing_task(demo_workspace):
    wf = str(demo_workspace)
    record_shadow_snapshot(wf, _snapshot())
    with pytest.raises(ValueError, match="unknown task space"):
        bind_shadow_to_task(wf, "shadow:dsh:dsh-1", "no-such-task")


def test_bind_is_cas_guarded(demo_workspace):
    wf = str(demo_workspace)
    record_shadow_snapshot(wf, _snapshot())
    task = create_task_space(wf, title="login fix")["task_id"]
    bound = bind_shadow_to_task(wf, "shadow:dsh:dsh-1", task)
    assert bound["bound"] is True
    conflict = bind_shadow_to_task(wf, "shadow:dsh:dsh-1", task, expected_revision=0)
    assert conflict["reason"] == "stale_revision"
    assert conflict["current_revision"] == bound["revision"]


def test_promote_merges_summary_into_task_context(demo_workspace):
    wf = str(demo_workspace)
    record_shadow_snapshot(wf, _snapshot(candidate_files=["A.java", {"path": "nested/C.java"}]))
    task = create_task_space(wf, title="login fix")["task_id"]
    bind_shadow_to_task(wf, "shadow:dsh:dsh-1", task)
    promoted = promote_shadow_to_task(wf, "shadow:dsh:dsh-1")
    assert promoted["promoted"] is True
    assert promoted["candidate_file_count"] == 2
    context = str(get_task_artifact(wf, task, "context").get("content", ""))
    assert "## Task Shadow" in context
    assert "A.java" in context and "nested/C.java" in context


def test_discard_keeps_l2_and_returns_merged_snapshot(demo_workspace):
    wf = str(demo_workspace)
    record_shadow_snapshot(wf, _snapshot())
    task = create_task_space(wf, title="login fix")["task_id"]
    bind_shadow_to_task(wf, "shadow:dsh:dsh-1", task)
    promoted = promote_shadow_to_task(wf, "shadow:dsh:dsh-1")
    assert promoted["promoted"] is True
    discarded = discard_shadow(wf, "shadow:dsh:dsh-1")
    assert discarded["discarded"] is True
    assert build_merged_shadow(wf, "shadow:dsh:dsh-1") is None
    # L2 工件不受 Shadow 生命周期影响（验收 8）
    assert "A.java" in str(get_task_artifact(wf, task, "context").get("content", ""))


def test_retention_skips_bound_shadows(demo_workspace):
    wf = str(demo_workspace)
    record_shadow_snapshot(wf, _snapshot())
    task = create_task_space(wf, title="login fix")["task_id"]
    bind_shadow_to_task(wf, "shadow:dsh:dsh-1", task)
    cleanup = shadow_retention_cleanup(wf, older_than_days=0)
    assert "shadow:dsh:dsh-1" not in cleanup["candidates"]


def test_suggest_binding_blocks_after_bound(demo_workspace):
    wf = str(demo_workspace)
    ensure_shadow_for_session(wf, "sess-suggest", intent="explore")
    shadow_id = "shadow:memory-center:sess-suggest"
    task = create_task_space(wf, title="target task")["task_id"]
    bind_shadow_to_task(wf, shadow_id, task)
    result = suggest_shadow_binding(wf, shadow_id, candidate_tasks=[{"task_id": "other", "title": "Other", "score": 1}])
    assert result["suggested"] is False
    assert result["reason"] == "already_bound"


# ------------------------------------------------------------- mc_start 集成

def test_start_task_creates_shadow_without_writing_l2_when_unbound(demo_workspace):
    from memory_center.application.task_start import start_task

    result = start_task(
        str(demo_workspace),
        "explore indexing",
        limit=6,
        auto_sync_mode="balanced",
        sync_task_space=False,
        budget="small",
        deadline_ms=3000,
        request_tier="fast",
    )
    shadow = result["task_shadow"]
    assert shadow["shadow_id"].startswith("shadow:memory-center:")
    assert shadow["binding_status"] == "unbound"


# ---------------------------------------------------------- Observation Inbox

def _observation(**overrides):
    base = {
        "source_kind": "dsh",
        "source_session_id": "sess-obs",
        "event_seq": 3,
        "kind": "candidate_file",
        "payload": {"tool_name": "read_file", "candidate_files": ["src/Login.java"]},
    }
    base.update(overrides)
    return base


def test_observation_records_folds_and_dedupes(demo_workspace):
    wf = str(demo_workspace)
    first = record_observation(wf, _observation())
    assert first["recorded"] is True
    assert first["folded_into_shadow"] is True
    duplicate = record_observation(wf, _observation())
    assert duplicate["duplicate"] is True
    stale = record_observation(wf, _observation(event_seq=1))
    assert stale["reason"] == "stale_or_duplicate_event_seq"
    shadow = build_merged_shadow(wf, "shadow:dsh-observation@1:sess-obs")
    assert shadow["merged"]["candidate_files"] == ["src/Login.java"]
    assert shadow["shadow_authority"] == "observation"


def test_observation_allowlist_rejects_prompt_payload(demo_workspace):
    with pytest.raises(ObservationRejected) as exc:
        validate_observation(_observation(kind="tool_fact", payload={"prompt": "full prompt"}))
    assert exc.value.code == "payload_field_rejected"


def test_observation_rejects_absolute_paths(demo_workspace):
    with pytest.raises(ObservationRejected) as exc:
        validate_observation(_observation(payload={"candidate_files": ["/Users/secret/x.java"]}))
    assert exc.value.code == "absolute_path_rejected"


def test_observation_authority_switch_disposes_contributions(demo_workspace):
    wf = str(demo_workspace)
    record_observation(wf, _observation())
    shadow_id = "shadow:dsh-observation@1:sess-obs"
    switched = set_shadow_authority(wf, shadow_id, "snapshot")
    assert switched["shadow_authority"] == "snapshot"
    later = record_observation(wf, _observation(event_seq=9, kind="validation", payload={"validation_status": "passed"}))
    assert later["recorded"] is True  # L0 审计仍然落盘
    assert later["folded_into_shadow"] is False
    assert later["shadow_fold"]["reason"] == "shadow_authority_is_snapshot"
    shadow = build_merged_shadow(wf, shadow_id)
    assert all(item["disposed"] for item in shadow["contributions"] if item["source_provider_id"].endswith("-observation@1"))
    observations = list_observations(wf, source_session_id="sess-obs")
    assert observations["summary"]["total"] == 2


# --------------------------------------------------------------- Handoff Claim

def test_handoff_claim_once_cas(demo_workspace):
    wf = str(demo_workspace)
    created = create_handoff(wf, from_session_id="sess-a", shadow_id="")
    hid = created["handoff_id"]
    early = claim_handoff(wf, hid, claimed_by_session_id="sess-b", expected_revision=created["revision"])
    assert early["reason"] == "handoff_not_handed_off_yet"
    handed = mark_handed_off(wf, hid, expected_revision=created["revision"])
    assert handed["handed_off"] is True
    stale = claim_handoff(wf, hid, claimed_by_session_id="sess-b", expected_revision=created["revision"])
    assert stale["reason"] == "stale_revision"
    claimed = claim_handoff(wf, hid, claimed_by_session_id="sess-b", expected_revision=handed["revision"])
    assert claimed["claimed"] is True
    second = claim_handoff(wf, hid, claimed_by_session_id="sess-c", expected_revision=claimed["revision"])
    assert second["reason"] == "already_claimed"
    closed = close_handoff(wf, hid, expected_revision=claimed["revision"])
    assert closed["closed"] is True


def test_handoff_requires_known_shadow(demo_workspace):
    with pytest.raises(ValueError, match="unknown task shadow"):
        create_handoff(str(demo_workspace), from_session_id="sess-a", shadow_id="shadow:missing")


def test_handoff_does_not_create_task_space(demo_workspace):
    wf = str(demo_workspace)
    record_shadow_snapshot(wf, _snapshot())
    created = create_handoff(wf, from_session_id="sess-a", shadow_id="shadow:dsh:dsh-1")
    assert created["status"] == "draft"
    # handoff 不触发任何 L2 创建
    from memory_center.core.tasks.artifacts import list_task_spaces

    spaces = list_task_spaces(wf)
    assert all(item["task_id"] != created["handoff_id"] for item in spaces["active_tasks"])


# ----------------------------------------------------------------- mc_close 建议

def test_close_binding_recommendation_keeps_shadow_by_default(demo_workspace):
    from memory_center.application.task_start import start_task
    from memory_center.core.orchestrator import workspace_end_session
    from memory_center.core.tasks.shadow import build_merged_shadow

    wf = str(demo_workspace)
    result = start_task(
        wf,
        "explore retention",
        limit=6,
        auto_sync_mode="balanced",
        sync_task_space=False,
        budget="small",
        deadline_ms=3000,
        request_tier="fast",
    )
    session_id = result["session"]["session_id"]
    shadow_id = result["task_shadow"]["shadow_id"]
    workspace_end_session(wf, session_id, outcome="completed")
    shadow = build_merged_shadow(wf, shadow_id)
    # close 后 Shadow 保留为临时工作影子（默认选项），未绑定、未写 L2
    assert shadow is not None
    assert shadow["binding_status"] == "unbound"
    assert shadow["bound_task_id"] == ""
