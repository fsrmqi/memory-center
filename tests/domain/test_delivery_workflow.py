from __future__ import annotations

from memory_center.application.admin import build_admin_registry
from memory_center.core.tasks.artifacts import (
    compact_task_artifacts,
    create_task_space,
    list_task_spaces,
    update_task_artifact,
)
from memory_center.core.tasks.delivery import (
    delivery_skill_candidate,
    delivery_workflow_status,
    initialize_delivery_workflow,
    publish_delivery_skill,
    record_delivery_validation,
    transition_delivery_stage,
    update_delivery_contract,
    update_delivery_subtask_status,
)


def test_delivery_workflow_requires_contracts_and_validation(demo_workspace) -> None:
    task = create_task_space(demo_workspace, title="发布接口", intent="新增发布接口")
    task_id = task["task_id"]

    initialized = initialize_delivery_workflow(demo_workspace, task_id, actor="test")
    assert initialized["stage"] == "intake"
    blocked = transition_delivery_stage(demo_workspace, task_id, "breakdown")
    assert blocked["transitioned"] is False
    assert blocked["gate"]["missing"] == ["requirements"]

    update_delivery_contract(demo_workspace, task_id, kind="requirements", items=[{
        "id": "REQ-1", "title": "发布接口", "scope": "Controller 和 Feign 契约", "evidence_refs": ["evidence:req"], "acceptance_ids": ["AC-1"],
    }])
    update_delivery_contract(demo_workspace, task_id, kind="acceptance", items=[{
        "id": "AC-1", "title": "回归测试通过", "verification_type": "test", "required": True,
    }])
    assert transition_delivery_stage(demo_workspace, task_id, "breakdown")["transitioned"] is True
    assert transition_delivery_stage(demo_workspace, task_id, "locate")["transitioned"] is True

    update_delivery_contract(demo_workspace, task_id, kind="subtasks", items=[{
        "id": "SUB-1", "title": "实现 Controller", "requirement_ids": ["REQ-1"], "code_targets": ["ArticleController#publish"],
    }])
    assert transition_delivery_stage(demo_workspace, task_id, "implement")["transitioned"] is True
    assert transition_delivery_stage(demo_workspace, task_id, "verify")["transitioned"] is False
    update_delivery_subtask_status(demo_workspace, task_id, "SUB-1", "implemented")
    assert transition_delivery_stage(demo_workspace, task_id, "verify")["transitioned"] is True

    blocked_close = transition_delivery_stage(demo_workspace, task_id, "close")
    assert blocked_close["transitioned"] is False
    receipt = record_delivery_validation(demo_workspace, task_id, status="passed", summary="1 passed", exit_code=0, acceptance_ids=["AC-1"], evidence_kind="manual_verified")
    assert receipt["receipt"]["command"] == ""
    closed = transition_delivery_stage(demo_workspace, task_id, "close")
    assert closed["transitioned"] is True
    assert delivery_workflow_status(demo_workspace, task_id)["state"] == "done"
    assert list_task_spaces(demo_workspace)["active_tasks"][0]["status"] == "done"


def test_delivery_admin_contract_actions_use_existing_facade(demo_workspace) -> None:
    task = create_task_space(demo_workspace, title="任务", intent="需求")
    registry = build_admin_registry(workspace_file=str(demo_workspace), task_id=task["task_id"], source="mcp")
    assert registry.dispatch("delivery_init")["initialized"] is True

    payload = '{"kind":"requirements","items":[{"id":"REQ-1","title":"需求","scope":"范围"}]}'
    registry = build_admin_registry(workspace_file=str(demo_workspace), task_id=task["task_id"], source="mcp", payload=payload)
    result = registry.dispatch("delivery_contract_update")
    assert result["updated"] is True
    assert result["items"][0]["id"] == "REQ-1"


def test_closed_verified_delivery_can_publish_reviewed_skill(demo_workspace) -> None:
    task = create_task_space(demo_workspace, title="发布接口", intent="新增发布接口")
    task_id = task["task_id"]
    initialize_delivery_workflow(demo_workspace, task_id)
    update_delivery_contract(demo_workspace, task_id, kind="requirements", items=[{"id": "REQ-1", "title": "发布", "scope": "接口", "acceptance_ids": ["AC-1"]}])
    update_delivery_contract(demo_workspace, task_id, kind="acceptance", items=[{"id": "AC-1", "title": "测试", "required": True}])
    transition_delivery_stage(demo_workspace, task_id, "breakdown")
    transition_delivery_stage(demo_workspace, task_id, "locate")
    update_delivery_contract(demo_workspace, task_id, kind="subtasks", items=[{"id": "SUB-1", "title": "实现", "code_targets": ["ArticleController#publish"]}])
    transition_delivery_stage(demo_workspace, task_id, "implement")
    update_delivery_subtask_status(demo_workspace, task_id, "SUB-1", "implemented")
    transition_delivery_stage(demo_workspace, task_id, "verify")
    record_delivery_validation(demo_workspace, task_id, status="passed", acceptance_ids=["AC-1"], evidence_kind="manual_verified")
    transition_delivery_stage(demo_workspace, task_id, "close")

    candidate = delivery_skill_candidate(demo_workspace, task_id)
    assert candidate["candidate"]["eligible"] is True
    published = publish_delivery_skill(demo_workspace, task_id)
    assert published["published"] is True
    assert (demo_workspace.parent / "artifacts" / "skills" / "delivery-published" / task_id / "SKILL.md").exists()


def test_delivery_matrix_and_policy_control_executor(demo_workspace) -> None:
    from memory_center.core.tasks.delivery import (
        delivery_matrix,
        execute_delivery_validation,
        propose_delivery_breakdown,
        update_delivery_policy,
    )

    task_id = create_task_space(demo_workspace, title="验证", intent="测试")["task_id"]
    initialize_delivery_workflow(demo_workspace, task_id)
    candidate = propose_delivery_breakdown(demo_workspace, task_id, source_refs=["req:1"], summary="发布接口")
    assert candidate["candidate"]["source_refs"] == ["req:1"]
    update_delivery_contract(demo_workspace, task_id, kind="requirements", items=[{"id": "REQ-1", "title": "发布", "scope": "接口", "source_refs": ["req:1"], "acceptance_ids": ["AC-1"]}])
    update_delivery_contract(demo_workspace, task_id, kind="acceptance", items=[{"id": "AC-1", "title": "解释器可用"}])
    matrix = delivery_matrix(demo_workspace, task_id)
    assert matrix["matrix"]["coverage"]["requirements"] == 1
    assert (demo_workspace.parent / "artifacts" / "tasks" / task_id / "TECH_SPEC.md").exists()
    blocked = execute_delivery_validation(demo_workspace, task_id, profile_id="missing")
    assert blocked["reason"] == "profile_not_allowed"
    update_delivery_policy(demo_workspace, {"validation_profiles": [{"id": "python-version", "argv": ["python3", "--version"], "timeout_sec": 10}]})
    executed = execute_delivery_validation(demo_workspace, task_id, profile_id="python-version", acceptance_ids=["AC-1"])
    assert executed["executed"] is True
    assert executed["receipt"]["evidence_kind"] == "executor"


def test_compact_task_artifacts_keeps_bounded_live_content(demo_workspace) -> None:
    task = create_task_space(demo_workspace, title="大工件", intent="压缩")
    task_id = task["task_id"]
    result = update_task_artifact(demo_workspace, task_id, "context", "x" * 60_000)
    assert result["updated"] is True
    compacted = compact_task_artifacts(demo_workspace, task_id, threshold_bytes=1_000, keep_bytes=512)
    assert compacted["compacted"]
    item = compacted["compacted"][0]
    assert item["before_bytes"] > item["after_bytes"]
