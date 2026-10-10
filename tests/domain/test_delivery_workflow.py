from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import memory_center.core.tasks.delivery as delivery_module
from memory_center.application.admin import build_admin_registry

pass  # 4.x 入口已退役
from memory_center.core.tasks.artifacts import (
    compact_task_artifacts,
    create_task_space,
    list_task_spaces,
    update_task_artifact,
)
from memory_center.core.tasks.delivery import (
    DeliveryArtifactCorruptionError,
    DeliverySkillRegistryCorruptionError,
    delivery_skill_candidate,
    delivery_skill_replay_set,
    delivery_skill_status,
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


def _skill_contract(*, stop_condition: str = "索引陈旧时停止", languages: list[str] | None = None, minimum_verified_passed: int = 3) -> dict[str, object]:
    """Build the complete, reviewable contract required for a delivery Skill."""

    return {
        "languages": languages or ["java"],
        "applicability_conditions": ["目标范围与已验证交付一致"],
        "prohibited_conditions": ["需求边界不清时禁止使用"],
        "preconditions": ["已完成影响分析"],
        "acceptance_evidence": {
            "accepted_kinds": ["manual_verified"],
            "required_fields": ["acceptance_ids", "evidence_refs"],
        },
        "stop_conditions": [stop_condition],
        "rollback": {
            "triggers": ["出现失败观测"],
            "action": "执行 delivery-skill-rollback 并回退到常规交付流程",
        },
        "input_contract": {"required_fields": ["intent", "task_id"]},
        "output_contract": {"required_fields": ["next_action", "validation_evidence"]},
        "replay_policy": {"redacted": True, "minimum_verified_passed": minimum_verified_passed},
    }


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
    receipt = record_delivery_validation(demo_workspace, task_id, status="passed", summary="1 passed", exit_code=0, acceptance_ids=["AC-1"], evidence_kind="manual_verified", actor="reviewer")
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

    acceptance_payload = json.dumps({
        "kind": "acceptance",
        "items": [{
            "id": "AC-1",
            "title": "兼容性验证",
            "critical_hypothesis": "旧客户端仍能解析响应",
            "continue_if": "旧版回归与契约门禁通过",
            "stop_if": "旧版反序列化失败",
            "rollback": "撤回新增字段并恢复旧契约",
            "evidence_required": ["contract-gate", "executor-receipt"],
        }],
    }, ensure_ascii=False)
    registry = build_admin_registry(workspace_file=str(demo_workspace), task_id=task["task_id"], source="mcp", payload=acceptance_payload)
    acceptance = registry.dispatch("delivery_contract_update")["items"][0]
    assert acceptance["critical_hypothesis"] == "旧客户端仍能解析响应"
    assert acceptance["evidence_required"] == ["contract-gate", "executor-receipt"]


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_acceptance_validation_design_is_available_through_cli_http_and_mcp(demo_workspace) -> None:
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_manual_validation_is_available_through_cli_http_and_mcp(demo_workspace) -> None:
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_delivery_skill_contract_is_available_through_admin_and_http(demo_workspace) -> None:
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


def test_closed_verified_delivery_canary_requires_objective_evidence_before_publish(demo_workspace, monkeypatch) -> None:
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
    record_delivery_validation(demo_workspace, task_id, status="passed", acceptance_ids=["AC-1"], evidence_kind="manual_verified", actor="reviewer")
    transition_delivery_stage(demo_workspace, task_id, "close")

    candidate = delivery_skill_candidate(demo_workspace, task_id)
    assert candidate["candidate"]["eligible"] is True
    assert candidate["candidate"]["contract"]["languages"] == ["java"]
    assert update_delivery_skill_contract(demo_workspace, task_id, contract={})["reason"] == "skill_contract_invalid"
    mismatched_evidence = _skill_contract()
    mismatched_evidence["acceptance_evidence"] = {
        "accepted_kinds": ["executor"],
        "required_fields": ["acceptance_ids", "evidence_refs"],
    }
    assert update_delivery_skill_contract(demo_workspace, task_id, contract=mismatched_evidence)["updated"] is True
    assert start_delivery_skill_canary(demo_workspace, task_id)["reason"] == "candidate_acceptance_evidence_missing"
    contract = update_delivery_skill_contract(demo_workspace, task_id, contract=_skill_contract(minimum_verified_passed=5))
    assert contract["updated"] is True
    assert contract["contract"]["rollback"]["action"]
    assert contract["contract"]["acceptance_evidence"]["required_fields"] == ["acceptance_ids", "evidence_refs"]
    assert publish_delivery_skill(demo_workspace, task_id)["reason"] == "canary_required"
    canary = start_delivery_skill_canary(demo_workspace, task_id, actor="test")
    assert canary["started"] is True
    skill_id = canary["skill"]["skill_id"]
    assert record_delivery_skill_observation(demo_workspace, skill_id, outcome="passed")["reason"] == "evidence_required"
    assert record_delivery_skill_observation(
        demo_workspace,
        skill_id,
        outcome="passed",
        evidence_refs=["validation:not-real"],
    )["reason"] == "evidence_not_resolvable"
    for index in range(3):
        receipt = record_delivery_validation(
            demo_workspace,
            task_id,
            status="passed",
            acceptance_ids=["AC-1"],
            evidence_kind="manual_verified",
            actor=f"reviewer-{index}",
        )["receipt"]
        result = record_delivery_skill_observation(demo_workspace, skill_id, outcome="passed", evidence_refs=[receipt["evidence_refs"][-1]], latency_ms=100, token_count=20)
        assert result["recorded"] is True
        assert record_delivery_skill_observation(
            demo_workspace,
            skill_id,
            outcome="passed",
            evidence_refs=[receipt["evidence_refs"][-1]],
        )["reason"] == "evidence_already_used"
    evaluation = evaluate_delivery_skill(demo_workspace, skill_id=skill_id)
    assert evaluation["metrics"]["verified_passed"] == 3
    assert evaluation["minimum_verified_passed"] == 5
    assert evaluation["publishable"] is False
    assert evaluation["recommendation"] == "继续灰度并记录真实验证证据"
    assert publish_delivery_skill(demo_workspace, task_id)["reason"] == "canary_evidence_insufficient"
    replay = delivery_skill_replay_set(demo_workspace, skill_id=skill_id)
    assert replay["count"] == 3
    assert "发布接口" not in str(replay)
    revised = update_delivery_skill_contract(
        demo_workspace,
        task_id,
        contract=_skill_contract(stop_condition="索引陈旧或验收变化时停止"),
    )
    assert revised["updated"] is True
    assert "索引陈旧或验收变化时停止" in Path(canary["path"]).read_text(encoding="utf-8")
    assert evaluate_delivery_skill(demo_workspace, skill_id=skill_id)["metrics"]["verified_passed"] == 0
    assert delivery_skill_replay_set(demo_workspace, skill_id=skill_id)["count"] == 0
    for index in range(3, 6):
        receipt = record_delivery_validation(
            demo_workspace,
            task_id,
            status="passed",
            acceptance_ids=["AC-1"],
            evidence_kind="manual_verified",
            actor=f"reviewer-{index}",
        )["receipt"]
        assert record_delivery_skill_observation(
            demo_workspace,
            skill_id,
            outcome="passed",
            evidence_refs=[receipt["evidence_refs"][-1]],
        )["recorded"] is True
    def fail_asset_registration(*_args, **_kwargs):
        raise OSError("asset registry unavailable")

    monkeypatch.setattr("memory_center.core.knowledge.assets.register_collaboration_asset", fail_asset_registration)
    published = publish_delivery_skill(demo_workspace, task_id)
    assert published["published"] is True
    assert published["asset_registered"] is False
    assert published["asset_diagnostic"]["error_type"] == "OSError"
    assert published["next_action"] == "Skill 已发布；执行 artifact asset-sync 补齐协作资产，并持续记录效果。"
    assert update_delivery_skill_contract(demo_workspace, task_id, contract=_skill_contract(languages=["python"]))["reason"] == "published_skill_contract_immutable"
    recommendation = recommend_delivery_skills(demo_workspace, "发布接口")["skills"][0]
    assert recommendation["skill_id"] == skill_id
    assert recommendation["prohibited_conditions"] == ["需求边界不清时禁止使用"]
    assert recommendation["rollback"]["action"]
    assert not recommend_delivery_skills(demo_workspace, "发布接口", language="python")["skills"]
    assert rollback_delivery_skill(demo_workspace, skill_id, reason="发现回归")["rolled_back"] is True
    assert not recommend_delivery_skills(demo_workspace, "发布接口")["skills"]
    rolled_back_status = delivery_skill_status(demo_workspace, task_id)
    assert rolled_back_status["lifecycle"] == "rolled_back"
    assert rolled_back_status["next_action"] == "delivery-skill-canary"
    restarted = start_delivery_skill_canary(demo_workspace, task_id, actor="test-restart")
    assert restarted["started"] is True
    assert restarted["skill"]["skill_id"] == skill_id
    assert restarted["skill"]["activation_id"] != canary["skill"]["activation_id"]
    assert delivery_skill_status(demo_workspace, task_id)["lifecycle"] == "canary"
    assert evaluate_delivery_skill(demo_workspace, skill_id=skill_id)["metrics"]["verified_passed"] == 0

    receipt = record_delivery_validation(
        demo_workspace,
        task_id,
        status="passed",
        acceptance_ids=["AC-1"],
        evidence_kind="manual_verified",
        actor="parallel-reviewer",
    )["receipt"]
    evidence_ref = receipt["evidence_refs"][-1]
    task_ref = evidence_ref.split(":", 2)[1]
    external_receipt = record_delivery_validation(
        demo_workspace,
        task_id,
        status="passed",
        evidence_kind="recorded_external",
    )["receipt"]
    forged_ref = f"delivery-validation:{task_ref}:{external_receipt['receipt_id']}"
    assert record_delivery_skill_observation(
        demo_workspace,
        skill_id,
        outcome="passed",
        evidence_refs=[forged_ref],
    )["reason"] == "evidence_not_resolvable"
    original_resolver = delivery_module._resolved_delivery_evidence_refs
    barrier = threading.Barrier(2)
    call_lock = threading.Lock()
    call_count = 0

    def synchronize_first_two_resolutions(*args, **kwargs):
        nonlocal call_count
        resolved = original_resolver(*args, **kwargs)
        with call_lock:
            call_count += 1
            should_wait = call_count <= 2
        if should_wait:
            barrier.wait(timeout=5)
        return resolved

    monkeypatch.setattr(delivery_module, "_resolved_delivery_evidence_refs", synchronize_first_two_resolutions)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(
            lambda _: record_delivery_skill_observation(
                demo_workspace,
                skill_id,
                outcome="passed",
                evidence_refs=[evidence_ref],
            ),
            range(2),
        ))
    assert sum(bool(result.get("recorded")) for result in results) == 1
    assert {result.get("reason", "recorded") for result in results} == {"recorded", "evidence_already_used"}
    replay_path = demo_workspace.parent / "artifacts" / "skills" / "delivery-replays" / f"{skill_id}.jsonl"
    replay_path.unlink(missing_ok=True)
    replay_path.parent.mkdir(parents=True, exist_ok=True)
    replay_path.write_text(
        "".join(
            json.dumps({
                "privacy": "redacted_contract_metrics_only",
                "observation_id": f"legacy-{index}",
                "skill_id": skill_id,
                "activation_id": "superseded-activation",
                "contract_sha256": "superseded-contract",
            }) + "\n"
            for index in range(20)
        ),
        encoding="utf-8",
    )
    assert delivery_skill_replay_set(demo_workspace, skill_id=skill_id)["count"] == 1
    assert evaluate_delivery_skill(demo_workspace, skill_id=skill_id)["metrics"]["redacted_replays"] == 1


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
        record_delivery_validation(demo_workspace, task_id, status="passed", acceptance_ids=["AC-1"], evidence_kind="manual_verified", actor="reviewer")
        transition_delivery_stage(demo_workspace, task_id, "close")
        delivery_skill_candidate(demo_workspace, task_id)
    synthesis = synthesize_delivery_skill_trajectories(demo_workspace)
    assert synthesis["syntheses"]


def test_recommendation_skips_published_skills_with_invalid_legacy_contract(demo_workspace) -> None:
    from memory_center.core.storage.workspace import WorkspaceStore

    store = WorkspaceStore(demo_workspace)
    registry = store.artifacts_dir / "skills" / "delivery-skill-registry.json"
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text(
        json.dumps({
            "schema_version": 1,
            "skills": [{
                "skill_id": "legacy-skill",
                "title": "发布接口",
                "lifecycle": "published",
                "signature": {"terms": ["发布", "接口"]},
                "contract": {"languages": ["java"]},
            }],
        }, ensure_ascii=False),
        encoding="utf-8",
    )

    result = recommend_delivery_skills(demo_workspace, "发布接口")

    assert result["skills"] == []
    assert result["skipped_invalid_contract"] == 1
    assert result["next_action"] == "先迁移或重新生成无完整边界契约的已发布 Skill；有效 Skill 可继续使用。"


def test_delivery_skill_registry_recovers_backup_and_refuses_double_corruption(demo_workspace) -> None:
    from memory_center.core.storage.workspace import WorkspaceStore

    store = WorkspaceStore(demo_workspace)
    path = store.artifacts_dir / "skills" / "delivery-skill-registry.json"
    backup = path.with_name(f"{path.name}.bak")
    path.parent.mkdir(parents=True, exist_ok=True)
    valid = {
        "schema_version": 2,
        "skills": [{
            "skill_id": "recoverable-skill",
            "title": "发布接口",
            "lifecycle": "published",
            "signature": {"terms": ["发布", "接口"]},
            "contract": _skill_contract(),
        }],
    }
    path.write_text("{broken", encoding="utf-8")
    backup.write_text(json.dumps(valid, ensure_ascii=False), encoding="utf-8")

    recovered = recommend_delivery_skills(demo_workspace, "发布接口")

    assert recovered["skills"][0]["skill_id"] == "recoverable-skill"
    assert json.loads(path.read_text(encoding="utf-8"))["skills"][0]["skill_id"] == "recoverable-skill"

    path.write_text("{broken-again", encoding="utf-8")
    backup.write_text("{also-broken", encoding="utf-8")
    with pytest.raises(DeliverySkillRegistryCorruptionError):
        recommend_delivery_skills(demo_workspace, "发布接口")
    assert path.read_text(encoding="utf-8") == "{broken-again"


def test_delivery_skill_registry_preserves_independent_stale_updates(demo_workspace) -> None:
    from memory_center.core.storage.workspace import WorkspaceStore
    from memory_center.core.tasks.delivery import _read_skill_registry, _write_skill_registry

    store = WorkspaceStore(demo_workspace)
    first_snapshot = _read_skill_registry(store)
    second_snapshot = _read_skill_registry(store)
    first_snapshot["skills"].append({"skill_id": "skill-a", "lifecycle": "canary"})
    second_snapshot["skills"].append({"skill_id": "skill-b", "lifecycle": "canary"})

    _write_skill_registry(store, first_snapshot, changed_skill_ids={"skill-a"})
    _write_skill_registry(store, second_snapshot, changed_skill_ids={"skill-b"})

    assert {row["skill_id"] for row in _read_skill_registry(store)["skills"]} == {"skill-a", "skill-b"}

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
    update_delivery_contract(demo_workspace, task_id, kind="requirements", items=[{"id": "REQ-1", "title": "发布", "scope": "接口", "out_of_scope": ["不修改认证"], "source_refs": ["req:1"], "acceptance_ids": ["AC-1"]}])
    update_delivery_contract(demo_workspace, task_id, kind="subtasks", items=[{
        "id": "SUB-1",
        "title": "定位发布入口",
        "requirement_ids": ["REQ-1"],
        "code_targets": ["app/publish.py"],
        "read_targets": ["app/publish.py"],
        "write_targets": ["app/publish.py"],
        "stop_conditions": ["接口契约未确认"],
    }])
    update_delivery_contract(demo_workspace, task_id, kind="acceptance", items=[{
        "id": "AC-1",
        "title": "解释器可用",
        "critical_hypothesis": "预注册解释器可执行",
        "continue_if": "命令退出码为 0",
        "stop_if": "命令不存在或超时",
        "rollback": "移除验证 profile",
        "evidence_required": ["executor-receipt"],
    }])
    task_dir = demo_workspace.parent / "artifacts" / "tasks" / task_id
    assert json.loads((task_dir / "requirements.json").read_text(encoding="utf-8"))["schema_version"] == 2
    assert json.loads((task_dir / "acceptance.json").read_text(encoding="utf-8"))["schema_version"] == 2
    matrix = delivery_matrix(demo_workspace, task_id)
    assert matrix["matrix"]["coverage"]["requirements"] == 1
    assert matrix["matrix"]["coverage"]["designed_acceptance"] == 1
    assert matrix["matrix"]["coverage"]["validation_design_coverage"] == 1.0
    acceptance = matrix["matrix"]["rows"][0]["acceptance"][0]
    assert acceptance["validation_design_complete"] is True
    assert acceptance["evidence_required"] == ["executor-receipt"]
    assert delivery_workflow_status(demo_workspace, task_id)["counts"]["designed_acceptance"] == 1
    tech_spec = (demo_workspace.parent / "artifacts" / "tasks" / task_id / "TECH_SPEC.md").read_text(encoding="utf-8")
    assert "非目标：不修改认证" in tech_spec
    assert "来源：req:1" in tech_spec
    assert "子任务 SUB-1: 读范围=app/publish.py; 写范围=app/publish.py; 停止条件=接口契约未确认" in tech_spec
    assert "关键假设：预注册解释器可执行" in tech_spec
    assert "已设计验证的验收：1/1" in tech_spec
    blocked = execute_delivery_validation(demo_workspace, task_id, profile_id="missing")
    assert blocked["reason"] == "profile_not_allowed"
    update_delivery_policy(demo_workspace, {"validation_profiles": [{"id": "missing-command", "argv": ["memory-center-command-that-does-not-exist"], "timeout_sec": 10}]})
    environment_failure = execute_delivery_validation(demo_workspace, task_id, profile_id="missing-command")
    assert environment_failure["executed"] is False
    assert environment_failure["reason"] == "environment_error"
    assert environment_failure["error_type"] == "FileNotFoundError"
    update_delivery_policy(demo_workspace, {"validation_profiles": [{"id": "python-version", "argv": ["python3", "--version"], "timeout_sec": 10}]})
    executed = execute_delivery_validation(demo_workspace, task_id, profile_id="python-version", acceptance_ids=["AC-1"])
    assert executed["executed"] is True
    assert executed["receipt"]["evidence_kind"] == "executor"


def test_delivery_gate_keeps_older_verified_receipts_resolvable(demo_workspace) -> None:
    task_id = create_task_space(demo_workspace, title="长期验证", intent="保留早期验证证据")["task_id"]
    initialize_delivery_workflow(demo_workspace, task_id)
    update_delivery_contract(
        demo_workspace,
        task_id,
        kind="acceptance",
        items=[{"id": "AC-1", "title": "长期有效", "required": True, "evidence_required": ["contract-gate"]}],
    )
    record_delivery_validation(
        demo_workspace,
        task_id,
        status="passed",
        acceptance_ids=["AC-1"],
        evidence_types=["contract-gate"],
        evidence_kind="manual_verified",
        actor="reviewer",
    )
    receipts_path = demo_workspace.parent / "artifacts" / "tasks" / task_id / "verification-receipts.jsonl"
    initial_mtime_ns = receipts_path.stat().st_mtime_ns
    initialize_delivery_workflow(demo_workspace, task_id, include_status=False)
    assert receipts_path.stat().st_mtime_ns == initial_mtime_ns
    for _ in range(250):
        record_delivery_validation(
            demo_workspace,
            task_id,
            status="recorded",
            evidence_kind="recorded_external",
        )

    status = delivery_workflow_status(demo_workspace, task_id)

    assert status["counts"]["verified_acceptance"] == 1
    assert status["counts"]["evidence_complete_acceptance"] == 1
    assert status["counts"]["validation_receipts"] == 251
    delivery_file = demo_workspace.parent / "artifacts" / "tasks" / task_id / "delivery.json"
    assert len(json.loads(delivery_file.read_text(encoding="utf-8"))["history"]) == 200


def test_delivery_corruption_is_reported_without_overwriting_source(demo_workspace) -> None:
    task_id = create_task_space(demo_workspace, title="损坏保护", intent="保留原始任务状态")["task_id"]
    initialize_delivery_workflow(demo_workspace, task_id)
    delivery_file = demo_workspace.parent / "artifacts" / "tasks" / task_id / "delivery.json"
    corrupted = b"{broken-delivery"
    delivery_file.write_bytes(corrupted)

    with pytest.raises(DeliveryArtifactCorruptionError, match="delivery.json"):
        record_delivery_validation(demo_workspace, task_id, status="recorded")

    assert delivery_file.read_bytes() == corrupted


def test_delivery_jsonl_tail_preserves_valid_multibyte_rows(tmp_path) -> None:
    path = tmp_path / "valid.jsonl"
    line = json.dumps({"text": "中" * 18}, ensure_ascii=False) + "\n"
    path.write_text(line * 1000, encoding="utf-8")

    rows = delivery_module._read_jsonl_tail(path, 20)

    assert len(rows) == 20
    assert all(json.loads(row)["text"] == "中" * 18 for row in rows)


def test_delivery_receipt_sync_does_not_advance_past_concurrent_append(demo_workspace, monkeypatch) -> None:
    from memory_center.core.storage.workspace import WorkspaceStore

    task_id = create_task_space(demo_workspace, title="并发回执", intent="验证同步水位")['task_id']
    initialize_delivery_workflow(demo_workspace, task_id, include_status=False)
    store = WorkspaceStore(demo_workspace)
    task_dir = store.artifacts_dir / "tasks" / task_id
    path = task_dir / delivery_module.VALIDATION_RECEIPTS_FILE

    def receipt(index: int) -> dict[str, object]:
        return {
            "receipt_id": f"race-{index}",
            "recorded_at": f"2026-01-01T00:00:0{index}+00:00",
            "status": "recorded",
            "evidence_kind": "recorded_external",
        }

    path.write_text(json.dumps(receipt(1)) + "\n", encoding="utf-8")
    delivery_module._recent_receipts(store, task_dir)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(receipt(2)) + "\n")

    backend = store.memory_backend()
    original_replace = backend.replace_delivery_receipts

    def append_after_snapshot(task_key, receipts, **kwargs):
        snapshot = list(receipts)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(receipt(3)) + "\n")
        return original_replace(task_key, snapshot, **kwargs)

    monkeypatch.setattr(backend, "replace_delivery_receipts", append_after_snapshot)
    first = delivery_module._recent_receipts(store, task_dir)
    monkeypatch.setattr(backend, "replace_delivery_receipts", original_replace)
    second = delivery_module._recent_receipts(store, task_dir)

    assert [row["receipt_id"] for row in first] == ["race-1", "race-2"]
    assert [row["receipt_id"] for row in second] == ["race-1", "race-2", "race-3"]


def test_delivery_status_uses_bounded_receipt_queries(demo_workspace, monkeypatch) -> None:
    from memory_center.core.storage.runtime import RuntimeStore

    task_id = create_task_space(demo_workspace, title="有界查询", intent="禁止全量解码")['task_id']
    initialize_delivery_workflow(demo_workspace, task_id, include_status=False)
    original_query = RuntimeStore.query_delivery_receipts
    calls: list[dict[str, object]] = []

    def bounded_query(self, task_key, **kwargs):
        calls.append(kwargs)
        assert kwargs.get("limit", 0) or kwargs.get("receipt_ids")
        return original_query(self, task_key, **kwargs)

    monkeypatch.setattr(RuntimeStore, "query_delivery_receipts", bounded_query)

    assert delivery_workflow_status(demo_workspace, task_id)["initialized"] is True
    assert calls == [{"receipt_ids": None, "trusted_passed_only": False, "limit": 100}]


def test_delivery_write_touches_task_activity_once(demo_workspace, monkeypatch) -> None:
    task_id = create_task_space(demo_workspace, title="活动时间", intent="避免重复写入")['task_id']
    initialize_delivery_workflow(demo_workspace, task_id, include_status=False)
    calls: list[str] = []
    monkeypatch.setattr(
        delivery_module,
        "touch_task_activity",
        lambda workspace_file, current_task_id, source: calls.append(source),
    )

    record_delivery_validation(demo_workspace, task_id, status="recorded")

    assert calls == ["delivery_validation"]


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


def test_acceptance_validation_design_is_optional_but_can_be_enforced(demo_workspace) -> None:
    from memory_center.core.tasks.delivery import delivery_matrix, update_delivery_policy

    legacy_task = create_task_space(demo_workspace, title="兼容旧验收", intent="默认兼容")['task_id']
    initialize_delivery_workflow(demo_workspace, legacy_task)
    update_delivery_contract(demo_workspace, legacy_task, kind="requirements", items=[{
        "id": "REQ-1", "title": "兼容需求", "scope": "接口", "source_refs": ["req:legacy"], "acceptance_ids": ["AC-1"],
    }])
    update_delivery_contract(demo_workspace, legacy_task, kind="acceptance", items=[{
        "id": "AC-1", "title": "旧版回归",
    }])
    assert transition_delivery_stage(demo_workspace, legacy_task, "breakdown")["transitioned"] is True
    assert transition_delivery_stage(demo_workspace, legacy_task, "locate")["transitioned"] is True
    legacy_matrix = delivery_matrix(demo_workspace, legacy_task, write=False)["matrix"]
    assert legacy_matrix["coverage"]["designed_acceptance"] == 0
    assert legacy_matrix["coverage"]["validation_design_coverage"] == 0.0

    update_delivery_policy(demo_workspace, {"enforce_validation_design_contract": True})
    strict_task = create_task_space(demo_workspace, title="严格验收设计", intent="强制可证伪")['task_id']
    initialize_delivery_workflow(demo_workspace, strict_task)
    update_delivery_contract(demo_workspace, strict_task, kind="requirements", items=[{
        "id": "REQ-1", "title": "严格需求", "scope": "接口", "source_refs": ["req:strict"], "acceptance_ids": ["AC-1"],
    }])
    update_delivery_contract(demo_workspace, strict_task, kind="acceptance", items=[{
        "id": "AC-1", "title": "兼容性验证",
    }])
    assert transition_delivery_stage(demo_workspace, strict_task, "breakdown")["transitioned"] is True
    blocked = transition_delivery_stage(demo_workspace, strict_task, "locate")
    assert blocked["transitioned"] is False
    assert blocked["gate"]["code"] == "validation_design_required"
    assert blocked["gate"]["missing"] == ["AC-1"]

    update_delivery_contract(demo_workspace, strict_task, kind="acceptance", items=[{
        "id": "AC-1",
        "title": "兼容性验证",
        "critical_hypothesis": "旧客户端仍兼容",
        "continue_if": "旧版回归通过",
        "stop_if": "旧版反序列化失败",
        "rollback": "恢复旧契约",
        "evidence_required": ["contract-gate", "executor-receipt"],
    }])
    assert transition_delivery_stage(demo_workspace, strict_task, "locate")["transitioned"] is True
    strict_matrix = delivery_matrix(demo_workspace, strict_task, write=False)["matrix"]
    assert strict_matrix["policy"]["enforce_validation_design_contract"] is True
    assert strict_matrix["coverage"]["validation_design_coverage"] == 1.0


def test_acceptance_evidence_contract_closes_from_structured_receipts(demo_workspace) -> None:
    from memory_center.core.tasks.delivery import (
        delivery_matrix,
        execute_delivery_validation,
        update_delivery_policy,
    )

    update_delivery_policy(demo_workspace, {
        "enforce_evidence_contract": True,
        "validation_profiles": [{
            "id": "contract-gate",
            "argv": ["python3", "--version"],
            "timeout_sec": 10,
            "evidence_types": ["contract-gate"],
        }],
    })
    task_id = create_task_space(demo_workspace, title="证据闭环", intent="自动核对证据")['task_id']
    initialize_delivery_workflow(demo_workspace, task_id)
    update_delivery_contract(demo_workspace, task_id, kind="requirements", items=[{
        "id": "REQ-1", "title": "证据闭环", "scope": "接口", "source_refs": ["req:1"], "acceptance_ids": ["AC-1"],
    }])
    update_delivery_contract(demo_workspace, task_id, kind="acceptance", items=[{
        "id": "AC-1",
        "title": "契约与执行验证",
        "critical_hypothesis": "契约兼容且测试可执行",
        "continue_if": "两类证据均通过",
        "stop_if": "任一证据缺失",
        "rollback": "恢复旧契约",
        "evidence_required": ["contract-gate", "executor-receipt"],
    }])
    record_delivery_validation(
        demo_workspace,
        task_id,
        status="passed",
        acceptance_ids=["AC-1"],
        evidence_types=["contract-gate"],
        evidence_kind="manual_verified",
        actor="reviewer",
    )

    partial = delivery_matrix(demo_workspace, task_id, write=False)["matrix"]
    acceptance = partial["rows"][0]["acceptance"][0]
    assert acceptance["evidence_observed"] == ["contract-gate", "manual-verification"]
    assert acceptance["evidence_missing"] == ["executor-receipt"]
    assert acceptance["evidence_complete"] is False
    assert partial["coverage"]["evidence_complete_acceptance"] == 0
    blocked = transition_delivery_stage(demo_workspace, task_id, "close")
    assert blocked["transitioned"] is False
    assert blocked["gate"]["code"] == "evidence_contract_required"
    assert blocked["gate"]["missing"] == ["AC-1:executor-receipt"]

    executed = execute_delivery_validation(
        demo_workspace,
        task_id,
        profile_id="contract-gate",
        acceptance_ids=["AC-1"],
    )
    assert executed["receipt"]["evidence_types"] == ["executor-receipt", "profile:contract-gate", "contract-gate"]
    complete = delivery_matrix(demo_workspace, task_id, write=False)["matrix"]
    assert complete["policy"]["enforce_evidence_contract"] is True
    assert complete["coverage"]["evidence_complete_acceptance"] == 1
    assert complete["coverage"]["evidence_contract_coverage"] == 1.0
    assert transition_delivery_stage(demo_workspace, task_id, "close")["transitioned"] is True


def test_compact_task_artifacts_keeps_bounded_live_content(demo_workspace) -> None:
    task = create_task_space(demo_workspace, title="大工件", intent="压缩")
    task_id = task["task_id"]
    result = update_task_artifact(demo_workspace, task_id, "context", "x" * 60_000)
    assert result["updated"] is True
    compacted = compact_task_artifacts(demo_workspace, task_id, threshold_bytes=1_000, keep_bytes=512)
    assert compacted["compacted"]
    item = compacted["compacted"][0]
    assert item["before_bytes"] > item["after_bytes"]


def test_waiver_lifecycle_and_gate_bypass(demo_workspace) -> None:
    """Waiver create -> approve -> bypass gate flow."""
    from memory_center.core.tasks.delivery import (
        approve_delivery_waiver,
        create_delivery_waiver,
        list_delivery_waivers,
        revoke_delivery_waiver,
        transition_delivery_stage,
    )
    task = create_task_space(demo_workspace, title="Waiver测试", intent="测试门禁豁免")
    task_id = task["task_id"]
    initialize_delivery_workflow(demo_workspace, task_id, actor="test")

    # Gate should fail (no requirements)
    blocked = transition_delivery_stage(demo_workspace, task_id, "breakdown")
    assert blocked["transitioned"] is False
    gate_code = blocked["gate"]["code"]

    # Create waiver
    waiver_result = create_delivery_waiver(demo_workspace, task_id, gate_code=gate_code, reason="测试豁免", actor="reviewer")
    assert waiver_result["created"] is True
    waiver_id = waiver_result["waiver_id"]

    # Pending waiver should NOT bypass gate
    still_blocked = transition_delivery_stage(demo_workspace, task_id, "breakdown")
    assert still_blocked["transitioned"] is False

    # Approve waiver
    approved = approve_delivery_waiver(demo_workspace, task_id, waiver_id=waiver_id, actor="admin")
    assert approved["approved"] is True

    # Now gate should pass via waiver
    passed = transition_delivery_stage(demo_workspace, task_id, "breakdown")
    assert passed["transitioned"] is True
    assert passed["gate"]["passed"] is False  # gate itself still reports not passed
    # History should show waived_transition
    history = passed["delivery"]["stage_history"]
    assert any(entry.get("event") == "waived_transition" for entry in history)

    # Revoke should work
    revoked = revoke_delivery_waiver(demo_workspace, task_id, waiver_id=waiver_id, reason="不再需要", actor="admin")
    assert revoked["revoked"] is True

    # List waivers should show revoked status
    waivers = list_delivery_waivers(demo_workspace, task_id)
    assert waivers["total"] == 1
    assert waivers["all"][0]["status"] == "revoked"


def test_waiver_expiry_is_fail_closed_for_unparseable_and_naive_values() -> None:
    """无时区时间戳按 UTC 解释；无法解析的过期时间不得变成永久豁免。"""
    from memory_center.core.tasks.delivery import _waiver_expired

    assert _waiver_expired({}) is False
    assert _waiver_expired({"expires_at": ""}) is False
    assert _waiver_expired({"expires_at": "2020-01-01T00:00:00"}) is True
    assert _waiver_expired({"expires_at": "2020-01-01T00:00:00+00:00"}) is True
    assert _waiver_expired({"expires_at": "2999-01-01T00:00:00"}) is False
    assert _waiver_expired({"expires_at": "next week"}) is True


def test_approving_an_expired_waiver_persists_the_expired_status(demo_workspace) -> None:
    """过期审批必须落盘：此前只改内存副本，磁盘上仍是 pending，列表又会当 pending 列出。"""
    from memory_center.core.tasks.delivery import (
        approve_delivery_waiver,
        create_delivery_waiver,
        list_delivery_waivers,
        transition_delivery_stage,
    )

    task = create_task_space(demo_workspace, title="过期豁免落盘", intent="测试过期豁免")
    task_id = task["task_id"]
    initialize_delivery_workflow(demo_workspace, task_id, actor="test")
    gate_code = transition_delivery_stage(demo_workspace, task_id, "breakdown")["gate"]["code"]
    waiver_id = create_delivery_waiver(
        demo_workspace, task_id, gate_code=gate_code, reason="已过期",
        expires_at="2020-01-01T00:00:00+00:00", actor="reviewer",
    )["waiver_id"]

    rejected = approve_delivery_waiver(demo_workspace, task_id, waiver_id=waiver_id, actor="admin")
    assert rejected["approved"] is False
    assert rejected["reason"] == "waiver_expired"
    # 重新从磁盘读取也必须看到 expired（此前会回退成 pending）
    assert list_delivery_waivers(demo_workspace, task_id)["all"][0]["status"] == "expired"
    # 状态已持久化，后续审批不再走「过期」分支而是拒绝重复审批
    assert approve_delivery_waiver(demo_workspace, task_id, waiver_id=waiver_id, actor="admin")["reason"] == "waiver_already_expired"
    # 过期 waiver 不得绕过门禁
    assert transition_delivery_stage(demo_workspace, task_id, "breakdown")["transitioned"] is False


def test_listing_waivers_auto_expires_pending_ones(demo_workspace) -> None:
    """pending 也会过期：过期后本就无法审批，列表不得继续把它算作 active。"""
    from memory_center.core.tasks.delivery import (
        create_delivery_waiver,
        list_delivery_waivers,
        transition_delivery_stage,
    )

    task = create_task_space(demo_workspace, title="过期Pending", intent="测试 pending 过期")
    task_id = task["task_id"]
    initialize_delivery_workflow(demo_workspace, task_id, actor="test")
    gate_code = transition_delivery_stage(demo_workspace, task_id, "breakdown")["gate"]["code"]
    create_delivery_waiver(
        demo_workspace, task_id, gate_code=gate_code, reason="已过期",
        expires_at="2020-01-01T00:00:00+00:00", actor="reviewer",
    )
    listed = list_delivery_waivers(demo_workspace, task_id)
    assert listed["all"][0]["status"] == "expired"
    assert listed["active"] == []

    # 未设置 expires_at 的 waiver 永不过期，必须仍为 pending/active
    create_delivery_waiver(demo_workspace, task_id, gate_code=gate_code, reason="无期限", actor="reviewer")
    active = list_delivery_waivers(demo_workspace, task_id)["active"]
    assert [item["status"] for item in active] == ["pending"]


def test_expired_waiver_cannot_bypass_gate(demo_workspace) -> None:
    from memory_center.core.tasks.delivery import (
        approve_delivery_waiver,
        create_delivery_waiver,
        transition_delivery_stage,
    )
    task = create_task_space(demo_workspace, title="过期豁免门禁", intent="测试过期豁免")
    task_id = task["task_id"]
    initialize_delivery_workflow(demo_workspace, task_id, actor="test")
    blocked = transition_delivery_stage(demo_workspace, task_id, "breakdown")
    gate_code = blocked["gate"]["code"]

    created = create_delivery_waiver(
        demo_workspace, task_id, gate_code=gate_code, reason="已过期豁免", expires_at="2020-01-01T00:00:00"
    )
    approved = approve_delivery_waiver(demo_workspace, task_id, waiver_id=created["waiver_id"], actor="admin")
    still_blocked = transition_delivery_stage(demo_workspace, task_id, "breakdown")

    assert approved["approved"] is False
    assert approved["reason"] == "waiver_expired"
    assert still_blocked["transitioned"] is False


def test_create_waiver_rejects_unparseable_expiry(demo_workspace) -> None:
    from memory_center.core.tasks.delivery import create_delivery_waiver, transition_delivery_stage
    task = create_task_space(demo_workspace, title="非法过期时间", intent="测试校验")
    task_id = task["task_id"]
    initialize_delivery_workflow(demo_workspace, task_id, actor="test")
    blocked = transition_delivery_stage(demo_workspace, task_id, "breakdown")

    with pytest.raises(ValueError, match="ISO-8601"):
        create_delivery_waiver(
            demo_workspace,
            task_id,
            gate_code=blocked["gate"]["code"],
            reason="非法过期",
            expires_at="next week",
        )


def test_failure_classification(demo_workspace) -> None:
    """Four-category failure classification."""
    from memory_center.core.tasks.delivery import classify_delivery_failure
    task = create_task_space(demo_workspace, title="失败分类测试", intent="测试分类")
    task_id = task["task_id"]
    initialize_delivery_workflow(demo_workspace, task_id, actor="test")

    # Timeout should be auto_repairable
    result = classify_delivery_failure(demo_workspace, task_id, failure_type="timeout", context="网络超时", actor="test")
    assert result["classified"] is True
    assert result["classification"]["category"] == "auto_repairable"
    assert result["classification"]["retry_allowed"] is True

    # Permission should be environment_blocked
    result = classify_delivery_failure(demo_workspace, task_id, failure_type="permission", context="无写入权限", actor="test")
    assert result["classification"]["category"] == "environment_blocked"
    assert result["classification"]["retry_allowed"] is False

    # Not found should be requirement_path_error
    result = classify_delivery_failure(demo_workspace, task_id, failure_type="not_found", context="目标不存在", actor="test")
    assert result["classification"]["category"] == "requirement_path_error"

    # Unknown defaults to human_decision_required
    result = classify_delivery_failure(demo_workspace, task_id, failure_type="unknown_error", context="", actor="test")
    assert result["classification"]["category"] == "human_decision_required"


def test_delivery_task_metrics(demo_workspace) -> None:
    """Task-level effectiveness metrics."""
    from memory_center.core.tasks.delivery import delivery_task_metrics
    task = create_task_space(demo_workspace, title="度量测试", intent="测试度量")
    task_id = task["task_id"]
    initialize_delivery_workflow(demo_workspace, task_id, actor="test")

    # Empty metrics should have zero coverage
    metrics = delivery_task_metrics(demo_workspace, task_id)
    assert metrics["coverage"]["requirements"] == 0
    assert metrics["verification"]["total_receipts"] == 0

    # Add requirements and subtasks
    update_delivery_contract(demo_workspace, task_id, kind="requirements", items=[
        {"id": "REQ-1", "title": "功能A", "scope": "模块A", "acceptance_ids": ["AC-1"]},
    ])
    update_delivery_contract(demo_workspace, task_id, kind="subtasks", items=[
        {"id": "SUB-1", "title": "实现A", "requirement_ids": ["REQ-1"], "code_targets": ["ServiceA#method"]},
    ])
    update_delivery_contract(demo_workspace, task_id, kind="acceptance", items=[
        {"id": "AC-1", "title": "测试通过"},
    ])

    metrics = delivery_task_metrics(demo_workspace, task_id)
    assert metrics["coverage"]["requirements"] == 1
    assert metrics["coverage"]["located_requirements"] == 1
    assert metrics["coverage"]["requirement_coverage"] == 1.0
    assert metrics["verification"]["total_receipts"] == 0
    assert metrics["coverage"]["verified_acceptance"] == 0


def test_enhanced_propose_breakdown_with_freshness(demo_workspace) -> None:
    """Enhanced breakdown includes freshness hint."""
    from memory_center.core.tasks.delivery import propose_delivery_breakdown
    task = create_task_space(demo_workspace, title="拆解测试", intent="增强拆解")
    task_id = task["task_id"]
    initialize_delivery_workflow(demo_workspace, task_id, actor="test")

    # Without source_refs, should have ambiguity
    result = propose_delivery_breakdown(demo_workspace, task_id, source_refs=[], summary="添加新接口")
    assert result["applied"] is False
    assert result["candidate"]["decision_required"] is True
    assert len(result["candidate"]["ambiguities"]) >= 1
    assert "freshness" in result

    # With source_refs, fewer ambiguities
    result = propose_delivery_breakdown(demo_workspace, task_id, source_refs=["ref-1"], summary="添加新接口")
    assert result["candidate"]["source_refs"] == ["ref-1"]


def test_resume_check_delivery_hints(demo_workspace) -> None:
    """Resume check includes delivery matrix hints."""
    from memory_center.core.orchestrator.resume_check import _delivery_matrix_hints
    matrix = {
        "rows": [
            {"requirement_id": "REQ-1", "title": "功能A", "ambiguities": ["范围不清"], "acceptance": [{"id": "AC-1", "title": "测试", "verified": False, "validation_design_complete": False, "evidence_complete": False, "evidence_missing": ["contract-gate"]}]},
            {"requirement_id": "REQ-2", "title": "功能B", "ambiguities": [], "acceptance": [{"id": "AC-2", "title": "回归", "verified": True, "validation_design_complete": True, "evidence_complete": True, "evidence_missing": []}]},
        ],
        "policy": {"enforce_validation_design_contract": True, "enforce_evidence_contract": True},
    }
    metrics = {
        "coverage": {"requirement_coverage": 0.5, "acceptance_coverage": 0.5, "validation_design_coverage": 0.5, "evidence_contract_coverage": 0.5},
        "verification": {"success_rate": 0.5},
        "failure_classification": {"auto_repairable": 1, "environment_blocked": 0},
    }
    hints = _delivery_matrix_hints(matrix, metrics)
    assert len(hints["unresolved_ambiguities"]) == 1
    assert hints["unresolved_ambiguities"][0]["requirement_id"] == "REQ-1"
    assert len(hints["failed_validations"]) == 1
    assert hints["failed_validations"][0]["acceptance_id"] == "AC-1"
    assert len(hints["validation_design_gaps"]) == 1
    assert hints["validation_design_enforced"] is True
    assert hints["validation_design_coverage"] == 0.5
    assert hints["evidence_contract_enforced"] is True
    assert hints["evidence_contract_gaps"][0]["missing"] == ["contract-gate"]
    assert hints["evidence_contract_coverage"] == 0.5
    assert hints["has_critical_gaps"] is True
    assert hints["requirement_coverage"] == 0.5
