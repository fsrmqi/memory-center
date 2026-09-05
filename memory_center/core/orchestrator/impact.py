from __future__ import annotations

import hashlib
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from time import perf_counter
from typing import Any

from memory_center.core.governance.rules import match_rules
from memory_center.core.knowledge.ontology import edge_strength
from memory_center.core.observability.diagnostics import DIAG, diag_entry
from memory_center.core.observability.tracking import log_token_gain
from memory_center.core.storage.graph import IMPACT_DEFAULT_EDGE_WEIGHT, IMPACT_EDGE_WEIGHTS
from memory_center.core.storage.runtime import RuntimeStore

from ..explanation import explanation_entry, merge_explanations
from ..verification.heuristics import apply_candidate_path_learning
from .compact import _measure_compact_gain
from .query import (
    _build_augmented_lookup_payload,
    _build_edge_summary_lines,
    _build_impact_evidence_summary,
    _build_lookup_payload,
    _build_project_evidence,
    _build_project_scope,
    _compact_focus_edges,
    _format_compact_node_summary,
    _summarize_chain_edges,
    memory_symbol,
)
from .shared import (
    _build_progressive_levels,
    _impact_checklist,
    _is_compact_view,
    _unknown_static_analysis_risks,
    load_context,
)


def memory_impact(
    workspace_file: str | Path,
    target: str,
    direction: str = "upstream",
    max_depth: int = 3,
    project: str = "",
    view: str = "full",
    budget: str = "medium",
) -> dict[str, Any]:
    _, store = load_context(workspace_file)
    with RuntimeStore(store.graph_db_path) as graph:
        symbol_info = memory_symbol(workspace_file, target, limit=8, project=project)
        lookup = symbol_info.get("lookup", {})
        if not symbol_info.get("found"):
            candidate_paths = _build_impact_candidate_paths(
                found=False,
                target={"name": target, "type": ""},
                risk_level="unknown",
                confirmed=[],
                probable=[],
                possible=[],
                rules=[],
                freshness={},
            )
            candidate_paths = apply_candidate_path_learning(workspace_file, candidate_paths)
            freshness = _get_freshness_for_impact(workspace_file)
            result = {
                "target": target,
                "found": False,
                "risk_level": "unknown",
                "confirmed_impacts": [],
                "probable_impacts": [],
                "possible_impacts": [],
                "candidate_paths": candidate_paths,
                "recommended_path": dict(candidate_paths[0]) if candidate_paths else {},
                "lookup": lookup if lookup else _build_lookup_payload({"query": target, "matches": []}),
                "progressive": _build_impact_progressive_view(target, None, [], [], []),
                "unknown_risks": _unknown_static_analysis_risks(),
                "freshness": freshness,
                "_reasoning": {"patterns": [], "transitive": [], "risk": []},
            }
            if _is_compact_view(view):
                compact = _compact_impact_result(result, budget=budget)
                gain = _measure_compact_gain(result, compact)
                log_token_gain(workspace_file, "memory_impact", budget=budget, model="", raw_tokens=gain["raw_tokens"], compact_tokens=gain["compact_tokens"], view=view)
                return compact
            return result
        node = symbol_info.get("best_match", {}) or {}
        impacts = graph.weighted_impact_paths(
            node["id"], direction=direction, max_depth=max_depth, limit=300
        )
        impacts = _include_alternative_direct_evidence(graph, node["id"], direction, impacts)
        confirmed = [x for x in impacts if _impact_band_score(x) >= 0.80]
        probable = [
            x
            for x in impacts
            if 0.55 <= _impact_band_score(x) < 0.80
        ]
        possible = [x for x in impacts if _impact_band_score(x) < 0.55]
        impacted_projects = sorted(
            {x.get("source", {}).get("project") for x in impacts if x.get("source", {}).get("project")}
            | {x.get("target", {}).get("project") for x in impacts if x.get("target", {}).get("project")}
        )
        risky_types = {"DTO", "Field", "FeignClient", "FeignMethod", "MQTopic", "MQConsumer", "Endpoint", "ConfigKey"}
        if node["type"] in risky_types or len(impacted_projects) >= 3 or confirmed:
            risk_level = "high"
        else:
            risk_level = "low" if impacts else "unknown"
        rules = match_rules(store, intent=f"impact {target} {node['type']}", files=[node.get("file_path", "")])[:12]
        freshness = _get_freshness_for_impact(workspace_file)
        candidate_paths = _build_impact_candidate_paths(
            found=True,
            target=node,
            risk_level=risk_level,
            confirmed=confirmed,
            probable=probable,
            possible=possible,
            rules=rules,
            freshness=freshness,
        )
        candidate_paths = apply_candidate_path_learning(workspace_file, candidate_paths)
        result = {
            "target": node,
            "found": True,
            "direction": direction,
            "max_depth": max_depth,
            "project_scope": _build_project_scope(project, node),
            "project_evidence": _build_project_evidence(symbol_info.get("matches", []), node, project),
            "risk_level": risk_level,
            "impacted_projects": impacted_projects,
            "confirmed_impacts": confirmed,
            "probable_impacts": probable,
            "possible_impacts": possible,
            "impact_algorithm": {
                "name": "bounded_weighted_best_path_v1",
                "score_formula": "relation_weight * edge_confidence * evidence_factor * freshness_factor * depth_decay",
                "bounded": True,
                "truncated": bool((impacts[0].get("traversal", {}) if impacts else {}).get("truncated", False)),
            },
            "candidate_paths": candidate_paths,
            "recommended_path": dict(candidate_paths[0]) if candidate_paths else {},
            "lookup": _build_augmented_lookup_payload(
                {"query": target, "retrieval_summary": lookup.get("retrieval_summary", {}), "matches": []},
                anchor_node=node,
                project_evidence=_build_project_evidence(symbol_info.get("matches", []), node, project),
            ),
            "evidence_summary": _build_impact_evidence_summary(confirmed, probable, possible),
            "progressive": _build_impact_progressive_view(target, node, confirmed, probable, possible),
            "required_rules": rules,
            "review_checklist": _impact_checklist(node, risk_level),
            "unknown_risks": _unknown_static_analysis_risks(),
            "explanation": {
                "confirmed": "impact_score >= 0.80 after relation, confidence, evidence, freshness, and depth weighting",
                "probable": "0.55 <= impact_score < 0.80; inspect the returned best evidence path",
                "possible": "impact_score < 0.55; weak or distant propagation that requires verification",
            },
            "_explanation_entries": _build_impact_explanation_entries(confirmed, probable, possible, node),
            "freshness": freshness,
            "_reasoning": _get_reasoning_for_impact(workspace_file, node.get("id", "")),
        }
        if _is_compact_view(view):
            compact = _compact_impact_result(result, budget=budget)
            gain = _measure_compact_gain(result, compact)
            log_token_gain(workspace_file, "memory_impact", budget=budget, model="", raw_tokens=gain["raw_tokens"], compact_tokens=gain["compact_tokens"], view=view)
            return compact
        return result


def _impact_band_score(impact: dict[str, Any]) -> float:
    """Keep direct extracted edges in their prior evidence band while ranking by weighted score."""
    weighted = float(impact.get("impact_score", impact.get("confidence", 0)) or 0.0)
    if int(impact.get("depth", 0) or 0) == 1 or impact.get("alternative_path_evidence"):
        return max(weighted, float(impact.get("confidence", 0) or 0.0))
    return weighted


def _include_alternative_direct_evidence(
    graph: RuntimeStore,
    node_id: str,
    direction: str,
    impacts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Expose distinct direct relations without expanding them as competing paths."""
    known_edge_ids = {str(item.get("id", "")) for item in impacts}
    direct_edges = graph.neighbors(node_id, direction=direction, max_depth=1, limit=100)
    alternatives: list[dict[str, Any]] = []
    for edge in direct_edges:
        if str(edge.get("id", "")) in known_edge_ids:
            continue
        confidence = float(edge.get("confidence", 0.0) or 0.0)
        weight = float(IMPACT_EDGE_WEIGHTS.get(str(edge.get("type", "")), IMPACT_DEFAULT_EDGE_WEIGHT))
        endpoint = edge.get("source_id") if edge.get("target_id") == node_id else edge.get("target_id")
        alternatives.append(
            {
                **edge,
                "depth": 1,
                "impact_score": round(confidence * weight, 6),
                "best_path": {"node_ids": [node_id, endpoint], "edge_ids": [edge.get("id", "")], "hop_count": 1},
                "score_breakdown": {
                    "relation_weight": round(weight, 4),
                    "edge_confidence": round(confidence, 4),
                    "evidence_factor": 1.0,
                    "freshness_factor": 1.0,
                    "depth_factor": 1.0,
                },
                "alternative_direct_evidence": True,
                "propagated": False,
            }
        )
    return sorted(
        [*impacts, *alternatives],
        key=lambda item: (-float(item.get("impact_score", 0.0)), int(item.get("depth", 0)), str(item.get("id", ""))),
    )


def _compact_impact_result(result: dict[str, Any], budget: str = "medium") -> dict[str, Any]:
    from ..reasoning.integration import compact_reasoning_view
    from .shared import _budget_limits

    limits = _budget_limits(budget)
    # found=False 分支的 target 是原始查询字符串，不是节点 dict。
    raw_target = result.get("target", {}) or {}
    target = raw_target if isinstance(raw_target, dict) else {}
    lookup = result.get("lookup", {}) or {}
    confirmed = result.get("confirmed_impacts", []) or []
    probable = result.get("probable_impacts", []) or []
    possible = result.get("possible_impacts", []) or []
    candidate_paths = result.get("candidate_paths", []) or []
    confirmed_summary = _summarize_chain_edges(_compact_focus_edges(confirmed))
    probable_summary = _summarize_chain_edges(_compact_focus_edges(probable))
    possible_summary = _summarize_chain_edges(_compact_focus_edges(possible))
    summary_lines = [f"Target {_format_compact_node_summary(target)}"]
    project_scope = result.get("project_scope", {}) or {}
    project_evidence = result.get("project_evidence", []) or []
    if project_scope.get("uses_cross_project_anchor"):
        summary_lines.append(
            f"Project scope {project_scope.get('requested_project', '')} uses anchor {target.get('project', '')}"
        )
    for evidence in project_evidence[: limits["events"]]:
        summary_lines.append(f"Project evidence: {_format_compact_node_summary(evidence)}")
    summary_lines.append(
        f"Risk {result.get('risk_level', 'unknown')}, confirmed={len(confirmed)} probable={len(probable)} possible={len(possible)}"
    )
    summary_lines.extend(
        _build_edge_summary_lines("Confirmed", confirmed_summary.get("items", []), limits["steps"] + limits["events"])
    )
    summary_lines.extend(
        _build_edge_summary_lines("Probable", probable_summary.get("items", []), limits["events"])
    )
    summary_lines.extend(
        _build_edge_summary_lines("Possible", possible_summary.get("items", []), max(1, limits["events"] // 2))
    )
    recommended_path = result.get("recommended_path", {}) or {}
    next_action = str(recommended_path.get("next_action", "") or "").strip()
    if next_action:
        summary_lines.append(f"Next: {next_action}")
    return {
        "target": {
            "type": target.get("type", ""),
            "name": target.get("name", "") if isinstance(target, dict) else str(target),
            "project": target.get("project", "") if isinstance(target, dict) else "",
            "file_path": target.get("file_path", "") if isinstance(target, dict) else "",
            "line": target.get("line", 0) if isinstance(target, dict) else 0,
        },
        "found": result.get("found", False),
        "direction": result.get("direction", ""),
        "max_depth": result.get("max_depth", 0),
        "project_scope": project_scope,
        "project_evidence": project_evidence[: limits["events"]],
        "risk_level": result.get("risk_level", "unknown"),
        "impacted_projects": result.get("impacted_projects", [])[: limits["services"]],
        "evidence_summary": result.get("evidence_summary", {}),
        "confirmed_summary": {
            "items": confirmed_summary.get("items", [])[: limits["steps"] + limits["events"]],
            "count": len(confirmed),
        },
        "probable_summary": {
            "items": probable_summary.get("items", [])[: limits["events"]],
            "count": len(probable),
        },
        "possible_summary": {
            "items": possible_summary.get("items", [])[: max(1, limits["events"] // 2)],
            "count": len(possible),
        },
        "summary_lines": summary_lines,
        "candidate_paths": [
            {
                "candidate_type": item.get("candidate_type", ""),
                "target": item.get("target", ""),
                "status": item.get("status", ""),
                "weight": item.get("weight", 0),
                "next_action": item.get("next_action", ""),
            }
            for item in candidate_paths[: limits["steps"]]
        ],
        "recommended_path": recommended_path,
        "lookup": {
            "query": lookup.get("query", ""),
            "retrieval_summary": lookup.get("retrieval_summary", {}),
            "entrypoints": [
                {
                    "role": item.get("role", ""),
                    "type": (item.get("node", {}) or {}).get("type", ""),
                    "name": (item.get("node", {}) or {}).get("name", ""),
                    "project": (item.get("node", {}) or {}).get("project", ""),
                    "line": (item.get("node", {}) or {}).get("line", 0),
                    "exact_score": item.get("exact_score", 0),
                }
                for item in (lookup.get("entrypoints", []) or [])[: limits["events"]]
            ],
        },
        "_reasoning": compact_reasoning_view(result.get("_reasoning", {}), limit=2),
    }


def memory_plan_change(workspace_file: str | Path, target: str, direction: str = "upstream", max_depth: int = 3) -> dict[str, Any]:
    impact = memory_impact(workspace_file, target, direction=direction, max_depth=max_depth)
    if not impact.get("found"):
        return {
            "target": target,
            "found": False,
            "plan": [],
            "hint": "未找到目标节点，先用 memory_search_code / memory_symbol 定位。",
            "impact": impact,
        }
    plan = [
        "1) 先确认目标节点与影响范围（context + impact）。",
        "2) 优先处理 high confidence 影响点，再处理 probable/possible。",
        "3) 执行契约兼容检查（DTO/Feign/MQ/Config）。",
        "4) 增量改动并同步补测试，执行回归与静态检查。",
        "5) 完成后记录 case，沉淀流程与风险点。",
    ]
    return {
        "target": impact.get("target", {}),
        "found": True,
        "risk_level": impact.get("risk_level", "unknown"),
        "plan": plan,
        "candidate_paths": impact.get("candidate_paths", []),
        "recommended_path": impact.get("recommended_path", {}),
        "required_rules": impact.get("required_rules", []),
        "review_checklist": impact.get("review_checklist", []),
        "impact": {
            "confirmed_count": len(impact.get("confirmed_impacts", [])),
            "probable_count": len(impact.get("probable_impacts", [])),
            "possible_count": len(impact.get("possible_impacts", [])),
            "impacted_projects": impact.get("impacted_projects", []),
        },
    }


def memory_verify_checklist(workspace_file: str | Path, target: str) -> dict[str, Any]:
    impact = memory_impact(workspace_file, target, direction="upstream", max_depth=3)
    checklist = list(impact.get("review_checklist", []))
    target_type = (impact.get("target", {}) or {}).get("type", "")
    if target_type in {"FeignClient", "FeignMethod", "Endpoint"}:
        checklist.extend(["校验调用方与被调方请求/响应结构兼容。", "校验 HTTP 状态码与错误码约定是否一致。"])
    if target_type in {"MQTopic", "MQConsumer"}:
        checklist.extend(["校验消息 schema 向后兼容与默认值策略。", "校验消费幂等、重试与死信处理。"])
    if target_type in {"ConfigKey"}:
        checklist.extend(["校验默认配置和环境覆盖是否一致。", "校验灰度发布期间新旧配置都可工作。"])
    deduped = list(dict.fromkeys(checklist))
    return {
        "target": target,
        "found": impact.get("found", False),
        "risk_level": impact.get("risk_level", "unknown"),
        "target_type": target_type,
        "checklist": deduped,
        "required_rules": impact.get("required_rules", []),
    }


def memory_detect_changes(workspace_file: str | Path, scope: str = "staged") -> dict[str, Any]:
    config, store = load_context(workspace_file)
    started = perf_counter()
    repositories = [
        (config.resolve_service_path(service), config.service_logical_prefix(service).strip("/"))
        for service in config.services
        if (config.resolve_service_path(service) / ".git").exists()
    ]
    changed: list[str] = []
    deleted: list[str] = []
    git_errors: list[dict[str, str]] = []
    if repositories:
        with ThreadPoolExecutor(max_workers=min(8, len(repositories))) as executor:
            futures = {
                executor.submit(_git_changes_for_repository, repo, prefix, scope): prefix
                for repo, prefix in repositories
            }
            for future in as_completed(futures):
                prefix = futures[future]
                try:
                    repo_changed, repo_deleted = future.result()
                    changed.extend(repo_changed)
                    deleted.extend(repo_deleted)
                except (OSError, subprocess.SubprocessError) as exc:
                    git_errors.append({"repository_ref": _change_repository_ref(prefix), "reason": type(exc).__name__})
    changed = sorted(dict.fromkeys(changed))
    deleted = sorted(dict.fromkeys(deleted))
    with RuntimeStore(store.graph_db_path) as graph:
        file_index = store.read_json_prefer_backend("file-index.json", [])
        matched_files = [f for f in file_index if f.get("path") in changed]
        changed_text = " ".join(changed)
        rules = match_rules(store, intent=f"git changes {changed_text}", files=changed)[:20]
        affected_projects = sorted({f.get("project") for f in matched_files})
        graph_hits = graph.nodes_for_files(changed[:50], types=["File"], limit=100)
        confirmed_edges = []
        for hit in graph_hits[:20]:
            confirmed_edges.extend(graph.traverse_edges(hit["id"], direction="both", max_depth=1, limit=20))
        high_markers = ["common-api", "Feign", "Message", "Consumer", "Controller", "DTO", "application.yml", "bootstrap.yml"]
        risk_level = "high" if any(m in changed_text for m in high_markers) or any(e.get("type") in {"IMPLEMENTS_FEIGN", "CONSUMES_TOPIC", "READS_FIELD"} for e in confirmed_edges) else "medium" if changed else "low"
        return {
            "scope": scope,
            "timing_ms": {"total": round((perf_counter() - started) * 1000, 3)},
            "git_repository_count": len(repositories),
            "git_errors": git_errors,
            "changed_files": changed,
            "deleted_files": deleted,
            "matched_index_files": matched_files,
            "affected_projects": affected_projects,
            "risk_level": risk_level,
            "graph_evidence": confirmed_edges[:50],
            "rules": rules,
            "review_checklist": [
                "检查公共 DTO / Feign / MQ Message 是否存在兼容性风险",
                "检查 Kafka/RocketMQ 消费是否幂等、可重试、可观测",
                "检查 ES/Mongo/DB 写入是否具备失败明细与补偿策略",
                "检查日志是否包含 chainId、siteCode、uid、业务主键",
                "如果 graph_evidence 为空，不代表无影响；可能是索引精度不足或尚未 reindex",
            ],
            "unknown_risks": _unknown_static_analysis_risks(),
        }


def _git_changes_for_repository(repo: Path, prefix: str, scope: str) -> tuple[list[str], list[str]]:
    commands = [["git", "diff", "--name-status", "-z"]]
    if scope == "staged":
        commands = [["git", "diff", "--cached", "--name-status", "-z"]]
    elif scope == "head":
        commands = [["git", "diff", "--name-status", "-z", "HEAD~1..HEAD"]]
    elif scope == "all":
        commands.append(["git", "diff", "--cached", "--name-status", "-z"])
    changed: list[str] = []
    deleted: list[str] = []
    for command in commands:
        output = subprocess.check_output(
            command,
            cwd=repo,
            stderr=subprocess.DEVNULL,
            timeout=10,
        ).decode("utf-8", errors="replace")
        command_changed, command_deleted = _parse_git_name_status(output, prefix)
        changed.extend(command_changed)
        deleted.extend(command_deleted)
    return changed, deleted


def _parse_git_name_status(output: str, prefix: str) -> tuple[list[str], list[str]]:
    fields = [field for field in output.split("\0") if field]
    changed: list[str] = []
    deleted: list[str] = []
    index = 0
    while index < len(fields):
        status = fields[index]
        index += 1
        if index >= len(fields):
            break
        old_path = fields[index]
        index += 1
        path = old_path
        if status.startswith(("R", "C")) and index < len(fields):
            path = fields[index]
            index += 1
            if status.startswith("R"):
                deleted.append(f"{prefix}/{old_path}".strip("/"))
        logical_path = f"{prefix}/{path}".strip("/")
        changed.append(logical_path)
        if status.startswith("D"):
            deleted.append(logical_path)
    return changed, deleted


def _change_repository_ref(prefix: str) -> str:
    return hashlib.sha256(prefix.encode("utf-8", errors="replace")).hexdigest()[:12]


def _build_impact_progressive_view(
    target: str,
    node: dict[str, Any] | None,
    confirmed: list[dict[str, Any]],
    probable: list[dict[str, Any]],
    possible: list[dict[str, Any]],
) -> dict[str, Any]:
    node_label = target if not node else f"{node.get('type', '')}:{node.get('name', '')}"
    return _build_progressive_levels(
        {
            "target": node_label,
            "confirmed_count": len(confirmed),
            "probable_count": len(probable),
            "possible_count": len(possible),
        },
        {
            "confirmed_edge_types": sorted({item.get("type", "") for item in confirmed if item.get("type")}),
            "probable_edge_types": sorted({item.get("type", "") for item in probable if item.get("type")}),
            "top_confirmed": [
                f"{item.get('type', '')}:{item.get('source', {}).get('name', '')}->{item.get('target', {}).get('name', '')}"
                for item in confirmed[:5]
            ],
        },
        {
            "probable_preview": [
                f"{item.get('type', '')}:{item.get('source', {}).get('name', '')}->{item.get('target', {}).get('name', '')}"
                for item in probable[:5]
            ],
            "possible_preview": [
                f"{item.get('type', '')}:{item.get('source', {}).get('name', '')}->{item.get('target', {}).get('name', '')}"
                for item in possible[:5]
            ],
        },
    )


def _build_impact_candidate_paths(
    *,
    found: bool,
    target: dict[str, Any],
    risk_level: str,
    confirmed: list[dict[str, Any]],
    probable: list[dict[str, Any]],
    possible: list[dict[str, Any]],
    rules: list[dict[str, Any]],
    freshness: dict[str, Any],
) -> list[dict[str, Any]]:
    if not found:
        return [
            {
                "candidate_type": "re-locate-target",
                "target": target.get("name", ""),
                "status": "probable",
                "weight": 0.82,
                "why": "当前没有定位到图谱节点，先重新定位符号或代码入口比直接做影响分析更有效。",
                "next_action": '先用 mc_lookup(query="...", mode="symbol/code") 重新定位目标',
                "verification_cost": "low",
            }
        ]

    candidates: list[dict[str, Any]] = []
    target_name = target.get("name", "")
    target_type = target.get("type", "")
    confirmed_count = len(confirmed)
    probable_count = len(probable)
    possible_count = len(possible)

    if confirmed_count > 0:
        candidates.append(
            {
                "candidate_type": "verify_confirmed_impacts",
                "target": target_name,
                "status": "confirmed",
                "weight": 0.95,
                "why": f"当前已有 {confirmed_count} 个高置信影响点，先验证这批路径最划算。",
                "next_action": "优先检查 confirmed_impacts 中的直接调用、注入、契约或配置边",
                "verification_cost": "medium",
                "_learning_aliases": [
                    {"candidate_type": "impact_analysis", "target": target_name},
                ],
            }
        )

    if risk_level in {"high", "medium"}:
        depth = "full" if target_type in {"FeignClient", "FeignMethod", "MQTopic", "MQConsumer", "Endpoint", "ConfigKey", "DTO", "Field"} else "standard"
        candidates.append(
            {
                "candidate_type": "structured_impact_review",
                "target": target_name,
                "status": "probable" if risk_level == "medium" else "confirmed",
                "weight": 0.84 if risk_level == "medium" else 0.91,
                "why": f"目标类型 {target_type or 'unknown'} 的风险等级为 {risk_level}，建议进入结构化影响审查。",
                "next_action": f'mc_analyze(target="{target_name}", depth="{depth}")',
                "verification_cost": "medium",
                "_learning_aliases": [
                    {"candidate_type": "impact_analysis", "target": target_name},
                ],
            }
        )

    if rules:
        candidates.append(
            {
                "candidate_type": "rule_validation",
                "target": target_name,
                "status": "possible",
                "weight": 0.73,
                "why": f"当前命中了 {len(rules)} 条相关规则，先核对规则与契约边界可降低误改概率。",
                "next_action": "先查看 required_rules 与 review_checklist，再决定改动方式",
                "verification_cost": "low",
            }
        )

    freshness_status = ((freshness.get("freshness", {}) or {}).get("status", "") if isinstance(freshness, dict) else "")
    if freshness_status in {"pending", "stale"}:
        candidates.append(
            {
                "candidate_type": "freshness_validation",
                "target": freshness_status,
                "status": "possible",
                "weight": 0.78 if freshness_status == "pending" else 0.88,
                "why": f"当前索引状态为 {freshness_status}，关键影响路径最好先读 live file 或 reindex。",
                "next_action": "先读取关键文件实时内容；必要时先 reindex 再确认影响面",
                "verification_cost": "low",
            }
        )

    if probable_count or possible_count:
        candidates.append(
            {
                "candidate_type": "expand_low_confidence_paths",
                "target": target_name,
                "status": "possible",
                "weight": 0.62,
                "why": f"还有 {probable_count} 个 probable 和 {possible_count} 个 possible 路径，适合在确认高置信影响后再扩展验证。",
                "next_action": "确认 confirmed 后，再按 probable -> possible 的顺序补做抽样验证",
                "verification_cost": "high" if possible_count > probable_count else "medium",
                "_learning_aliases": [
                    {"candidate_type": "impact_analysis", "target": target_name},
                ],
            }
        )

    return sorted(
        candidates,
        key=lambda item: (
            0 if item.get("status") == "confirmed" else 1 if item.get("status") == "probable" else 2,
            -float(item.get("weight", 0.0)),
            item.get("candidate_type", ""),
        ),
    )


def _get_freshness_for_impact(workspace_file: str | Path) -> dict:
    """Get freshness banner for impact analysis results."""
    try:
        from ..freshness.status import IndexFreshnessService
        svc = IndexFreshnessService(workspace_file)
        return svc.banner()
    except Exception as exc:
        return diag_entry(DIAG.UNKNOWN, exc=exc)


def _get_reasoning_for_impact(workspace_file: str | Path, target_id: str) -> dict:
    """Run reasoning patterns and return results for impact analysis.

    Returns reasoning dict with patterns, transitive, risk, and optional _diagnostics.
    Never raises — returns diagnostics on failure.
    """
    try:
        from ..reasoning.integration import run_reasoning_patterns
        return run_reasoning_patterns(str(workspace_file), target_id=target_id, intent="impact")
    except Exception as exc:
        return {"patterns": [], "transitive": [], "risk": [], "_diagnostics": diag_entry(DIAG.UNAVAILABLE, exc=exc)}


def _build_impact_explanation_entries(
    confirmed: list[dict[str, Any]],
    probable: list[dict[str, Any]],
    possible: list[dict[str, Any]],
    node: dict[str, Any],
) -> dict[str, Any]:
    """Build D-03 standard explanation entries for each impact tier."""
    target_label = f"{node.get('type', '')}:{node.get('name', '')}"

    def _tier_entry(items: list[dict[str, Any]], label: str, desc: str) -> dict:
        evidence = [
            {
                "edge_type": item.get("type", ""),
                "source": item.get("source", {}).get("name", ""),
                "target": item.get("target", {}).get("name", ""),
                "confidence": item.get("confidence", 0.5),
            }
            for item in items[:10]
        ]
        refs = [
            {"id": item.get("target", {}).get("id", ""), "name": item.get("target", {}).get("name", "")}
            for item in items[:10]
            if item.get("target", {}).get("id")
        ]
        avg_conf = sum(float(i.get("confidence", 0.5)) for i in items) / max(len(items), 1)
        strengths = [edge_strength(str(item.get("type", "") or "")) for item in items]
        normalized_strengths = [strength if strength in {"fact", "inferred", "derived"} else "inferred" for strength in strengths]
        strength = min(normalized_strengths, key={"derived": 0, "inferred": 1, "fact": 2}.get, default="inferred")
        return explanation_entry(
            subject=f"impact:{target_label}:{label}",
            summary=f"{desc} (共 {len(items)} 项)",
            evidence=evidence,
            semantic_strength=strength,
            confidence=round(avg_conf, 3),
            next_refs=refs,
        )

    entries = []
    if confirmed:
        entries.append(_tier_entry(confirmed, "confirmed", "高置信度影响"))
    if probable:
        entries.append(_tier_entry(probable, "probable", "中置信度影响"))
    if possible:
        entries.append(_tier_entry(possible, "possible", "低置信度可能影响"))

    merged = merge_explanations(entries) if entries else explanation_entry(
        subject=f"impact:{target_label}",
        summary="未发现影响",
        semantic_strength="fact",
        confidence=1.0,
    )
    return {"entries": entries, "merged": merged}
