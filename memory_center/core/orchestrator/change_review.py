"""Unified graph-aware change review plan."""
from __future__ import annotations

import copy
import threading
import time
from pathlib import Path
from typing import Any

from memory_center.core.freshness.targeted_refresh import MAX_REFRESH_FILES, refresh_explicit_paths
from memory_center.core.indexing.control_plane import index_control_status
from memory_center.core.orchestrator.budget_guard import InvocationBudget, invocation_fingerprint
from memory_center.core.orchestrator.impact import memory_detect_changes
from memory_center.core.storage.runtime import RuntimeStore
from memory_center.core.storage.workspace import WorkspaceStore

_CACHE_TTL_SECONDS = 15.0
_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_CACHE_LOCK = threading.Lock()


def build_change_review_plan(
    workspace_file: str | Path,
    *,
    scope: str = "all",
    files: list[str] | None = None,
    detail_level: str = "minimal",
    refresh: bool = True,
    max_depth: int = 3,
    max_impacts: int = 120,
) -> dict[str, Any]:
    """Refresh, analyze, and package one bounded change review workflow."""
    detail = detail_level if detail_level in {"minimal", "standard", "deep"} else "minimal"
    budget = InvocationBudget(
        max_stages=8,
        max_output_tokens={"minimal": 900, "standard": 2400, "deep": 6000}[detail],
        max_elapsed_ms=30_000.0 if refresh else 10_000.0,
    )
    store = WorkspaceStore(workspace_file)
    budget.enter("detect_changes")
    detected = memory_detect_changes(workspace_file, scope=scope)
    changed = list(dict.fromkeys(files or detected.get("changed_files", []) or []))[:200]
    deleted = set(detected.get("deleted_files", []) or [])
    generation_before = index_control_status(store)
    source_signature = _source_signature(store, changed)
    fingerprint = invocation_fingerprint(
        {
            "workspace": str(store.workspace_file),
            "scope": scope,
            "files": changed,
            "source_signature": source_signature,
            "detail": detail,
            "refresh": refresh,
            "max_depth": max_depth,
        }
    )
    cached = _cache_get(
        fingerprint,
        generation=str(generation_before.get("active_generation", "") or ""),
    )
    if cached is not None:
        cached["cache"] = {"status": "hit", "ttl_seconds": _CACHE_TTL_SECONDS}
        return cached

    refresh_result: dict[str, Any] = {
        "refreshed": False,
        "mode": "disabled" if not refresh else "not_needed",
        "files": [],
        "truncated": False,
    }
    refreshable = [path for path in changed if path not in deleted]
    if refresh and refreshable and budget.enter("scoped_refresh"):
        refresh_result = refresh_explicit_paths(
            workspace_file, refreshable, limit=MAX_REFRESH_FILES
        )
        if refresh_result.get("truncated"):
            budget.stopped_reason = "refresh_scope_truncated"

    budget.enter("locate_changed_nodes")
    with RuntimeStore(store.graph_db_path) as graph:
        changed_nodes = graph.nodes_for_files(changed, limit=160)
        seed_nodes = [node for node in changed_nodes if node.get("type") != "File"][:40]
        if not seed_nodes:
            seed_nodes = changed_nodes[:20]
        budget.enter("weighted_impact")
        impacts_by_node: dict[str, dict[str, Any]] = {}
        for seed in seed_nodes:
            for impact in graph.weighted_impact_paths(
                str(seed.get("id", "")),
                direction="upstream",
                max_depth=min(max(1, max_depth), 5),
                limit=min(40, max_impacts),
            ):
                endpoint = _impact_endpoint(impact, str(seed.get("id", "")))
                key = str(endpoint.get("id", "") or impact.get("id", ""))
                previous = impacts_by_node.get(key)
                if previous is None or float(impact.get("impact_score", 0.0)) > float(previous.get("impact_score", 0.0)):
                    impacts_by_node[key] = {**impact, "seed": _compact_node(seed)}
            if len(impacts_by_node) >= max_impacts:
                break

    impacts = sorted(
        impacts_by_node.values(),
        key=lambda row: (-float(row.get("impact_score", 0.0)), int(row.get("depth", 0)), str(row.get("id", ""))),
    )[:max_impacts]
    budget.enter("risk_and_test_gaps")
    contract_types = {
        "FeignClient", "FeignMethod", "Endpoint", "MQTopic", "MQConsumer",
        "ConfigKey", "DTO", "Field", "DataResource",
    }
    contract_nodes = [node for node in changed_nodes if str(node.get("type", "")) in contract_types]
    impacted_files = _aggregate_impacted_files(impacts)
    test_files = {
        path
        for path in [*changed, *(row.get("file_path", "") for row in impacted_files)]
        if _is_test_path(str(path))
    }
    missing_tests = [
        {
            "node": _compact_node(node),
            "reason": "No changed or impacted test file was found in the bounded graph scope.",
            "evidence_level": "AMBIGUOUS",
        }
        for node in seed_nodes
        if node.get("type") in {"Method", "Endpoint", "FeignMethod"} and not test_files
    ][:20]
    risk_score = min(
        100,
        len(contract_nodes) * 12
        + sum(8 for row in impacts if float(row.get("impact_score", 0.0)) >= 0.8)
        + min(24, len(impacted_files) * 2)
        + (15 if refresh_result.get("truncated") else 0),
    )
    risk_level = "high" if risk_score >= 55 else "medium" if risk_score >= 20 else "low"
    budget.enter("actions")
    actions = _review_actions(
        changed=changed,
        contract_nodes=contract_nodes,
        missing_tests=missing_tests,
        refresh_result=refresh_result,
    )
    generation_after = index_control_status(store)
    result = {
        "schema_version": 1,
        "workflow": "change_review_plan",
        "status": "ready" if changed else "no_changes",
        "knowledge_state": "FOUND" if changed_nodes else "NOT_FOUND" if changed else "UNKNOWN",
        "scope_checked": {
            "change_scope": scope,
            "changed_file_count": len(changed),
            "deleted_file_count": len(deleted),
            "generation_before": generation_before.get("active_generation", ""),
            "generation_after": generation_after.get("active_generation", ""),
            "impact_mode": "bounded_weighted_best_path_v1",
        },
        "refresh": refresh_result,
        "summary": {
            "risk_level": risk_level,
            "risk_score": risk_score,
            "changed_file_count": len(changed),
            "changed_node_count": len(changed_nodes),
            "impacted_file_count": len(impacted_files),
            "contract_change_count": len(contract_nodes),
            "missing_test_count": len(missing_tests),
        },
        "changed_files": changed,
        "changed_nodes": [_compact_node(node) for node in changed_nodes],
        "impacted_files": impacted_files,
        "impacts": impacts,
        "contract_changes": [_compact_node(node) for node in contract_nodes],
        "missing_tests": missing_tests,
        "actions": actions,
        "stop_condition": (
            "Review remaining changed files in another bounded batch."
            if refresh_result.get("truncated")
            else "Stop when every blocking action has a passed validation receipt."
        ),
        "fallback": "Keep the last published generation and mark conclusions STALE or UNKNOWN if scoped refresh fails.",
        "invocation_budget": budget.contract(fingerprint=fingerprint, detail_level=detail),
        "cache": {"status": "miss", "ttl_seconds": _CACHE_TTL_SECONDS},
    }
    result = _apply_detail_level(result, detail)
    # Additive validation plan (subproject 2): minimal falsifiable, executable
    # verification design. Never runs commands; MQ without destination stays
    # insufficient_evidence; a contract breaking change forces blocked.
    try:
        contract_diff = store.read_json_prefer_backend("contract-diff.json", {}) or {}
        contract_block = int(contract_diff.get("breaking_count", 0) or 0) > 0
        result["validation_plan"] = _build_validation_plan(
            list(changed),
            contract_nodes,
            sorted(deleted),
            contract_block,
        )
    except Exception:
        result["validation_plan"] = {"status": "blocked", "minimum_actions": [], "critical_hypotheses": [], "continue_if": [], "stop_if": ["validation-plan-unavailable"], "rollback": [], "evidence_required": [], "coverage": {"risk_categories": [], "uncovered_risks": ["validation_plan_unavailable"]}}
    # Additive Phase A contract: index_context + claim_boundary so consumers
    # know which generation the review ran against and whether an empty
    # impact result may be read as "no impact".
    try:
        from memory_center.core.freshness.contract import attach_contract

        refresh_truncated = bool(refresh_result.get("truncated"))
        attach_contract(
            result,
            workspace_file,
            request_tier="deep" if detail == "deep" else ("standard" if detail == "standard" else "fast"),
            query_budget={"depth": max_depth, "nodes": len(result.get("impacts", []) or []), "edges": 0, "timed_out": False},
            # A truncated refresh means not every changed file was analyzed,
            # so an empty impact list must not count as a covered negative.
            result_count=0 if refresh_truncated else len(impacts),
        )
        if refresh_truncated:
            coverage = result["index_context"]["coverage"]
            coverage["truncated"] = True
            reason_codes = result["claim_boundary"]["reason_codes"]
            if "query_truncated" not in reason_codes:
                reason_codes.append("query_truncated")
            result["claim_boundary"]["negative_claim_allowed"] = False
    except Exception:
        pass
    _cache_put(fingerprint, result)
    return result


def _impact_endpoint(impact: dict[str, Any], seed_id: str) -> dict[str, Any]:
    path_ids = list((impact.get("best_path", {}) or {}).get("node_ids", []) or [])
    endpoint_id = str(path_ids[-1]) if path_ids else ""
    if impact.get("target_id") == endpoint_id or (not endpoint_id and impact.get("source_id") == seed_id):
        return {"id": impact.get("target_id", ""), **(impact.get("target", {}) or {})}
    return {"id": impact.get("source_id", ""), **(impact.get("source", {}) or {})}


def _compact_node(node: dict[str, Any]) -> dict[str, Any]:
    return {key: node.get(key, "") for key in ("id", "type", "name", "project", "file_path", "line")}


# Risk category -> minimal falsifiable validation plan (subproject 2).
# Never executes commands; returns the minimum evidence a verifier must obtain.
_RISK_VALIDATION: dict[str, dict[str, Any]] = {
    "dto": {
        "risk_category": "dto_contract",
        "minimum_actions": ["serialization/deserialization compatibility check", "consumer contract check"],
        "evidence_required": ["contract-gate", "consumer-validation"],
    },
    "feign": {
        "risk_category": "feign_contract",
        "minimum_actions": ["request/response compatibility", "caller + endpoint contract check"],
        "evidence_required": ["contract", "affected-consumer-evidence"],
    },
    "http": {
        "risk_category": "http_route",
        "minimum_actions": ["route mapping check", "status-code check", "caller path check"],
        "evidence_required": ["route-contract"],
    },
    "mq": {
        "risk_category": "mq_producer_consumer",
        "minimum_actions": ["topic/message-type static evidence"],
        "evidence_required": ["extracted-graph", "insufficient-evidence-if-no-destination"],
    },
    "config": {
        "risk_category": "config_key",
        "minimum_actions": ["config read-point check", "default-value check", "migration-strategy check"],
        "evidence_required": ["config-usage-evidence"],
    },
    "method": {
        "risk_category": "private_method",
        "minimum_actions": ["unit test or direct call-chain verification"],
        "evidence_required": ["local-call-evidence"],
    },
    "delete": {
        "risk_category": "delete_or_move",
        "minimum_actions": ["old node/reference cleanup check", "test-association check"],
        "evidence_required": ["graph-change-evidence"],
    },
}

_CONTRACT_NODE_TYPES_FOR_RISK = ("DTO", "FeignClient", "Endpoint", "MQProducer", "MQConsumer", "ConfigKey")


def _risk_for_changed(changed: list[str], contract_nodes: list[dict[str, Any]], deleted: list[str]) -> list[dict[str, Any]]:
    """Classify changed files into risk categories using graph evidence only."""
    risks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for node in contract_nodes:
        ntype = str(node.get("type", ""))
        for risk_type, mapping in _RISK_VALIDATION.items():
            if risk_type == "mq" and ntype in ("MQProducer", "MQConsumer"):
                pass
            elif risk_type == "dto" and ntype == "DTO":
                pass
            elif risk_type == "feign" and ntype == "FeignClient":
                pass
            elif risk_type == "http" and ntype == "Endpoint":
                pass
            elif risk_type == "config" and ntype == "ConfigKey":
                pass
            else:
                continue
            key = f"{risk_type}:{node.get('id')}"
            if key in seen:
                break
            seen.add(key)
            risks.append({"category": risk_type, "node_type": ntype, **mapping})
            break
    if not risks and changed:
        # No contract node evidence: classify by file shape when present, else
        # treat as private/local change (never fabricate a contract risk).
        risks.append({"category": "method", "node_type": "Method", **_RISK_VALIDATION["method"]})
    if deleted:
        risks.append({"category": "delete", "node_type": "File", **_RISK_VALIDATION["delete"]})
    return risks


def _build_validation_plan(changed: list[str], contract_nodes: list[dict[str, Any]], deleted: list[str], contract_block: bool) -> dict[str, Any]:
    """Build the additive validation_plan for a change review (subproject 2).

    A plan is a suggestion, never a command. Without graph evidence no test
    scope is claimed; MQ without a destination stays insufficient_evidence;
    a contract block forces status=blocked; high-risk changes always carry a
    stop_if and rollback.
    """
    if not changed:
        return {"status": "not_applicable", "minimum_actions": [], "critical_hypotheses": [], "continue_if": [], "stop_if": [], "rollback": [], "evidence_required": [], "coverage": {"risk_categories": [], "uncovered_risks": []}}
    risks = _risk_for_changed(changed, contract_nodes, deleted)
    hypotheses = []
    for risk in risks:
        category = risk["category"]
        hyp_id = f"{category}-compatible"
        hypotheses.append({
            "id": hyp_id,
            "claim": f"{category} change does not break indexed consumers/callers",
            "continue_if": "contract gate pass and affected consumer checks pass",
            "stop_if": "contract block or missing required consumer evidence",
            "rollback": "restore compatible shape or use additive migration",
            "evidence_required": risk.get("evidence_required", []),
        })
    status = "blocked" if contract_block else "ready"
    if any(r["category"] == "mq" for r in risks):
        # MQ without provable destination is an evidence gap, not a ready plan.
        status = "insufficient_evidence" if status != "blocked" else status
    return {
        "status": status,
        "minimum_actions": list({a for r in risks for a in r.get("minimum_actions", [])}),
        "critical_hypotheses": hypotheses,
        "continue_if": ["contract gate pass", "affected consumer checks pass"],
        "stop_if": ["contract block", "missing required consumer evidence"] if any(r["category"] in ("dto", "feign", "http", "mq") for r in risks) else [],
        "rollback": ["restore compatible shape or use additive migration"],
        "evidence_required": list({e for r in risks for e in r.get("evidence_required", [])}),
        "coverage": {
            "risk_categories": [r["category"] for r in risks],
            "uncovered_risks": [] if status != "insufficient_evidence" else ["mq_destination_not_provable"],
        },
    }


def _aggregate_impacted_files(impacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best: dict[str, dict[str, Any]] = {}
    for impact in impacts:
        for endpoint in (impact.get("source", {}) or {}, impact.get("target", {}) or {}):
            path = str(endpoint.get("file_path", "") or "")
            if not path:
                continue
            score = float(impact.get("impact_score", 0.0) or 0.0)
            if path not in best or score > float(best[path]["impact_score"]):
                best[path] = {
                    "file_path": path,
                    "project": endpoint.get("project", ""),
                    "impact_score": round(score, 6),
                    "evidence_path": impact.get("best_path", {}),
                }
    return sorted(best.values(), key=lambda row: (-float(row["impact_score"]), row["file_path"]))


def _is_test_path(path: str) -> bool:
    lowered = path.lower()
    return any(token in lowered for token in ("/test/", "/tests/", "test.java", "tests.java", "spec."))


def _review_actions(
    *,
    changed: list[str],
    contract_nodes: list[dict[str, Any]],
    missing_tests: list[dict[str, Any]],
    refresh_result: dict[str, Any],
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    if refresh_result.get("truncated"):
        actions.append({"id": "review-next-refresh-batch", "priority": "blocking", "action": "review_next_batch", "reason": "Scoped refresh limit reached.", "requires_confirmation": False})
    if contract_nodes:
        actions.append({"id": "verify-contract-compatibility", "priority": "blocking", "action": "verify_contracts", "reason": "Public contract nodes changed.", "requires_confirmation": False})
    if missing_tests:
        actions.append({"id": "verify-test-coverage", "priority": "high", "action": "run_registered_tests", "reason": "High-impact changed nodes have no test evidence in the bounded graph scope.", "requires_confirmation": True})
    if changed:
        actions.append({"id": "record-validation-receipt", "priority": "required", "action": "record_validation", "reason": "Close the review with executor or manual verification evidence.", "requires_confirmation": True})
    return actions


def _apply_detail_level(result: dict[str, Any], detail: str) -> dict[str, Any]:
    if detail == "deep":
        return result
    compact = copy.deepcopy(result)
    if detail == "minimal":
        compact["changed_files"] = compact["changed_files"][:12]
        compact["changed_nodes"] = compact["changed_nodes"][:12]
        compact["impacted_files"] = compact["impacted_files"][:12]
        compact["impacts"] = compact["impacts"][:8]
        compact["contract_changes"] = compact["contract_changes"][:8]
        compact["missing_tests"] = compact["missing_tests"][:8]
    else:
        compact["changed_nodes"] = compact["changed_nodes"][:50]
        compact["impacted_files"] = compact["impacted_files"][:50]
        compact["impacts"] = compact["impacts"][:40]
    compact["truncated_sections"] = [
        name
        for name, original in (
            ("changed_nodes", result["changed_nodes"]),
            ("impacted_files", result["impacted_files"]),
            ("impacts", result["impacts"]),
            ("contract_changes", result["contract_changes"]),
            ("missing_tests", result["missing_tests"]),
        )
        if len(compact[name]) < len(original)
    ]
    return compact


def _source_signature(store: WorkspaceStore, paths: list[str]) -> list[tuple[str, int, int]]:
    by_path = {
        str(row.get("path", "")): row
        for row in store.read_json_prefer_backend("file-index.json", [])
        if isinstance(row, dict)
    }
    signature: list[tuple[str, int, int]] = []
    for path in paths[:MAX_REFRESH_FILES]:
        absolute = str((by_path.get(path, {}) or {}).get("abs_path", "") or "")
        try:
            stat = Path(absolute).stat() if absolute else None
        except OSError:
            stat = None
        signature.append((path, int(stat.st_mtime_ns) if stat else -1, int(stat.st_size) if stat else -1))
    return signature


def _cache_get(key: str, *, generation: str) -> dict[str, Any] | None:
    now = time.monotonic()
    with _CACHE_LOCK:
        row = _CACHE.get(key)
        if row is None or now - row[0] > _CACHE_TTL_SECONDS:
            _CACHE.pop(key, None)
            return None
        cached_generation = str(
            ((row[1].get("scope_checked", {}) or {}).get("generation_after", "")) or ""
        )
        if cached_generation != generation:
            _CACHE.pop(key, None)
            return None
        return copy.deepcopy(row[1])


def _cache_put(key: str, value: dict[str, Any]) -> None:
    with _CACHE_LOCK:
        if len(_CACHE) >= 128:
            oldest = min(_CACHE, key=lambda item: _CACHE[item][0])
            _CACHE.pop(oldest, None)
        _CACHE[key] = (time.monotonic(), copy.deepcopy(value))
