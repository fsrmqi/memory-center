from pathlib import Path

from memory_center.core.artifacts import (
    create_task_space,
    record_task_decision,
    task_evidence_gc,
    update_task_artifact,
)
from memory_center.core.config import load_workspace_config
from memory_center.core.freshness.invalidation import build_invalidation_plan
from memory_center.core.freshness.watcher import trigger_incremental_reindex
from memory_center.core.index_control import index_control_status, rollback_generation
from memory_center.core.indexer import reindex_workspace
from memory_center.core.query_planner import QueryPlanner
from memory_center.core.store import WorkspaceStore


def _workspace(tmp_path: Path) -> Path:
    from tests.fixtures import copy_demo_workspace
    return copy_demo_workspace(tmp_path)


def test_query_plan_is_bounded_by_tier(tmp_path: Path) -> None:
    plan = QueryPlanner(_workspace(tmp_path)).plan(tier="fast", limit=100, depth=9, enable_vector=True)
    assert plan.limit == 8
    assert plan.depth == 1
    assert plan.enable_vector is False


def test_invalidation_classifies_contract_paths(tmp_path: Path) -> None:
    plan = build_invalidation_plan(_workspace(tmp_path), ["demo/src/main/java/example/OrderDto.java"])
    assert plan["categories"] == ["dto_contract"]
    assert plan["rules"][0]["rule"] == "propagate_to_feign_mq_serialization"


def test_task_decision_and_evidence_gc_are_safe_by_default(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    task = create_task_space(workspace, title="架构决策")
    artifact = update_task_artifact(workspace, task["task_id"], "context", "证据" * (40 * 1024))
    decision = record_task_decision(workspace, task["task_id"], "索引", "使用 generation", "保证一致性", evidence_refs=[artifact["evidence"]["ref"]])
    gc = task_evidence_gc(workspace, task["task_id"])

    assert decision["recorded"] is True
    assert gc["apply"] is False
    assert gc["candidates"] == []


def test_watcher_schedules_coalesced_partial_reindex_and_generation_can_rollback(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    store = WorkspaceStore(workspace)
    reindex_workspace(load_workspace_config(workspace), store, parallel=False)
    first = index_control_status(store)["active_generation"]
    reindex_workspace(load_workspace_config(workspace), store, parallel=False)
    second = index_control_status(store)["active_generation"]

    rollback = rollback_generation(store)

    assert first != second
    assert rollback["rolled_back"] is True
    assert index_control_status(store)["active_generation"] == first
    queued = trigger_incremental_reindex(workspace, ["api/src/main/java/example/OrderDto.java"])
    assert queued["reindex_job"]["kind"] == "reindex"
