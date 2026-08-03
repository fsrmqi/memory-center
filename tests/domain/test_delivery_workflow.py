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
    delivery_skill_replay_set,
    delivery_workflow_status,
    derive_delivery_failure_candidates,
    evaluate_delivery_skill,
    initialize_delivery_workflow,
    publish_delivery_skill,
    recommend_delivery_skills,
    record_delivery_skill_observation,
    record_delivery_validation,
    rollback_delivery_skill,
    start_delivery_skill_canary,
    synthesize_delivery_skill_trajectories,
    transition_delivery_stage,
    update_delivery_contract,
    update_delivery_skill_contract,
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


def test_delivery_skill_contract_is_available_through_admin_and_http(demo_workspace) -> None:
    from memory_center.http.server import _route_request

    task = create_task_space(demo_workspace, title="Skill 契约", intent="声明 Skill 范围")
    task_id = task["task_id"]
    delivery_skill_candidate(demo_workspace, task_id)
    payload = '{"languages":["java"],"preconditions":["已定位"],"stop_conditions":["索引陈旧"],"input_contract":{"required_fields":["intent"]},"output_contract":{"required_fields":["next_action"]},"replay_policy":{"redacted":true}}'

    admin = build_admin_registry(workspace_file=str(demo_workspace), task_id=task_id, source="mcp", payload=payload)
    assert admin.dispatch("delivery_skill_contract_update")["updated"] is True
    http = _route_request(
        "/workspace/delivery/skill/contract",
        {"task_id": [task_id], "payload": [payload]},
        str(demo_workspace),
    )
    assert http["updated"] is True


def test_closed_verified_delivery_canary_requires_objective_evidence_before_publish(demo_workspace) -> None:
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
    assert candidate["candidate"]["contract"]["languages"] == ["java"]
    assert update_delivery_skill_contract(demo_workspace, task_id, contract={})["reason"] == "skill_contract_invalid"
    contract = update_delivery_skill_contract(demo_workspace, task_id, contract={
        "languages": ["java"],
        "preconditions": ["已完成影响分析"],
        "stop_conditions": ["索引陈旧时停止"],
        "input_contract": {"required_fields": ["intent", "task_id"]},
        "output_contract": {"required_fields": ["next_action", "validation_evidence"]},
        "replay_policy": {"redacted": True},
    })
    assert contract["updated"] is True
    assert publish_delivery_skill(demo_workspace, task_id)["reason"] == "canary_required"
    canary = start_delivery_skill_canary(demo_workspace, task_id, actor="test")
    assert canary["started"] is True
    skill_id = canary["skill"]["skill_id"]
    assert record_delivery_skill_observation(demo_workspace, skill_id, outcome="passed")["reason"] == "evidence_required"
    for index in range(3):
        result = record_delivery_skill_observation(demo_workspace, skill_id, outcome="passed", evidence_refs=[f"validation:{index}"], latency_ms=100, token_count=20)
        assert result["recorded"] is True
    assert evaluate_delivery_skill(demo_workspace, skill_id=skill_id)["metrics"]["verified_passed"] == 3
    replay = delivery_skill_replay_set(demo_workspace, skill_id=skill_id)
    assert replay["count"] == 3
    assert "发布接口" not in str(replay)
    revised = update_delivery_skill_contract(demo_workspace, task_id, contract={
        "languages": ["java"],
        "preconditions": ["已完成影响分析"],
        "stop_conditions": ["索引陈旧或验收变化时停止"],
        "input_contract": {"required_fields": ["intent", "task_id"]},
        "output_contract": {"required_fields": ["next_action", "validation_evidence"]},
        "replay_policy": {"redacted": True},
    })
    assert revised["updated"] is True
    assert evaluate_delivery_skill(demo_workspace, skill_id=skill_id)["metrics"]["verified_passed"] == 0
    assert delivery_skill_replay_set(demo_workspace, skill_id=skill_id)["count"] == 0
    for index in range(3, 6):
        assert record_delivery_skill_observation(demo_workspace, skill_id, outcome="passed", evidence_refs=[f"validation:{index}"])["recorded"] is True
    published = publish_delivery_skill(demo_workspace, task_id)
    assert published["published"] is True
    assert update_delivery_skill_contract(demo_workspace, task_id, contract={
        "languages": ["python"],
        "preconditions": ["已定位"],
        "stop_conditions": ["停止"],
        "input_contract": {"required_fields": ["intent"]},
        "output_contract": {"required_fields": ["next_action"]},
        "replay_policy": {"redacted": True},
    })["reason"] == "published_skill_contract_immutable"
    assert recommend_delivery_skills(demo_workspace, "发布接口")["skills"][0]["skill_id"] == skill_id
    assert not recommend_delivery_skills(demo_workspace, "发布接口", language="python")["skills"]
    assert rollback_delivery_skill(demo_workspace, skill_id, reason="发现回归")["rolled_back"] is True
    assert not recommend_delivery_skills(demo_workspace, "发布接口")["skills"]


def test_delivery_offline_failure_and_trajectory_synthesis_are_bounded(demo_workspace) -> None:
    from memory_center.core.storage.workspace import WorkspaceStore
    from memory_center.core.tasks.artifacts import create_task_space

    store = WorkspaceStore(demo_workspace)
    for task_id in ("task-a", "task-b"):
        task_dir = store.artifacts_dir / "tasks" / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        (task_dir / "verification-receipts.jsonl").write_text(
            '{"status":"failed","profile_id":"unit-test","acceptance_ids":["AC-1"],"evidence_refs":["e:1"],"summary":"private output"}\n',
            encoding="utf-8",
        )
    failures = derive_delivery_failure_candidates(demo_workspace)
    assert failures["candidates"][0]["support"] == 2
    assert "private output" not in str(failures)

    for suffix in ("alpha", "beta", "gamma"):
        task = create_task_space(demo_workspace, title=f"shared-test-{suffix}", intent="共享测试")
        task_id = task["task_id"]
        initialize_delivery_workflow(demo_workspace, task_id)
        update_delivery_contract(demo_workspace, task_id, kind="requirements", items=[{"id": "REQ-1", "title": "共享测试", "scope": "接口", "acceptance_ids": ["AC-1"]}])
        update_delivery_contract(demo_workspace, task_id, kind="acceptance", items=[{"id": "AC-1", "title": "测试", "required": True}])
        update_delivery_contract(demo_workspace, task_id, kind="subtasks", items=[{"id": "SUB-1", "title": "实现", "code_targets": ["SharedController#run"]}])
        update_delivery_subtask_status(demo_workspace, task_id, "SUB-1", "implemented")
        record_delivery_validation(demo_workspace, task_id, status="passed", acceptance_ids=["AC-1"], evidence_kind="manual_verified")
        transition_delivery_stage(demo_workspace, task_id, "close")
        delivery_skill_candidate(demo_workspace, task_id)
    synthesis = synthesize_delivery_skill_trajectories(demo_workspace)
    assert synthesis["syntheses"]


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


def test_delivery_scope_contract_is_visible_and_can_be_enforced(demo_workspace) -> None:
    from memory_center.core.tasks.delivery import delivery_matrix, update_delivery_policy

    task_id = create_task_space(demo_workspace, title="范围受控交付", intent="实现受控接口")["task_id"]
    initialize_delivery_workflow(demo_workspace, task_id)
    update_delivery_contract(demo_workspace, task_id, kind="requirements", items=[{
        "id": "REQ-1", "title": "实现接口", "scope": "发布接口", "acceptance_ids": ["AC-1"],
    }])
    update_delivery_contract(demo_workspace, task_id, kind="acceptance", items=[{"id": "AC-1", "title": "回归测试"}])
    transition_delivery_stage(demo_workspace, task_id, "breakdown")
    transition_delivery_stage(demo_workspace, task_id, "locate")
    update_delivery_contract(demo_workspace, task_id, kind="subtasks", items=[{
        "id": "SUB-1",
        "title": "实现发布接口",
        "requirement_ids": ["REQ-1"],
        "code_targets": ["ArticleController#publish"],
        "read_targets": ["ArticleController", "ArticleService"],
        "write_targets": ["ArticleController#publish"],
        "stop_conditions": ["发现跨服务契约变更时停止并重新分析"],
    }])
    matrix = delivery_matrix(demo_workspace, task_id)
    subtask = matrix["matrix"]["rows"][0]["subtasks"][0]
    assert subtask["read_targets"] == ["ArticleController", "ArticleService"]
    assert subtask["write_targets"] == ["ArticleController#publish"]
    assert matrix["matrix"]["coverage"]["scoped_subtasks"] == 1

    update_delivery_policy(demo_workspace, {"enforce_scope_contract": True})
    assert transition_delivery_stage(demo_workspace, task_id, "implement")["transitioned"] is True

    unscoped_task = create_task_space(demo_workspace, title="缺少范围", intent="实现接口")["task_id"]
    initialize_delivery_workflow(demo_workspace, unscoped_task)
    update_delivery_contract(demo_workspace, unscoped_task, kind="requirements", items=[{"id": "REQ-1", "title": "实现接口", "scope": "接口"}])
    update_delivery_contract(demo_workspace, unscoped_task, kind="acceptance", items=[{"id": "AC-1", "title": "回归测试"}])
    transition_delivery_stage(demo_workspace, unscoped_task, "breakdown")
    transition_delivery_stage(demo_workspace, unscoped_task, "locate")
    update_delivery_contract(demo_workspace, unscoped_task, kind="subtasks", items=[{"id": "SUB-1", "title": "实现", "code_targets": ["ArticleController#publish"]}])
    blocked = transition_delivery_stage(demo_workspace, unscoped_task, "implement")
    assert blocked["transitioned"] is False
    assert blocked["gate"]["code"] == "scoped_subtasks_required"


def test_compact_task_artifacts_keeps_bounded_live_content(demo_workspace) -> None:
    task = create_task_space(demo_workspace, title="大工件", intent="压缩")
    task_id = task["task_id"]
    result = update_task_artifact(demo_workspace, task_id, "context", "x" * 60_000)
    assert result["updated"] is True
    compacted = compact_task_artifacts(demo_workspace, task_id, threshold_bytes=1_000, keep_bytes=512)
    assert compacted["compacted"]
    item = compacted["compacted"][0]
    assert item["before_bytes"] > item["after_bytes"]
