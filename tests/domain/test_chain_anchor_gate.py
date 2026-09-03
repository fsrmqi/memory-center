"""P1-A regression: chain anchor/scope negative-claim gate.

来自真实会话复盘（docs/LOOKUP_ARCHITECTURE_HANDOFF_PLAN.md §5 P1-A）：
``mc_lookup(mode="chain")`` 可能把包含明确类名的 query 锚定到不相关符号
（如 ``NoSuchClassXYZ`` 解析到 ``Result``），且 shard 路由可能遗漏锚点
所在项目。这两种情况下 chain 为空不能得出 "VERIFIED_NEGATIVE"（确认
没有调用方），否则 Agent 会提前停止定位。

门禁语义：只有 锚点匹配(matched) + 路由覆盖锚点项目 + fresh + coverage
完整 + 未截断/未超时 同时成立，空 chain 才允许负向结论。
"""
from __future__ import annotations

from memory_center.core.freshness.contract import evaluate_claim_boundary
from memory_center.application.lookup import _ensure_chain_gate, _result_count_for_claim
from memory_center.core.orchestrator.chain_anchor_gate import (
    build_chain_anchor_validation,
    build_chain_scope_validation,
    build_empty_chain_fallback,
    gate_reasons_from_chain,
)


# ---------------------------------------------------------------------------
# Unit: anchor validation
# ---------------------------------------------------------------------------


def test_anchor_validation_matched_exact_name():
    node = {"id": "Class:task-service:ArticleMoveService", "type": "Class", "name": "ArticleMoveService", "project": "task-service"}
    validation = build_chain_anchor_validation(requested="ArticleMoveService", anchor=node)
    assert validation["status"] == "matched"
    assert validation["requested_symbol"] == "ArticleMoveService"
    assert validation["resolved_anchor"] == "ArticleMoveService"


def test_anchor_validation_matched_qualified_request():
    node = {"id": "Class:api:OrderService", "type": "Class", "name": "com.example.api.OrderService", "project": "api"}
    validation = build_chain_anchor_validation(requested="OrderService", anchor=node)
    assert validation["status"] == "matched"


def test_anchor_validation_mismatch_on_wrong_symbol():
    """The field bug: a nonsense query resolves to an unrelated class."""
    node = {"id": "Class:common-api:Result", "type": "Class", "name": "Result", "project": "common-api"}
    validation = build_chain_anchor_validation(requested="NoSuchClassXYZ", anchor=node)
    assert validation["status"] == "mismatch"
    assert validation["reason"]


def test_anchor_validation_missing_when_not_found():
    validation = build_chain_anchor_validation(requested="ArticleMoveService", anchor=None)
    assert validation["status"] == "missing"


def test_anchor_validation_matched_with_explicit_symbol_and_chinese_intent():
    """中文意图词混入 query 但显式 symbol 正确时仍匹配。"""
    node = {"id": "Class:task-service:ArticleMoveService", "type": "Class", "name": "ArticleMoveService", "project": "task-service"}
    validation = build_chain_anchor_validation(requested="查一下 ArticleMoveService 的调用方", anchor=node, explicit_symbol="ArticleMoveService")
    assert validation["status"] == "matched"


# ---------------------------------------------------------------------------
# Unit: scope validation
# ---------------------------------------------------------------------------


def test_scope_validation_covered():
    validation = build_chain_scope_validation(
        anchor={"project": "task-service"},
        routed_projects=["task-service", "article-service"],
        route_available=True,
    )
    assert validation["anchor_project_covered"] is True
    assert validation["scope_incomplete"] is False


def test_scope_validation_incomplete_when_anchor_project_missing():
    validation = build_chain_scope_validation(
        anchor={"project": "task-service"},
        routed_projects=["article-service"],
        route_available=True,
    )
    assert validation["anchor_project_covered"] is False
    assert validation["scope_incomplete"] is True


def test_scope_validation_unavailable_route_is_incomplete():
    validation = build_chain_scope_validation(
        anchor={"project": "task-service"},
        routed_projects=[],
        route_available=False,
    )
    assert validation["scope_incomplete"] is True


def test_finalize_gate_is_conservative_for_group_chain_without_target():
    payload = {"mode": "chain-group", "_chain_requested_symbol": "ArticleMoveService", "result": {"local_chain": [], "chain_summary": {}}}
    gate = _ensure_chain_gate(payload, "ArticleMoveService", {"shard_route": {"available": True, "selected_projects": ["task-service"]}})
    assert gate == {"anchor_status": "missing", "scope_incomplete": True}
    boundary = evaluate_claim_boundary(_fresh_index_context(), result_count=_result_count_for_claim(payload), chain_gate=gate)
    assert boundary["negative_claim_allowed"] is False
    assert boundary["evidence_level"] == "AMBIGUOUS"


# ---------------------------------------------------------------------------
# Unit: gate reasons flow into claim boundary
# ---------------------------------------------------------------------------


def _fresh_index_context() -> dict:
    return {
        "generation": "gen-1",
        "freshness": "FRESH",
        "coverage": {
            "scope_kind": "workspace",
            "requested_files": 10,
            "indexed_files": 10,
            "partial_files": 0,
            "skipped_files": 0,
            "failed_files": 0,
            "unknown_files": 0,
            "relevant_unsupported": 0,
            "irrelevant_excluded": 0,
            "reasons": [],
            "truncated": False,
        },
        "query_budget": {"depth": 3, "nodes": 80, "edges": 120, "timed_out": False, "truncated": False},
    }


def test_matched_anchor_and_full_scope_keep_verified_negative():
    """明确类名 + 正确锚点 + 完整分片 + 空边：允许 VERIFIED_NEGATIVE。"""
    gate = evaluate_claim_boundary(
        _fresh_index_context(),
        result_count=0,
        chain_gate={"anchor_status": "matched", "scope_incomplete": False},
    )
    assert gate["negative_claim_allowed"] is True
    assert gate["evidence_level"] == "VERIFIED_NEGATIVE"


def test_mismatch_anchor_forces_ambiguous():
    """明确类名 + 错误锚点：AMBIGUOUS + anchor_mismatch，禁止负向结论。"""
    gate = evaluate_claim_boundary(
        _fresh_index_context(),
        result_count=0,
        chain_gate={"anchor_status": "mismatch", "scope_incomplete": False},
    )
    assert gate["negative_claim_allowed"] is False
    assert "anchor_mismatch" in gate["reason_codes"]
    assert gate["evidence_level"] == "AMBIGUOUS"


def test_missing_anchor_forces_ambiguous():
    gate = evaluate_claim_boundary(
        _fresh_index_context(),
        result_count=0,
        chain_gate={"anchor_status": "missing", "scope_incomplete": False},
    )
    assert gate["negative_claim_allowed"] is False
    assert "anchor_mismatch" in gate["reason_codes"]


def test_incomplete_scope_forces_ambiguous():
    """正确锚点 + 漏掉 anchor 项目的分片：AMBIGUOUS + scope_incomplete。"""
    gate = evaluate_claim_boundary(
        _fresh_index_context(),
        result_count=0,
        chain_gate={"anchor_status": "matched", "scope_incomplete": True},
    )
    assert gate["negative_claim_allowed"] is False
    assert "scope_incomplete" in gate["reason_codes"]
    assert gate["evidence_level"] == "AMBIGUOUS"


def test_positive_result_not_affected_by_chain_gate():
    gate = evaluate_claim_boundary(
        _fresh_index_context(),
        result_count=3,
        chain_gate={"anchor_status": "mismatch", "scope_incomplete": True},
    )
    assert gate["evidence_level"] == "EXTRACTED"


def test_gate_reasons_helper_maps_statuses():
    assert gate_reasons_from_chain({"anchor_status": "matched", "scope_incomplete": False}) == []
    assert set(gate_reasons_from_chain({"anchor_status": "mismatch", "scope_incomplete": False})) == {"anchor_mismatch"}
    assert set(gate_reasons_from_chain({"anchor_status": "missing", "scope_incomplete": True})) == {"anchor_mismatch", "scope_incomplete"}
    assert gate_reasons_from_chain(None) == []


# ---------------------------------------------------------------------------
# Unit: empty-chain fallback action
# ---------------------------------------------------------------------------


def test_empty_chain_fallback_names_bounded_next_queries():
    fallback = build_empty_chain_fallback("ArticleMoveService", direction="callers")
    assert fallback["chain_empty"] is True
    actions = fallback["actions"]
    assert actions, "empty chain must suggest a fallback action"
    modes = [action["mode"] for action in actions]
    assert "symbol" in modes
    assert "code" in modes


def test_empty_chain_fallback_carries_anchor_status():
    fallback = build_empty_chain_fallback(
        "NoSuchClassXYZ",
        direction="callers",
        anchor_validation={"status": "mismatch", "reason": "no exact class match"},
    )
    assert fallback["anchor_status"] == "mismatch"
