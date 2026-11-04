"""按查询意图过滤 API/Feign/MQ 契约列表的辅助。

从 query.py 按独立职责拆出的契约过滤辅助(ADR-0002)。
"""
from __future__ import annotations

import json

from memory_center.core.assessment.quality import evidence_level_for
from memory_center.core.knowledge.ontology import EntityValidator

from .ranking import tokenize


def _filter_contracts_by_query(contracts: list, query: str, intent: str) -> list:
    """Filter contracts by query relevance with confidence scoring.

    Confidence levels (per ONTOLOGY.md §5.6):
    - 0.95: interface name exact match
    - 0.85: method name exact match
    - 0.60: token match in interface name
    - 0.30: token match in JSON dump
    """
    if not contracts:
        return []

    query_lower = query.lower()
    tokens = tokenize(query_lower)
    scored_matches: list[tuple[float, str, dict]] = []  # (confidence, match_type, contract)

    for contract in contracts:
        contract_str = json.dumps(contract, ensure_ascii=False).lower()

        if intent == "feign" and "interface" in contract:
            interface_name = contract.get("interface", "").lower()
            # EntityValidator boost: 确认是 Feign 实体时提升置信度 (§5.1)
            is_feign = EntityValidator.is_feign_entity(interface_name)
            # 接口名精确匹配
            if query_lower in interface_name or interface_name in query_lower:
                scored_matches.append((0.97 if is_feign else 0.95, "interface_exact", contract))
                continue
            # 方法名精确匹配
            method_matched = False
            for m in contract.get("methods", []):
                if query_lower in m.get("method_name", "").lower():
                    scored_matches.append((0.85, "method_exact", contract))
                    method_matched = True
                    break
            if method_matched:
                continue
            # Token 匹配
            if any(token in interface_name for token in tokens):
                scored_matches.append((0.60, "token_match", contract))
        elif intent == "endpoint" and "path" in contract:
            path = contract.get("path", "").lower()
            controller = contract.get("controller", "").lower()
            if query_lower in path or query_lower in controller:
                scored_matches.append((0.90, "path_exact", contract))
            elif any(token in path or token in controller for token in tokens):
                scored_matches.append((0.60, "token_match", contract))
        else:
            # 通用匹配 — JSON 全文扫描
            if any(token in contract_str for token in tokens):
                scored_matches.append((0.30, "json_scan", contract))

    # 按置信度降序排列
    scored_matches.sort(key=lambda x: x[0], reverse=True)

    if scored_matches:
        result = []
        for confidence, match_type, contract in scored_matches[:20]:
            enriched = dict(contract)
            enriched["_confidence"] = confidence
            enriched["_match_type"] = match_type
            enriched["_semantic_strength"] = _contract_semantic_strength(confidence)
            enriched["evidence_level"] = evidence_level_for(
                enriched, semantic_strength=enriched["_semantic_strength"]
            )
            enriched["_match_reason"] = _contract_match_reason(match_type, contract, query)
            result.append(enriched)
        return result

    return []


def _contract_semantic_strength(confidence: float) -> str:
    """Map contract confidence to semantic strength."""
    if confidence >= 0.90:
        return "fact"
    if confidence >= 0.60:
        return "inferred"
    return "derived"


def _contract_match_reason(match_type: str, contract: dict, query: str) -> str:
    """Generate human-readable match reason for a contract."""
    if match_type == "interface_exact":
        iface = contract.get("interface", "")
        return '接口名 [' + str(iface) + '] 与查询 [' + str(query) + '] 精确匹配'
    if match_type == "method_exact":
        methods = [m.get("method_name", "") for m in contract.get("methods", [])]
        matched = [m for m in methods if query.lower() in m.lower()]
        return '方法名 [' + str(matched[0] if matched else '?') + '] 与查询 [' + str(query) + '] 匹配'
    if match_type == "path_exact":
        path = contract.get("path", "")
        return '路径 [' + str(path) + '] 与查询 [' + str(query) + '] 匹配'
    if match_type == "token_match":
        return '查询词与契约字段部分匹配'
    if match_type == "json_scan":
        return '查询词在契约全文扫描中匹配'
    return '匹配类型: ' + match_type
