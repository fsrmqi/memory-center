"""Lookup behavior contract replay remains deterministic and approval-gated."""
from __future__ import annotations

from pathlib import Path

from memory_center.core.benchmark.lookup_contract import evaluate_lookup_contract, evaluate_lookup_facade_contract, save_lookup_contract_baseline, save_lookup_facade_baseline, summarize_lookup_contract_coverage


def _write_cases(path: Path) -> None:
    path.write_text("schema_version: 1\ncases:\n  - case_id: symbol\n    query: ArticleService\n    project: demo\n", encoding="utf-8")


def _runner(case):
    return {
        "results": [{"node": {"id": "Class:ArticleService", "type": "Class", "project": case["project"]}}],
        "project_scope": {"requested": case["project"], "effective": case["project"], "source": "explicit"},
        "intent_analysis": {"primary_intent": "class"}, "contracts": {},
        "knowledge_state": {"state": "FOUND"}, "agent_next_steps": [{"action": "read_target"}],
        "served_dedup": {"applied": False},
    }


def test_lookup_contract_baseline_requires_explicit_approval(tmp_path: Path) -> None:
    cases, baseline = tmp_path / "cases.yaml", tmp_path / "baseline.json"
    _write_cases(cases)
    current = evaluate_lookup_contract("workspace.yaml", cases, runner=_runner)
    assert current["baseline_status"] == "no_baseline"
    assert current["status"] == "pass"
    save_lookup_contract_baseline(current, baseline, label="approved")
    compared = evaluate_lookup_contract("workspace.yaml", cases, baseline_file=baseline, runner=_runner)
    assert compared["baseline_status"] == "compared"
    assert compared["status"] == "pass"


def test_lookup_contract_reports_semantic_response_drift(tmp_path: Path) -> None:
    cases, baseline = tmp_path / "cases.yaml", tmp_path / "baseline.json"
    _write_cases(cases)
    approved = evaluate_lookup_contract("workspace.yaml", cases, runner=_runner)
    save_lookup_contract_baseline(approved, baseline)

    def changed(case):
        payload = _runner(case)
        payload["intent_analysis"] = {"primary_intent": "feign"}
        return payload

    result = evaluate_lookup_contract("workspace.yaml", cases, baseline_file=baseline, runner=changed)
    assert result["status"] == "block"
    assert result["changed_case_ids"] == ["symbol"]


def test_facade_contract_unwraps_wrapper_and_detects_drift() -> None:
    case = {"case_id": "symbol", "project": "demo"}
    payload = _runner(case)
    equal = evaluate_lookup_facade_contract([case], {"http": lambda _: {"result": payload}, "mcp": lambda _: payload})
    assert equal["status"] == "pass"
    drift = evaluate_lookup_facade_contract([case], {"http": lambda _: {"result": payload}, "mcp": lambda _: {**payload, "served_dedup": {"applied": True}}})
    assert drift["status"] == "block"


def test_facade_contract_only_injects_fresh_session_for_sequence() -> None:
    seen: list[str] = []
    def runner(case):
        seen.append(str(case.get("session_id", "")))
        return _runner(case)
    evaluate_lookup_facade_contract([{"case_id": "one", "project": "demo", "session_steps": 1}], {"cli": runner})
    assert seen == [""]
    seen.clear()
    evaluate_lookup_facade_contract([{"case_id": "two", "project": "demo", "session_steps": 2}], {"cli": runner})
    assert len(seen) == 2 and seen[0] and seen[0] == seen[1]


def test_facade_baseline_is_hashed_and_atomic_shape(tmp_path: Path) -> None:
    path = tmp_path / "facade.json"
    saved = save_lookup_facade_baseline({"snapshots": {"case": {"cli": {}}}}, path)
    assert saved["sha256"]
    assert '"sha256"' in path.read_text(encoding="utf-8")


def test_lookup_contract_coverage_never_returns_query_text(tmp_path: Path) -> None:
    cases = tmp_path / "cases.yaml"; _write_cases(cases)
    coverage = summarize_lookup_contract_coverage(cases)
    assert coverage["case_count"] == 1
    assert "ArticleService" not in str(coverage)
