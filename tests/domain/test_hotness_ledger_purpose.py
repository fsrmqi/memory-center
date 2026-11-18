"""hotness / served_ledger / purpose presets 测试(设计参考 OpenViking
memory_lifecycle / context_assembler ledger / PURPOSE_PRESETS)。

覆盖:
- hotness:频率 sigmoid × 半衰期衰减的纯函数行为;case 命中统计;排序
  (有命中按热度排前,无命中保持原序——微秒级创建时间差不引起重排);
- served_ledger:记录/读取/有界/按会话隔离/失败降级;payload 提取;
- query 降权:session_id 提供时已服务文件被标记降级,无 session 不生效;
- purpose presets:意图归并确定性 + 预算倾斜方向与基线对比。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from memory_center.core.foundation.hotness import (
    case_last_hit,
    hotness_score,
    rank_cases_by_hotness,
)
from memory_center.core.orchestrator.query import memory_query_hybrid
from memory_center.core.orchestrator.resume import _resume_related_cases
from memory_center.core.retrieval.policy import classify_purpose, select_retrieval_policy
from memory_center.core.retrieval.policy_rules import RETRIEVAL_POLICY_RULES_FILE, load_purpose_deltas
from memory_center.core.storage.served_ledger import (
    MAX_SERVED_PATHS,
    extract_file_paths_from_payload,
    paths_refer_to_same_file,
    record_served_files,
    served_files,
)
from memory_center.core.storage.workspace import WorkspaceStore

NOW = datetime(2026, 9, 1, tzinfo=timezone.utc)


# ---------- hotness ----------


def test_hotness_score_frequency_and_decay() -> None:
    assert hotness_score(0, None, now=NOW) == 0.0
    assert hotness_score(0, NOW, now=NOW) == 0.0
    # 新鲜 + 命中越多越热
    assert hotness_score(10, NOW, now=NOW) > hotness_score(1, NOW, now=NOW)
    # 半衰期:7 天前同样本分数减半
    week_ago = hotness_score(10, NOW - timedelta(days=7), now=NOW)
    fresh = hotness_score(10, NOW, now=NOW)
    assert abs(week_ago - fresh / 2) < 1e-9
    # 长期未命中的样本趋近 0
    assert hotness_score(10, NOW - timedelta(days=60), now=NOW) < 0.01
    # 无效时间字符串 → 0
    assert hotness_score(5, "not-a-date", now=NOW) == 0.0


def test_case_last_hit_counts_guidance_events() -> None:
    events = [
        {"event_type": "agent_guidance", "created_at": "2026-08-31T00:00:00+00:00", "payload": {"query": "修复 Feign 兼容 hot"}},
        {"event_type": "agent_guidance", "created_at": "2026-08-30T00:00:00+00:00", "payload": {"query": "another hot query"}},
        {"event_type": "tool_call", "created_at": "2026-08-29T00:00:00+00:00", "payload": {"query": "hot"}},
    ]
    hits, last_at = case_last_hit(events, "hot")
    assert hits == 2  # tool_call 不计入
    assert last_at == "2026-08-31T00:00:00+00:00"
    assert case_last_hit(events, "no-match") == (0, "")
    assert case_last_hit(events, "") == (0, "")


def test_rank_cases_by_hotness_orders_hit_first_and_keeps_zero_hit_order() -> None:
    events = [
        {"event_type": "agent_guidance", "created_at": "2026-08-31T00:00:00+00:00", "payload": {"query": "hot case"}},
        {"event_type": "agent_guidance", "created_at": "2026-08-20T00:00:00+00:00", "payload": {"query": "warm case"}},
    ]
    cases = [
        {"task": "cold case", "valid_from": "2026-08-25T00:00:00+00:00"},
        {"task": "warm case", "valid_from": "2026-08-01T00:00:00+00:00"},
        {"task": "hot case", "valid_from": "2026-06-01T00:00:00+00:00"},
    ]
    ranked = rank_cases_by_hotness(cases, events, now=NOW)
    assert [c["task"] for c in ranked] == ["hot case", "warm case", "cold case"]
    assert ranked[0]["hit_count"] == 1
    # 无命中 case 不因 valid_from 更新而抢占(保持原序,hotness=0)
    assert ranked[2]["hotness"] == 0.0


def test_rank_cases_by_hotness_zero_hits_preserves_original_order() -> None:
    cases = [
        {"task": "first", "valid_from": "2026-08-01T00:00:00+00:00"},
        {"task": "second", "valid_from": "2026-08-02T00:00:00+00:00"},
        {"task": "third", "valid_from": "2026-08-03T00:00:00+00:00"},
    ]
    ranked = rank_cases_by_hotness(cases, [], now=NOW)
    assert [c["task"] for c in ranked] == ["first", "second", "third"]


def test_resume_exact_keeps_highest_hotness_within_limit(demo_workspace: Path) -> None:
    store = WorkspaceStore(demo_workspace)
    for task in ("target cold", "target warm", "target hot"):
        store.append_jsonl("cross-service-task-memory.jsonl", {"task": task, "projects": ["p"]})
    for _ in range(3):
        store.append_jsonl("session-events.jsonl", {"event_type": "agent_guidance", "payload": {"query": "target hot"}})
    for _ in range(2):
        store.append_jsonl("session-events.jsonl", {"event_type": "agent_guidance", "payload": {"query": "target warm"}})

    cases, mode = _resume_related_cases(store, "target", limit=2)
    assert mode == "exact"
    assert [case["task"] for case in cases] == ["target hot", "target warm"]


# ---------- served_ledger ----------


def _payload_with_paths() -> dict:
    return {
        "read_targets": [{"path": "a/src/Foo.java"}, {"file_path": "b/src/Bar.java"}],
        "result": {
            "best_match": {"file_path": "a/src/Foo.java"},
            "matches": [{"node": {"file_path": "c/Baz.java"}}],
        },
        "primary_chain": {"steps": [{"file_path": "d/Chain.java"}]},
    }


def test_extract_file_paths_dedupes_and_bounds() -> None:
    paths = extract_file_paths_from_payload(_payload_with_paths())
    assert paths == ["a/src/Foo.java", "b/src/Bar.java", "c/Baz.java", "d/Chain.java"]
    assert extract_file_paths_from_payload({}) == []


def test_served_path_matching_requires_more_than_a_basename() -> None:
    assert paths_refer_to_same_file("service-a/src/UserService.java", "/repo/service-a/src/UserService.java")
    assert not paths_refer_to_same_file("service-a/src/UserService.java", "service-b/src/UserService.java")
    assert not paths_refer_to_same_file("service-a/src/UserService.java", "/repo/service-b/src/UserService.java")


def test_ledger_records_and_isolates_sessions(demo_workspace: Path) -> None:
    workspace = str(demo_workspace)
    size = record_served_files(workspace, "s1", ["a.java", "b.java"], tier="standard")
    assert size == 2
    record_served_files(workspace, "s1", ["b.java", "c.java"], tier="standard")
    assert served_files(workspace, "s1") == {"a.java", "b.java", "c.java"}
    assert served_files(workspace, "s2") == set()
    assert record_served_files(workspace, "", ["a.java"]) == 0
    assert record_served_files(workspace, "s1", []) == 3


def test_ledger_is_bounded() -> None:
    import tempfile

    from tests.fixtures import copy_demo_workspace

    workspace = str(copy_demo_workspace(Path(tempfile.mkdtemp())))
    overflow = [f"dir/file-{i}.java" for i in range(MAX_SERVED_PATHS + 50)]
    size = record_served_files(workspace, "bounded", overflow)
    assert size == MAX_SERVED_PATHS
    served = served_files(workspace, "bounded")
    assert "dir/file-0.java" not in served  # 最旧的被丢弃
    assert f"dir/file-{MAX_SERVED_PATHS + 49}.java" in served


def test_ledger_survives_repository_reopen(demo_workspace: Path) -> None:
    workspace = str(demo_workspace)
    record_served_files(workspace, "persist", ["x.java"], tier="deep")
    assert served_files(workspace, "persist") == {"x.java"}


# ---------- query dedup ----------


def test_query_downweights_served_files_for_session(demo_workspace_indexed: Path) -> None:
    workspace = str(demo_workspace_indexed)
    query = "MoveArticleRequest"
    baseline = memory_query_hybrid(workspace, query, limit=5)
    top_path = str(baseline["results"][0]["node"].get("file_path", "") or "")
    assert top_path, "indexed demo must return results with file paths"

    record_served_files(workspace, "sess-dedup", [top_path], tier="standard")
    with_session = memory_query_hybrid(workspace, query, limit=5, session_id="sess-dedup")
    assert with_session["served_dedup"]["applied"] is True
    marked = [r for r in with_session["results"] if r.get("_served_before")]
    assert marked, "previously served file must be marked"
    assert all(r.get("score", 0) <= baseline["results"][0].get("score", 0) for r in marked)

    without_session = memory_query_hybrid(workspace, query, limit=5)
    assert without_session["served_dedup"]["applied"] is False
    assert not any(r.get("_served_before") for r in without_session["results"])


# ---------- purpose presets ----------


def test_classify_purpose_is_deterministic() -> None:
    assert classify_purpose({"primary_intent": "walkthrough", "is_full_chain": True}) == "full_chain"
    assert classify_purpose({"primary_intent": "feign"}) == "contract_change"
    assert classify_purpose({"primary_intent": "mq"}) == "contract_change"
    assert classify_purpose({"primary_intent": "method", "query": "fix bug in Foo"}) == "quick_fix"
    # 契约类优先于快速修复(契约安全 > 预算收窄)
    assert classify_purpose({"primary_intent": "feign", "query": "fix bug"}) == "contract_change"
    assert classify_purpose({"primary_intent": "class"}) == "general"
    assert classify_purpose({}) == "general"


def test_purpose_deltas_adjust_budgets_against_baseline() -> None:
    freshness = {"status": "fresh"}
    baseline = select_retrieval_policy({"primary_intent": "class"}, freshness, {})
    contract = select_retrieval_policy({"primary_intent": "feign"}, freshness, {})
    quick = select_retrieval_policy({"primary_intent": "method", "query": "fix bug"}, freshness, {})
    assert contract.candidate_limit > baseline.candidate_limit
    assert contract.evidence_budget > baseline.evidence_budget
    assert quick.candidate_limit < baseline.candidate_limit
    assert quick.evidence_budget < baseline.evidence_budget
    # purpose 字段随 to_dict 输出(additive)
    assert baseline.to_dict()["purpose"] == "general"
    assert contract.to_dict()["purpose"] == "contract_change"


def test_workspace_purpose_delta_override_is_bounded_and_additive(demo_workspace: Path) -> None:
    rules = WorkspaceStore(demo_workspace).rules_dir / RETRIEVAL_POLICY_RULES_FILE
    rules.write_text(
        "purpose_deltas:\n  contract_change:\n    candidate_limit: 9\n    unknown: 999\n",
        encoding="utf-8",
    )
    deltas = load_purpose_deltas(demo_workspace)
    assert deltas["contract_change"]["candidate_limit"] == 9
    assert "unknown" not in deltas["contract_change"]
