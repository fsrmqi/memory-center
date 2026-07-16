"""Static contract snapshots, compatibility diffs, and release gates."""
from __future__ import annotations

from pathlib import Path
from typing import Any

CONTRACT_SNAPSHOT_FILE = "contract-snapshot.json"
CONTRACT_DIFF_FILE = "contract-diff.json"


def build_contract_snapshot(
    api_index: list[dict[str, Any]],
    feign_index: list[dict[str, Any]],
    mq_index: list[dict[str, Any]],
    symbol_index: list[dict[str, Any]],
) -> dict[str, Any]:
    apis = {
        _api_key(item): {"project": item.get("project", ""), "http_method": item.get("http_method", ""), "path": item.get("path", ""), "controller": item.get("controller", ""), "method_name": item.get("method_name", ""), "file": item.get("file", "")}
        for item in api_index
        if item.get("path")
    }
    feign = {}
    for client in feign_index:
        for method in client.get("methods", []) or []:
            key = "|".join(str(value) for value in (client.get("project", ""), client.get("interface", ""), method.get("method_name", ""), method.get("http_method", ""), method.get("path", "")))
            feign[key] = {"project": client.get("project", ""), "interface": client.get("interface", ""), "target_service": client.get("target_service", ""), "method_name": method.get("method_name", ""), "http_method": method.get("http_method", ""), "path": method.get("path", ""), "file": client.get("file", "")}
    mq = {}
    for item in mq_index:
        topic = str(item.get("topic", "") or item.get("topic_placeholder", "") or "")
        if topic:
            key = "|".join(str(value) for value in (item.get("project", ""), item.get("kind", ""), topic, item.get("class_name", ""), item.get("method_name", "")))
            mq[key] = {"project": item.get("project", ""), "kind": item.get("kind", ""), "topic": topic, "group": item.get("group", ""), "class_name": item.get("class_name", ""), "method_name": item.get("method_name", ""), "file": item.get("file", "")}
    dto = {}
    for symbol in symbol_index:
        for name in list(symbol.get("classes", []) or []) + list(symbol.get("interfaces", []) or []):
            if _looks_like_dto(name, symbol):
                dto[f"{symbol.get('project', '')}|{name}"] = {"project": symbol.get("project", ""), "name": name, "fields": dict(symbol.get("field_types", {}) or {}), "file": symbol.get("file", "")}
    return {"schema_version": 1, "apis": apis, "feign": feign, "mq": mq, "dto": dto}


def diff_contract_snapshots(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    changes: list[dict[str, Any]] = []
    for kind in ("apis", "feign", "mq"):
        before, after = previous.get(kind, {}) or {}, current.get(kind, {}) or {}
        for key in sorted(set(before) - set(after)):
            changes.append(_change(kind, "removed", before[key], severity="high"))
        for key in sorted(set(after) - set(before)):
            changes.append(_change(kind, "added", after[key], severity="low"))
    before_dto, after_dto = previous.get("dto", {}) or {}, current.get("dto", {}) or {}
    for key in sorted(set(before_dto) & set(after_dto)):
        before_fields, after_fields = before_dto[key].get("fields", {}), after_dto[key].get("fields", {})
        for field in sorted(set(before_fields) - set(after_fields)):
            changes.append(_change("dto", "field_removed", {**before_dto[key], "field": field, "field_type": before_fields[field]}, severity="high"))
        for field in sorted(set(after_fields) - set(before_fields)):
            changes.append(_change("dto", "field_added", {**after_dto[key], "field": field, "field_type": after_fields[field]}, severity="medium"))
        for field in sorted(set(before_fields) & set(after_fields)):
            if before_fields[field] != after_fields[field]:
                changes.append(_change("dto", "field_type_changed", {**after_dto[key], "field": field, "before_type": before_fields[field], "after_type": after_fields[field]}, severity="high"))
    for key in sorted(set(before_dto) - set(after_dto)):
        changes.append(_change("dto", "removed", before_dto[key], severity="high"))
    return {"schema_version": 1, "baseline_available": bool(previous), "changes": changes, "breaking_count": sum(1 for item in changes if item["severity"] == "high"), "warning_count": sum(1 for item in changes if item["severity"] == "medium")}


def contract_semantic_report(
    snapshot: dict[str, Any],
    diff: dict[str, Any],
    topology: dict[str, Any],
    contract_file: str = "",
) -> dict[str, Any]:
    target = Path(contract_file).stem.lower() if contract_file else ""
    service_names = {str(item.get("service_name", "") or ""): str(item.get("name", "") or "") for item in topology.get("services", []) or []}
    api_values = list((snapshot.get("apis", {}) or {}).values())
    feign_checks = []
    for item in (snapshot.get("feign", {}) or {}).values():
        if target and target not in str(item).lower():
            continue
        target_project = service_names.get(str(item.get("target_service", "") or ""), "")
        matched = [api for api in api_values if api.get("project") == target_project and api.get("http_method") == item.get("http_method") and api.get("path") == item.get("path")]
        feign_checks.append({"interface": item.get("interface", ""), "method": item.get("method_name", ""), "from_project": item.get("project", ""), "to_project": target_project, "status": "verified" if matched else "attention", "reason": "api_method_path_match" if matched else "server_endpoint_not_matched", "consumers": [item.get("project", "")]})
    topic_groups: dict[str, list[dict[str, Any]]] = {}
    for item in (snapshot.get("mq", {}) or {}).values():
        if target and target not in str(item).lower():
            continue
        topic_groups.setdefault(str(item.get("topic", "")), []).append(item)
    mq_checks = []
    for topic, rows in topic_groups.items():
        producers = [item.get("project", "") for item in rows if "producer" in str(item.get("kind", ""))]
        consumers = [item.get("project", "") for item in rows if "producer" not in str(item.get("kind", ""))]
        mq_checks.append({"topic": topic, "status": "verified" if producers and consumers else "attention", "producers": producers, "consumers": consumers})
    relevant_changes = [item for item in diff.get("changes", []) if not target or target in str(item).lower()]
    breaking = [item for item in relevant_changes if item.get("severity") == "high"]
    status = "block" if breaking else "attention" if any(item.get("status") == "attention" for item in feign_checks + mq_checks) else "pass"
    return {"status": status, "contract_file": contract_file, "baseline_available": bool(diff.get("baseline_available")), "breaking_changes": breaking[:50], "changes": relevant_changes[:100], "feign": feign_checks[:50], "mq": mq_checks[:50], "affected_consumers": sorted({consumer for item in feign_checks for consumer in item.get("consumers", [])} | {consumer for item in mq_checks for consumer in item.get("consumers", [])}), "required_actions": _actions(status, bool(diff.get("baseline_available")))}


def _api_key(item: dict[str, Any]) -> str:
    return "|".join(str(value) for value in (item.get("project", ""), item.get("http_method", ""), item.get("path", "")))


def _looks_like_dto(name: str, symbol: dict[str, Any]) -> bool:
    lower = name.lower()
    return any(token in lower for token in ("dto", "request", "response", "command", "event", "message", "vo")) or "dto" in str(symbol.get("file", "")).lower()


def _change(kind: str, change_type: str, subject: dict[str, Any], *, severity: str) -> dict[str, Any]:
    return {"kind": kind, "change_type": change_type, "severity": severity, "subject": subject, "breaking": severity == "high"}


def _actions(status: str, baseline_available: bool) -> list[str]:
    actions = []
    if not baseline_available:
        actions.append("当前为首个契约快照，仅建立基线；后续 reindex 才能比较语义变更。")
    if status == "block":
        actions.append("检测到破坏性契约变更，必须确认所有消费者兼容或提供迁移期后才能合并。")
    elif status == "attention":
        actions.append("存在未匹配服务端 API 或单向 MQ topic，请人工确认调用链和消费者。")
    else:
        actions.append("契约静态校验通过，仍建议执行消费者集成测试。")
    return actions
