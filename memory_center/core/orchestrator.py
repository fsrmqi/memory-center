from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from .config import load_workspace_config
from .rules import match_rules
from .store import WorkspaceStore


def load_context(workspace_file: str | Path):
    config = load_workspace_config(workspace_file)
    store = WorkspaceStore(workspace_file)
    return config, store


def workspace_status(workspace_file: str | Path) -> Dict[str, Any]:
    config, store = load_context(workspace_file)
    return {
        "workspace": config.workspace,
        "root": str(config.root_path),
        "services": [s.__dict__ for s in config.services],
        "index_counts": {
            "files": len(store.read_json("file-index.json", [])),
            "symbols": len(store.read_json("java-symbol-index.json", [])),
            "apis": len(store.read_json("api-index.json", [])),
            "feigns": len(store.read_json("feign-index.json", [])),
            "mq": len(store.read_json("mq-index.json", [])),
            "cases": len(store.read_jsonl("cross-service-task-memory.jsonl", limit=1000)),
        },
        "topology": store.read_json("service-topology.json", {}),
    }


def workspace_sniff(workspace_file: str | Path, intent: str, limit: int = 12) -> Dict[str, Any]:
    config, store = load_context(workspace_file)
    file_index = store.read_json("file-index.json", [])
    symbols = store.read_json("java-symbol-index.json", [])
    apis = store.read_json("api-index.json", [])
    feigns = store.read_json("feign-index.json", [])
    mq = store.read_json("mq-index.json", [])
    cases = store.read_jsonl("cross-service-task-memory.jsonl", limit=200)

    keywords = tokenize(intent)
    matched_files = rank_files(file_index, symbols, keywords)[:limit]
    matched_services = sorted({item["project"] for item in matched_files})
    related_apis = [x for x in apis if any(k in json.dumps(x, ensure_ascii=False).lower() for k in keywords)][:limit]
    related_feigns = [x for x in feigns if any(k in json.dumps(x, ensure_ascii=False).lower() for k in keywords)][:limit]
    related_mq = [x for x in mq if any(k in json.dumps(x, ensure_ascii=False).lower() for k in keywords)][:limit]
    related_cases = [x for x in cases if any(k in json.dumps(x, ensure_ascii=False).lower() for k in keywords)][-5:]
    rules = match_rules(store, intent=intent, files=[x["path"] for x in matched_files])[:10]

    return {
        "workspace": config.workspace,
        "intent": intent,
        "matched_services": matched_services,
        "candidate_files": matched_files,
        "related_apis": related_apis,
        "related_feigns": related_feigns,
        "related_mq": related_mq,
        "related_rules": rules,
        "historical_cases": related_cases,
        "next_steps": [
            "阅读 candidate_files 中排名靠前的入口文件",
            "如果涉及 DTO/Feign/MQ Message，先调用 workspace_check_contract",
            "编辑前调用 workspace_check_rules",
            "完成后调用 workspace_record_case 沉淀经验",
        ],
    }


def workspace_trace(workspace_file: str | Path, entry: str) -> Dict[str, Any]:
    _, store = load_context(workspace_file)
    topology = store.read_json("service-topology.json", {})
    apis = store.read_json("api-index.json", [])
    feigns = store.read_json("feign-index.json", [])
    mq = store.read_json("mq-index.json", [])
    entry_lower = entry.lower()
    return {
        "entry": entry,
        "matched_feign_edges": [x for x in topology.get("feign_edges", []) if entry_lower in json.dumps(x, ensure_ascii=False).lower()],
        "matched_apis": [x for x in apis if entry_lower in json.dumps(x, ensure_ascii=False).lower()],
        "matched_feigns": [x for x in feigns if entry_lower in json.dumps(x, ensure_ascii=False).lower()],
        "matched_mq": [x for x in mq if entry_lower in json.dumps(x, ensure_ascii=False).lower()],
        "topology_hint": topology,
    }


def workspace_check_contract(workspace_file: str | Path, contract_file: str, change_type: str) -> Dict[str, Any]:
    _, store = load_context(workspace_file)
    files = store.read_json("file-index.json", [])
    feigns = store.read_json("feign-index.json", [])
    mq = store.read_json("mq-index.json", [])
    basename = Path(contract_file).stem.lower()
    affected = []
    for item in files:
        text = item.get("path", "").lower()
        if basename in text or "common-api" in text or "message" in text or "dto" in text:
            affected.append(item)
    return {
        "contract_file": contract_file,
        "change_type": change_type,
        "affected_candidates": affected[:50],
        "related_feigns": [x for x in feigns if basename in json.dumps(x, ensure_ascii=False).lower()][:20],
        "related_mq": [x for x in mq if basename in json.dumps(x, ensure_ascii=False).lower()][:20],
        "rules": match_rules(store, intent=f"contract {change_type} {contract_file}", files=[contract_file], scopes=["contract", "dto", "feign", "message"]),
        "required_checks": [
            "全 workspace 搜索字段引用点",
            "确认历史 MQ 消息反序列化兼容",
            "确认 Feign 调用方请求/响应兼容",
            "新增字段提供默认值，删除字段需要灰度和兼容周期",
        ],
    }


def workspace_check_rules(workspace_file: str | Path, projects: List[str] | None, change_type: str, files: List[str] | None) -> Dict[str, Any]:
    _, store = load_context(workspace_file)
    intent = f"{change_type} {' '.join(projects or [])} {' '.join(files or [])}"
    rules = match_rules(store, intent=intent, files=files or [], scopes=[change_type])
    return {"projects": projects or [], "change_type": change_type, "files": files or [], "rules": rules}


def workspace_record_case(workspace_file: str | Path, task: str, projects: List[str], files: List[str], flow: str = "", risk_points: List[str] | None = None, verified_by: List[str] | None = None) -> Dict[str, Any]:
    _, store = load_context(workspace_file)
    item = {
        "task": task,
        "projects": projects,
        "files": files,
        "flow": flow,
        "risk_points": risk_points or [],
        "verified_by": verified_by or [],
    }
    store.append_jsonl("cross-service-task-memory.jsonl", item)
    return {"recorded": True, "case": item}


def tokenize(text: str) -> List[str]:
    raw = "".join(ch.lower() if ch.isalnum() or "\u4e00" <= ch <= "\u9fff" else " " for ch in text)
    words = [w for w in raw.split() if len(w) >= 2]
    # keep entire Chinese phrase fragments poorly but useful for mixed tasks
    for token in ["kafka", "rocketmq", "feign", "controller", "oldpubtime", "newpubtime", "es", "mongo", "redis", "nacos"]:
        if token in text.lower() and token not in words:
            words.append(token)
    return sorted(set(words))


def rank_files(file_index: List[Dict], symbols: List[Dict], keywords: List[str]) -> List[Dict]:
    symbol_by_file = {s["file"]: s for s in symbols}
    ranked = []
    for item in file_index:
        haystack = (item.get("path", "") + " " + json.dumps(symbol_by_file.get(item.get("path"), {}), ensure_ascii=False)).lower()
        score = sum(1 for k in keywords if k in haystack)
        path = item.get("path", "")
        if any(mark in path for mark in ["Consumer", "Listener", "Feign", "Controller", "Service", "Repository", "Mapper"]):
            score += 1
        if score > 0:
            ranked.append({**item, "score": score, "symbols": symbol_by_file.get(path, {})})
    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked

# ---- graph-native agent context tools --------------------------------------
from .graph import GraphStore


def _graph(workspace_file: str | Path) -> GraphStore:
    _, store = load_context(workspace_file)
    return GraphStore(store.graph_db_path)


def memory_query(workspace_file: str | Path, query: str, limit: int = 20, node_types: List[str] | None = None) -> Dict[str, Any]:
    """Graph-aware hybrid-lite query.

    The first public release uses deterministic graph/name/path lookup. It is
    intentionally explainable and works without embeddings. Optional semantic
    retrieval can be added later without changing this tool shape.
    """
    config, store = load_context(workspace_file)
    graph = GraphStore(store.graph_db_path)
    nodes = graph.find_nodes(query, types=node_types, limit=limit)
    if not nodes:
        seen_nodes = {}
        for token in tokenize(query):
            for item in graph.find_nodes(token, types=node_types, limit=limit):
                seen_nodes[item["id"]] = item
        nodes = list(seen_nodes.values())[:limit]
    expanded = []
    for node in nodes[: min(limit, 10)]:
        expanded.append({"node": node, "neighbors": graph.neighbors(node["id"], direction="both", max_depth=1, limit=20)})
    related_rules = match_rules(store, intent=query, files=[n.get("file_path", "") for n in nodes])[:10]
    cases = store.read_jsonl("cross-service-task-memory.jsonl", limit=200)
    related_cases = [c for c in cases if any(k in json.dumps(c, ensure_ascii=False).lower() for k in tokenize(query))][-5:]
    return {"workspace": config.workspace, "query": query, "matches": expanded, "related_rules": related_rules, "historical_cases": related_cases}


def memory_context(workspace_file: str | Path, name: str, max_depth: int = 2) -> Dict[str, Any]:
    graph = _graph(workspace_file)
    matches = graph.find_nodes(name, limit=10)
    if not matches:
        return {"name": name, "found": False, "matches": []}
    node = matches[0]
    return {
        "name": name,
        "found": True,
        "node": node,
        "incoming": graph.neighbors(node["id"], direction="upstream", max_depth=max_depth, limit=100),
        "outgoing": graph.neighbors(node["id"], direction="downstream", max_depth=max_depth, limit=100),
    }


def memory_impact(workspace_file: str | Path, target: str, direction: str = "upstream", max_depth: int = 3) -> Dict[str, Any]:
    _, store = load_context(workspace_file)
    graph = GraphStore(store.graph_db_path)
    matches = graph.find_nodes(target, limit=5)
    if not matches:
        return {"target": target, "found": False, "risk_level": "unknown", "impacts": []}
    node = matches[0]
    impacts = graph.neighbors(node["id"], direction=direction, max_depth=max_depth, limit=300)
    impacted_projects = sorted({x.get("source", {}).get("project") for x in impacts if x.get("source", {}).get("project")} | {x.get("target", {}).get("project") for x in impacts if x.get("target", {}).get("project")})
    risky_types = {"DTO", "FeignClient", "FeignMethod", "MQTopic", "MQConsumer", "Endpoint"}
    risk_level = "high" if node["type"] in risky_types or len(impacted_projects) >= 3 else "medium" if impacts else "low"
    rules = match_rules(store, intent=f"impact {target} {node['type']}", files=[node.get("file_path", "")])[:12]
    return {
        "target": node,
        "found": True,
        "direction": direction,
        "max_depth": max_depth,
        "risk_level": risk_level,
        "impacted_projects": impacted_projects,
        "impacts": impacts,
        "required_rules": rules,
        "review_checklist": _impact_checklist(node, risk_level),
    }


def memory_contracts(workspace_file: str | Path) -> Dict[str, Any]:
    _, store = load_context(workspace_file)
    return {
        "feign_contracts": store.read_json("feign-index.json", []),
        "mq_contracts": store.read_json("mq-index.json", []),
        "api_contracts": store.read_json("api-index.json", []),
        "rules": match_rules(store, intent="contract feign dto message api", scopes=["contract", "dto", "feign", "message"]),
    }


def memory_detect_changes(workspace_file: str | Path, scope: str = "staged") -> Dict[str, Any]:
    """Map git changes to graph nodes and risks.

    scope supports: staged, working, head. This command shells out only to local
    git and never sends code outside the machine.
    """
    import subprocess

    config, store = load_context(workspace_file)
    changed: List[str] = []
    for svc in config.services:
        repo = config.root_path / svc.path
        if not (repo / ".git").exists():
            continue
        cmd = ["git", "diff", "--name-only"]
        if scope == "staged":
            cmd = ["git", "diff", "--name-only", "--cached"]
        elif scope == "head":
            cmd = ["git", "diff", "--name-only", "HEAD~1..HEAD"]
        try:
            out = subprocess.check_output(cmd, cwd=repo, text=True, stderr=subprocess.DEVNULL)
            changed.extend([f"{svc.path}/{line.strip()}" for line in out.splitlines() if line.strip()])
        except Exception:
            continue
    file_index = store.read_json("file-index.json", [])
    matched_files = [f for f in file_index if f.get("path") in changed]
    changed_text = " ".join(changed)
    rules = match_rules(store, intent=f"git changes {changed_text}", files=changed)[:20]
    affected_projects = sorted({f.get("project") for f in matched_files})
    high_markers = ["common-api", "Feign", "Message", "Consumer", "Controller", "DTO", "application.yml", "bootstrap.yml"]
    risk_level = "high" if any(m in changed_text for m in high_markers) else "medium" if changed else "low"
    return {
        "scope": scope,
        "changed_files": changed,
        "matched_index_files": matched_files,
        "affected_projects": affected_projects,
        "risk_level": risk_level,
        "rules": rules,
        "review_checklist": [
            "检查公共 DTO / Feign / MQ Message 是否存在兼容性风险",
            "检查 Kafka/RocketMQ 消费是否幂等、可重试、可观测",
            "检查 ES/Mongo/DB 写入是否具备失败明细与补偿策略",
            "检查日志是否包含 chainId、siteCode、uid、业务主键",
        ],
    }


def _impact_checklist(node: Dict[str, Any], risk_level: str) -> List[str]:
    base = ["确认上游调用方", "确认下游实现方", "确认是否需要联调或回放历史消息"]
    if node["type"] in {"FeignClient", "FeignMethod", "DTO"}:
        base += ["公共契约变更必须检查所有消费者", "字段删除/改义必须保留兼容周期"]
    if node["type"] in {"MQTopic", "MQConsumer"}:
        base += ["检查重复消费幂等", "检查失败重试/死信/补偿", "检查历史消息反序列化兼容"]
    if risk_level == "high":
        base += ["建议生成变更影响报告并在 PR 中附上"]
    return base
