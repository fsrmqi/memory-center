from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from typer.testing import CliRunner

import memory_center.core.tasks.delivery as delivery_module
from memory_center.application.admin import build_admin_registry
from memory_center.cli.main import app
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


def test_manual_validation_is_available_through_cli_http_and_mcp(demo_workspace) -> None:
    from memory_center.http.server import _route_request

    task_id = create_task_space(demo_workspace, title="人工验证", intent="验证公共入口")["task_id"]
    cli = CliRunner().invoke(
        app,
        [
            "artifact",
            "delivery-record-validation",
            "--workspace",
            str(demo_workspace),
            "--task-id",
            task_id,
            "--status",
            "passed",
            "--acceptance-ids",
            '["AC-1"]',
            "--evidence-kind",
            "manual_verified",
            "--actor",
            "alice",
        ],
    )
    assert cli.exit_code == 0
    assert "manual_verified" in cli.stdout
    assert "delivery-validation:" in cli.stdout

    payload = json.dumps({
        "status": "passed",
        "acceptance_ids": ["AC-1"],
        "evidence_kind": "manual_verified",
        "actor": "carol",
    })
    http = _route_request(
        "/workspace/delivery/validation",
        {"task_id": [task_id], "payload": [payload], "actor": ["bob"]},
        str(demo_workspace),
    )
    assert http["receipt"]["evidence_kind"] == "manual_verified"
    assert http["receipt"]["evidence_refs"][0].startswith("delivery-validation:")

    admin = build_admin_registry(
        workspace_file=str(demo_workspace),
        task_id=task_id,
        source="mcp",
        payload=payload,
    )
    mcp = admin.dispatch("delivery_validation_record")
    assert mcp["receipt"]["evidence_kind"] == "manual_verified"
    assert mcp["receipt"]["evidence_refs"][0].startswith("delivery-validation:")
    assert mcp["receipt"]["actor"] == "carol"
    assert mcp["receipt"]["reported_actor"] == "carol"
    assert mcp["receipt"]["actor_source"] == "mcp"
    assert mcp["receipt"]["identity_assurance"] == "self_asserted"

    with pytest.raises(ValueError, match="actor is required"):
        record_delivery_validation(
            demo_workspace,
            task_id,
            status="passed",
            evidence_kind="manual_verified",
        )
    malformed = json.dumps({
        "status": "passed",
        "acceptance_ids": "AC-1",
        "evidence_kind": "manual_verified",
        "actor": "dave",
    })
    with pytest.raises(ValueError, match="acceptance_ids must be a JSON array"):
        _route_request(
            "/workspace/delivery/validation",
            {"task_id": [task_id], "payload": [malformed], "actor": ["dave"]},
            str(demo_workspace),
        )
    with pytest.raises(ValueError, match="evidence_refs must contain only strings"):
        record_delivery_validation(
            demo_workspace,
            task_id,
            status="passed",
            evidence_kind="manual_verified",
            actor="dave",
            evidence_refs=[{"invalid": True}],
        )
    crowded = record_delivery_validation(
        demo_workspace,
        task_id,
        status="passed",
        evidence_kind="manual_verified",
        actor="erin",
        evidence_refs=[f"external:{index}" for index in range(50)],
    )["receipt"]
    assert crowded["evidence_refs"][0].startswith("delivery-validation:")
    assert len(crowded["evidence_refs"]) == 50


def test_delivery_skill_contract_is_available_through_admin_and_http(demo_workspace) -> None:
    from memory_center.http.server import _route_request

    task = create_task_space(demo_workspace, title="Skill 契约", intent="声明 Skill 范围")
    task_id = task["task_id"]
    delivery_skill_candidate(demo_workspace, task_id)
    payload = json.dumps(_skill_contract(), ensure_ascii=False)

    admin = build_admin_registry(workspace_file=str(demo_workspace), task_id=task_id, source="mcp", payload=payload)
    assert admin.dispatch("delivery_skill_contract_update")["updated"] is True
    http = _route_request(
        "/workspace/delivery/skill/contract",
        {"task_id": [task_id], "payload": [payload]},
        str(demo_workspace),
    )
    assert http["updated"] is True


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
    update_delivery_contract(demo_workspace, task_id, kind="requirements", items=[{"id": "REQ-1", "title": "发布", "scope": "接口", "source_refs": ["req:1"], "acceptance_ids": ["AC-1"]}])
    update_delivery_contract(demo_workspace, task_id, kind="acceptance", items=[{"id": "AC-1", "title": "解释器可用"}])
    task_dir = demo_workspace.parent / "artifacts" / "tasks" / task_id
    assert json.loads((task_dir / "requirements.json").read_text(encoding="utf-8"))["schema_version"] == 2
    assert json.loads((task_dir / "acceptance.json").read_text(encoding="utf-8"))["schema_version"] == 2
    matrix = delivery_matrix(demo_workspace, task_id)
    assert matrix["matrix"]["coverage"]["requirements"] == 1
    assert (demo_workspace.parent / "artifacts" / "tasks" / task_id / "TECH_SPEC.md").exists()
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
        items=[{"id": "AC-1", "title": "长期有效", "required": True}],
    )
    record_delivery_validation(
        demo_workspace,
        task_id,
        status="passed",
        acceptance_ids=["AC-1"],
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


def test_compact_task_artifacts_keeps_bounded_live_content(demo_workspace) -> None:
    task = create_task_space(demo_workspace, title="大工件", intent="压缩")
    task_id = task["task_id"]
    result = update_task_artifact(demo_workspace, task_id, "context", "x" * 60_000)
    assert result["updated"] is True
    compacted = compact_task_artifacts(demo_workspace, task_id, threshold_bytes=1_000, keep_bytes=512)
    assert compacted["compacted"]
    item = compacted["compacted"][0]
    assert item["before_bytes"] > item["after_bytes"]
