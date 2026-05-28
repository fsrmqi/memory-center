from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Dict, List

from ..graph import GraphStore
from ..rules import match_rules
from .common import _best_match, _build_progressive_levels, _impact_checklist, _unknown_static_analysis_risks, load_context
from .query import _build_lookup_payload, _build_impact_evidence_summary, memory_query


def memory_impact(workspace_file: str | Path, target: str, direction: str = "upstream", max_depth: int = 3) -> Dict[str, Any]:
    _, store = load_context(workspace_file)
    with GraphStore(store.graph_db_path) as graph:
        lookup = memory_query(workspace_file, target, limit=8)
        matches = [item.get("node", {}) for item in lookup.get("matches", []) if item.get("node")]
        if not matches:
            return {
                "target": target,
                "found": False,
                "risk_level": "unknown",
                "confirmed_impacts": [],
                "probable_impacts": [],
                "possible_impacts": [],
                "lookup": _build_lookup_payload(lookup),
                "progressive": _build_impact_progressive_view(target, None, [], [], []),
                "unknown_risks": _unknown_static_analysis_risks(),
            }
        node = _best_match(matches, target)
        impacts = graph.neighbors(node["id"], direction=direction, max_depth=max_depth, limit=300)
        confirmed = [x for x in impacts if float(x.get("confidence", 0)) >= 0.80]
        probable = [x for x in impacts if 0.55 <= float(x.get("confidence", 0)) < 0.80]
        possible = [x for x in impacts if float(x.get("confidence", 0)) < 0.55]
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
        return {
            "target": node,
            "found": True,
            "direction": direction,
            "max_depth": max_depth,
            "risk_level": risk_level,
            "impacted_projects": impacted_projects,
            "confirmed_impacts": confirmed,
            "probable_impacts": probable,
            "possible_impacts": possible,
            "lookup": _build_lookup_payload(lookup),
            "evidence_summary": _build_impact_evidence_summary(confirmed, probable, possible),
            "progressive": _build_impact_progressive_view(target, node, confirmed, probable, possible),
            "required_rules": rules,
            "review_checklist": _impact_checklist(node, risk_level),
            "unknown_risks": _unknown_static_analysis_risks(),
            "explanation": {
                "confirmed": "confidence >= 0.80, usually direct declarations, annotations, config, or contract edges",
                "probable": "0.55 <= confidence < 0.80, usually import, Feign endpoint match, inferred method/field usage",
                "possible": "confidence < 0.55, weak hints only; verify manually",
            },
        }


def memory_plan_change(workspace_file: str | Path, target: str, direction: str = "upstream", max_depth: int = 3) -> Dict[str, Any]:
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
        "required_rules": impact.get("required_rules", []),
        "review_checklist": impact.get("review_checklist", []),
        "impact": {
            "confirmed_count": len(impact.get("confirmed_impacts", [])),
            "probable_count": len(impact.get("probable_impacts", [])),
            "possible_count": len(impact.get("possible_impacts", [])),
            "impacted_projects": impact.get("impacted_projects", []),
        },
    }


def memory_verify_checklist(workspace_file: str | Path, target: str) -> Dict[str, Any]:
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


def memory_detect_changes(workspace_file: str | Path, scope: str = "staged") -> Dict[str, Any]:
    config, store = load_context(workspace_file)
    with GraphStore(store.graph_db_path) as graph:
        changed: List[str] = []
        deleted: List[str] = []
        for svc in config.services:
            repo = config.resolve_service_path(svc)
            if not (repo / ".git").exists():
                continue
            commands = [["git", "diff", "--name-only"]]
            delete_commands = [["git", "diff", "--diff-filter=D", "--name-only"]]
            if scope == "staged":
                commands = [["git", "diff", "--name-only", "--cached"]]
                delete_commands = [["git", "diff", "--diff-filter=D", "--name-only", "--cached"]]
            elif scope == "head":
                commands = [["git", "diff", "--name-only", "HEAD~1..HEAD"]]
                delete_commands = [["git", "diff", "--diff-filter=D", "--name-only", "HEAD~1..HEAD"]]
            elif scope == "all":
                commands = [["git", "diff", "--name-only"], ["git", "diff", "--name-only", "--cached"]]
                delete_commands = [["git", "diff", "--diff-filter=D", "--name-only"], ["git", "diff", "--diff-filter=D", "--name-only", "--cached"]]
            try:
                for cmd in commands:
                    out = subprocess.check_output(cmd, cwd=repo, text=True, stderr=subprocess.DEVNULL)
                    changed.extend(
                        [f"{config.service_logical_prefix(svc)}/{line.strip()}".strip("/") for line in out.splitlines() if line.strip()]
                    )
                for cmd in delete_commands:
                    out = subprocess.check_output(cmd, cwd=repo, text=True, stderr=subprocess.DEVNULL)
                    deleted.extend(
                        [f"{config.service_logical_prefix(svc)}/{line.strip()}".strip("/") for line in out.splitlines() if line.strip()]
                    )
            except Exception:
                continue
        changed = sorted(dict.fromkeys(changed))
        deleted = sorted(dict.fromkeys(deleted))
        file_index = store.read_json_prefer_backend("file-index.json", [])
        matched_files = [f for f in file_index if f.get("path") in changed]
        changed_text = " ".join(changed)
        rules = match_rules(store, intent=f"git changes {changed_text}", files=changed)[:20]
        affected_projects = sorted({f.get("project") for f in matched_files})
        graph_hits = []
        for file in changed[:50]:
            graph_hits.extend(graph.find_nodes(file, types=["File"], limit=5))
        confirmed_edges = []
        for hit in graph_hits[:20]:
            confirmed_edges.extend(graph.neighbors(hit["id"], direction="both", max_depth=1, limit=20))
        high_markers = ["common-api", "Feign", "Message", "Consumer", "Controller", "DTO", "application.yml", "bootstrap.yml"]
        risk_level = "high" if any(m in changed_text for m in high_markers) or any(e.get("type") in {"IMPLEMENTS_FEIGN", "CONSUMES_TOPIC", "READS_FIELD"} for e in confirmed_edges) else "medium" if changed else "low"
        return {
            "scope": scope,
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


def _build_impact_progressive_view(
    target: str,
    node: Dict[str, Any] | None,
    confirmed: List[Dict[str, Any]],
    probable: List[Dict[str, Any]],
    possible: List[Dict[str, Any]],
) -> Dict[str, Any]:
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