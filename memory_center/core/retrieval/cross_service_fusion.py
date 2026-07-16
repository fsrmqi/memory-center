"""Fuse global and service-shard evidence into generation-consistent conclusions."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from ..indexing.control_plane import index_control_status
from ..indexing.shards import load_contract_shard, load_topology_shard
from ..store import WorkspaceStore
from .cross_service import query_cross_service_shards, route_cross_service_shards


def fuse_cross_shard_result(
    workspace_file: str | Path,
    query: str,
    primary: dict[str, Any],
    route: dict[str, Any],
    shard_evidence: dict[str, Any],
) -> dict[str, Any]:
    store = WorkspaceStore(workspace_file)
    active = str(index_control_status(store).get("active_generation", "") or "")
    routed = str(route.get("generation", "") or "")
    consistent = bool(active and routed and active == routed)
    selected_projects = list(route.get("selected_projects", []) or [])
    normalized = _normalize_matches(primary, shard_evidence, selected_projects)
    contracts = load_contract_shard(store, active) if consistent else None
    topology = load_topology_shard(store, active) if consistent else None
    contract_summary = _contract_consistency(contracts or {}, topology or {}, selected_projects, query)
    strength = "fact" if consistent and normalized else "derived"
    confidence = 0.92 if consistent and normalized else 0.55 if normalized else 0.2
    conclusions = _conclusions(normalized, contract_summary, consistent)
    return {
        "generation": {"active": active, "routed": routed, "consistent": consistent, "status": "consistent" if consistent else "generation_mismatch"},
        "selected_projects": selected_projects,
        "normalized_matches": normalized[:30],
        "contract_consistency": contract_summary,
        "conclusions": conclusions,
        "semantic_strength": strength,
        "confidence": confidence,
        "next_actions": _next_actions(consistent, contract_summary),
    }


def evaluate_cross_shard_fusion(workspace_file: str | Path, cases: list[dict[str, Any]], *, tier: str = "standard") -> dict[str, Any]:
    """Golden-like quality gate for service selection and explainable conclusions."""
    samples = []
    for case in cases[:100]:
        query = str(case.get("query", "") or "").strip()
        if not query:
            continue
        started = time.perf_counter()
        route = route_cross_service_shards(workspace_file, query, tier=tier)
        evidence = query_cross_service_shards(workspace_file, query, route, limit=12)
        fused = fuse_cross_shard_result(workspace_file, query, {}, route, evidence)
        expected = {str(item) for item in case.get("expected_projects", []) if item}
        selected = set(route.get("selected_projects", []) or [])
        samples.append({
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            "selection_ok": expected.issubset(selected) if expected else bool(selected),
            "generation_ok": bool(fused["generation"]["consistent"]),
            "explainable": bool(fused.get("conclusions")) and bool(fused.get("next_actions")),
        })
    total = len(samples)
    passed = total > 0 and all(sample["selection_ok"] and sample["generation_ok"] and sample["explainable"] for sample in samples)
    result = {
        "samples": total,
        "tier": tier,
        "selection_recall": round(sum(1 for sample in samples if sample["selection_ok"]) / total, 3) if total else 0.0,
        "generation_consistency": round(sum(1 for sample in samples if sample["generation_ok"]) / total, 3) if total else 0.0,
        "explainability_coverage": round(sum(1 for sample in samples if sample["explainable"]) / total, 3) if total else 0.0,
        "p95_ms": _p95([sample["elapsed_ms"] for sample in samples]),
        "passed": passed,
    }
    WorkspaceStore(workspace_file).append_jsonl("cross-shard-fusion-gates.jsonl", result)
    return result


def _normalize_matches(primary: dict[str, Any], shard_evidence: dict[str, Any], selected_projects: list[str]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for item in primary.get("results", []) or primary.get("matches", []) or primary.get("hits", []) or []:
        node = item.get("node", item) if isinstance(item, dict) else {}
        if not isinstance(node, dict):
            continue
        candidates.append({"project": node.get("project", ""), "name": node.get("name", ""), "type": node.get("type", ""), "file_path": node.get("file_path", node.get("path", "")), "line": node.get("line", 0), "score": float(item.get("score", 0) or 0) if isinstance(item, dict) else 0.0, "sources": ["primary"]})
    for item in shard_evidence.get("matches", []) or []:
        if isinstance(item, dict):
            candidates.append({**item, "sources": [item.get("source", "service_shard")]})
    merged: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for item in candidates:
        key = (str(item.get("project", "")), str(item.get("type", "")), str(item.get("name", "")), str(item.get("file_path", "")))
        current = merged.get(key)
        if current is None:
            merged[key] = item
            continue
        current["score"] = max(float(current.get("score", 0)), float(item.get("score", 0)))
        current["sources"] = sorted(set(current.get("sources", []) + item.get("sources", [])))
    rows = list(merged.values())
    for row in rows:
        if row.get("project") in selected_projects:
            row["score"] = float(row.get("score", 0)) + 1.0
    return sorted(rows, key=lambda item: (-float(item.get("score", 0)), str(item.get("project", "")), str(item.get("name", ""))))


def _contract_consistency(contracts: dict[str, Any], topology: dict[str, Any], projects: list[str], query: str) -> dict[str, Any]:
    project_set = set(projects)
    services = {str(item.get("name", "") or ""): item for item in topology.get("services", []) or []}
    service_aliases = {str(item.get("service_name", "") or ""): str(item.get("name", "") or "") for item in topology.get("services", []) or []}
    feign_checks = []
    for item in contracts.get("feigns", []) or []:
        if item.get("project") not in project_set:
            continue
        target = service_aliases.get(str(item.get("target_service", "") or ""), "")
        status = "verified" if target in services else "attention"
        feign_checks.append({"contract": item.get("interface", ""), "from_project": item.get("project", ""), "to_project": target, "status": status, "reason": "target_service_resolved" if status == "verified" else "target_service_not_in_workspace"})
    topic_map: dict[str, set[str]] = {}
    for item in contracts.get("mq", []) or []:
        if item.get("project") not in project_set:
            continue
        topic = str(item.get("topic", "") or item.get("topic_placeholder", "") or "")
        if topic:
            topic_map.setdefault(topic, set()).add(str(item.get("kind", "") or ""))
    mq_checks = [{"topic": topic, "status": "verified" if any("producer" in kind for kind in kinds) and any("consumer" in kind or "listener" in kind for kind in kinds) else "attention", "kinds": sorted(kinds)} for topic, kinds in topic_map.items()]
    dto_named = any(token in query.lower() for token in ("dto", "request", "response", "vo"))
    dto = {"status": "attention" if dto_named else "not_applicable", "reason": "shared_dto_requires_consumer_review" if dto_named else "query_not_dto_focused"}
    statuses = [item["status"] for item in feign_checks + mq_checks] + [dto["status"]]
    overall = "attention" if "attention" in statuses else "verified" if "verified" in statuses else "not_applicable"
    return {"overall": overall, "feign": feign_checks[:20], "mq": mq_checks[:20], "dto": dto, "api": {"status": "not_applicable", "reason": "api_matching_is_reported_by_indexed_contract_edges"}}


def _conclusions(matches: list[dict[str, Any]], contracts: dict[str, Any], consistent: bool) -> list[dict[str, Any]]:
    conclusions = []
    if matches:
        projects = sorted({str(item.get("project", "")) for item in matches if item.get("project")})
        conclusions.append({"kind": "service_scope", "summary": f"命中 {len(projects)} 个相关服务分片：{', '.join(projects[:6])}", "semantic_strength": "fact" if consistent else "derived", "evidence_count": len(matches)})
    if contracts.get("overall") == "attention":
        conclusions.append({"kind": "contract_risk", "summary": "发现需要人工确认的跨服务契约关联。", "semantic_strength": "inferred", "evidence_count": len(contracts.get("feign", [])) + len(contracts.get("mq", []))})
    if not conclusions:
        conclusions.append({"kind": "no_evidence", "summary": "当前分片未返回足够证据，建议缩小入口或运行局部 reindex。", "semantic_strength": "derived", "evidence_count": 0})
    return conclusions


def _next_actions(consistent: bool, contracts: dict[str, Any]) -> list[str]:
    actions = []
    if not consistent:
        actions.append("generation 不一致，重新查询或等待当前 reindex 完成后再修改代码。")
    if contracts.get("overall") == "attention":
        actions.append("对 Feign/API/MQ/DTO 运行 mc_analyze(depth='full') 并确认消费者兼容性。")
    if not actions:
        actions.append("读取已返回的服务分片证据，再对关键入口执行影响分析。")
    return actions


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * 0.95))]
