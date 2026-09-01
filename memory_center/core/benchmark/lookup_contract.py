"""Deterministic behavior-contract replay for the public hybrid lookup envelope."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable

import yaml

SCHEMA_VERSION = 1


def load_lookup_contract_cases(path: str | Path) -> list[dict[str, Any]]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict) or raw.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("lookup contract cases require schema_version=1")
    cases = raw.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("lookup contract cases require non-empty cases")
    normalized: list[dict[str, Any]] = []
    ids: set[str] = set()
    for item in cases:
        if not isinstance(item, dict):
            raise ValueError("lookup contract case must be an object")
        case_id, query = str(item.get("case_id", "")).strip(), str(item.get("query", "")).strip()
        if not case_id or not query or case_id in ids:
            raise ValueError("lookup contract case_id/query must be unique and non-empty")
        ids.add(case_id)
        normalized.append({"case_id": case_id, "query": query, "project": str(item.get("project", "")).strip(), "limit": int(item.get("limit", 10) or 10)})
    return normalized


def normalize_lookup_contract(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep stable, non-path-bearing response semantics for regression comparison."""
    results = []
    for item in (payload.get("results", []) or [])[:10]:
        node = item.get("node", {}) if isinstance(item, dict) else {}
        results.append({"id": str(node.get("id", "")), "type": str(node.get("type", "")), "project": str(node.get("project", ""))})
    contracts = payload.get("contracts", {}) if isinstance(payload.get("contracts"), dict) else {}
    steps = payload.get("agent_next_steps", []) or []
    return {
        "result_ids": results,
        "project_scope": {key: str((payload.get("project_scope", {}) or {}).get(key, "")) for key in ("requested", "effective", "source")},
        "intent": str((payload.get("intent_analysis", {}) or {}).get("primary_intent", "")),
        "contract_counts": {key: len(value) for key, value in contracts.items() if isinstance(value, list)},
        "contract_routing": {key: str(value) for key, value in (payload.get("contract_routing", {}) or {}).items() if key in {"mode", "intent", "evidence_count"}},
        "knowledge_state": str((payload.get("knowledge_state", {}) or {}).get("state", "")),
        "guidance_actions": [str(step.get("action", "")) for step in steps if isinstance(step, dict)][:8],
        "served_dedup": bool((payload.get("served_dedup", {}) or {}).get("applied", False)),
    }


def evaluate_lookup_contract(
    workspace_file: str | Path, cases_file: str | Path, *, baseline_file: str | Path | None = None,
    runner: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    cases = load_lookup_contract_cases(cases_file)
    if runner is None:
        from memory_center.core.orchestrator.query import memory_query_hybrid

        runner = lambda case: memory_query_hybrid(workspace_file, case["query"], limit=case["limit"], project=case["project"])
    current = {case["case_id"]: normalize_lookup_contract(runner(case)) for case in cases}
    baseline = _load_baseline(baseline_file) if baseline_file else None
    changed = []
    if baseline:
        expected = baseline.get("contracts", {})
        changed = [case_id for case_id, contract in current.items() if expected.get(case_id) != contract]
    return {
        "schema_version": SCHEMA_VERSION, "case_count": len(cases), "contracts": current,
        "baseline_status": "compared" if baseline else "no_baseline", "changed_case_ids": changed,
        "status": "block" if changed else "pass", "next_action": "save an approved baseline explicitly" if not baseline else "review changed_case_ids",
    }


def save_lookup_contract_baseline(result: dict[str, Any], path: str | Path, *, label: str = "current") -> dict[str, Any]:
    payload = {"schema_version": SCHEMA_VERSION, "label": label, "contracts": result.get("contracts", {})}
    payload["sha256"] = hashlib.sha256(json.dumps(payload["contracts"], ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"saved": True, "baseline_file": str(target), "sha256": payload["sha256"]}


def _load_baseline(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION or not isinstance(value.get("contracts"), dict):
        raise ValueError("lookup contract baseline must be schema_version=1")
    return value


__all__ = ["evaluate_lookup_contract", "load_lookup_contract_cases", "normalize_lookup_contract", "save_lookup_contract_baseline"]
