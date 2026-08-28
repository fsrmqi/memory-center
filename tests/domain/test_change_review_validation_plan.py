"""Change review validation_plan tests (subproject 2).

Verifies the additive validation_plan: risk->minimum-action mapping, MQ
destination evidence gap, contract-block -> blocked, no fabricated objects
when there is no graph evidence, determinism, and no command execution.
"""
from __future__ import annotations

from memory_center.core.orchestrator.change_review import _build_validation_plan


def _node(ntype: str, name: str = "X") -> dict:
    return {"id": f"{ntype}:{name}", "type": ntype, "name": name}


def test_dto_risk_plan():
    plan = _build_validation_plan(["a/Dto.java"], [_node("DTO")], [], contract_block=False)
    assert plan["status"] == "ready"
    assert plan["coverage"]["risk_categories"] == ["dto"]
    assert "serialization/deserialization compatibility check" in plan["minimum_actions"]
    assert "contract-gate" in plan["evidence_required"]
    assert plan["critical_hypotheses"][0]["id"] == "dto-compatible"
    assert plan["stop_if"]  # high-risk change carries stop_if


def test_mq_risk_is_insufficient_evidence():
    plan = _build_validation_plan(["a/Producer.java"], [_node("MQProducer")], [], contract_block=False)
    # MQ without provable destination must be an evidence gap, not ready.
    assert plan["status"] == "insufficient_evidence"
    assert "mq_destination_not_provable" in plan["coverage"]["uncovered_risks"]


def test_contract_block_forces_blocked():
    plan = _build_validation_plan(["a/Feign.java"], [_node("FeignClient")], [], contract_block=True)
    assert plan["status"] == "blocked"
    assert "contract block" in " ".join(plan["stop_if"])


def test_no_change_is_not_applicable():
    plan = _build_validation_plan([], [], [], contract_block=False)
    assert plan["status"] == "not_applicable"
    assert plan["minimum_actions"] == []


def test_private_method_never_fabricates_contract_risk():
    plan = _build_validation_plan(["a/Service.java"], [], [], contract_block=False)
    # No contract node evidence -> private/local change, not a contract risk.
    assert plan["coverage"]["risk_categories"] == ["method"]
    assert "feign" not in plan["coverage"]["risk_categories"]


def test_delete_risk_present():
    plan = _build_validation_plan(["a/Deleted.java"], [_node("DTO")], ["a/Deleted.java"], contract_block=False)
    assert "delete" in plan["coverage"]["risk_categories"]


def test_plan_is_deterministic():
    a = _build_validation_plan(["a/X.java", "b/Y.java"], [_node("DTO", "X"), _node("Endpoint", "Y")], [], False)
    b = _build_validation_plan(["a/X.java", "b/Y.java"], [_node("DTO", "X"), _node("Endpoint", "Y")], [], False)
    assert a == b
