from __future__ import annotations

from memory_center.application.admin import build_admin_registry
from memory_center.core.tasks.artifacts import create_task_space, list_task_spaces
from memory_center.core.tasks.delivery import (
    delivery_workflow_status,
    initialize_delivery_workflow,
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
    receipt = record_delivery_validation(demo_workspace, task_id, status="passed", summary="1 passed", exit_code=0, acceptance_ids=["AC-1"])
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
