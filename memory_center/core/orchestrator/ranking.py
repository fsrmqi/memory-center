"""排序与文本匹配原语:tokenize、RRF、best_match、节点类型优先级、文件排序。

从 shared.py 按独立职责拆出的纯函数簇(ADR-0002),不持有 workspace 状态。
"""
from __future__ import annotations

from typing import Any


def tokenize(text: str) -> list[str]:
    from memory_center.core.foundation.text import base_tokenize

    words = base_tokenize(text)
    for token in ["kafka", "rocketmq", "feign", "controller", "oldpubtime", "newpubtime", "es", "mongo", "redis", "nacos"]:
        if token in text.lower() and token not in words:
            words.append(token)
    return sorted(set(words))


def _rrf(rank: int, k: int = 60) -> float:
    return 1.0 / (k + rank)


def _best_match(matches: list[dict[str, Any]], query: str = "") -> dict[str, Any]:
    if not matches:
        return {}
    q = (query or "").lower()

    def key(item: dict[str, Any]):
        name = (item.get("name") or "").lower()
        exact = 0 if name == q or name.endswith("." + q) else 1
        return (exact, _node_type_priority(item.get("type")), len(item.get("id", "")))

    return sorted(matches, key=key)[0]


def _node_type_priority(node_type: str = "") -> int:
    priority = {
        "Class": 0, "FeignClient": 1, "FeignMethod": 2, "Method": 3,
        "Field": 4, "Endpoint": 5, "MQTopic": 6, "MQConsumer": 7,
        "ConfigKey": 8, "File": 20,
    }
    return priority.get(node_type, 10)


def _symbol_search_text(symbols: list[dict[str, Any]]) -> str:
    """Return the bounded, query-relevant surface of one file's symbols.

    Sniff and code search used to serialize every symbol payload for every file.
    On a large Java workspace that repeatedly encoded method-call and DTO detail
    that neither route returns, multiplying CPU and peak memory for each MCP
    process. Keep structural and callable names, which are the searchable
    contract for these routes, and leave detailed evidence to symbol/context
    lookup after a file is selected.
    """
    parts: list[str] = []
    for symbol in symbols:
        for field in ("project", "file", "package"):
            value = str(symbol.get(field, "") or "")
            if value:
                parts.append(value)
        for field in ("classes", "interfaces", "methods", "fields", "annotations", "imports", "config_usages", "data_resources"):
            value = symbol.get(field, []) or []
            if isinstance(value, dict):
                parts.extend(_searchable_symbol_value(key, item) for key, item in value.items())
            elif isinstance(value, list):
                parts.extend(_searchable_symbol_value(item) for item in value)
        for call in (symbol.get("method_calls", []) or []):
            if not isinstance(call, dict):
                continue
            parts.extend(
                str(call.get(field, "") or "")
                for field in ("owner_method", "method_name", "receiver", "receiver_type")
            )
    return " ".join(parts)


def _searchable_symbol_value(key: object, value: object = "") -> str:
    """Extract names from structured symbol fields without serializing payloads."""
    if isinstance(value, dict):
        parts = [str(key)]
        for field in ("name", "class_name", "method_name", "field_name", "type", "owner", "package", "path"):
            item = value.get(field, "")
            if isinstance(item, (str, int, float)) and item:
                parts.append(str(item))
        return " ".join(parts)
    if isinstance(key, dict):
        return _searchable_symbol_value("", key)
    if isinstance(value, (str, int, float)):
        return f"{key} {value}".strip()
    if isinstance(key, (str, int, float)):
        return str(key)
    return ""


def rank_files(file_index: list[dict], symbols: list[dict], keywords: list[str]) -> list[dict]:
    symbol_entries = {}
    for s in symbols:
        symbol_entries.setdefault(s["file"], []).append(s)
    ranked = []
    for item in file_index:
        path = item.get("path", "")
        file_syms = symbol_entries.get(path, [])
        haystack = f"{path} {_symbol_search_text(file_syms)}".lower()
        score = sum(1 for k in keywords if k in haystack)
        if any(mark in path for mark in ["Consumer", "Listener", "Feign", "Controller", "Service", "Repository", "Mapper"]):
            score += 1
        if score > 0:
            ranked.append({**item, "score": score, "symbols": file_syms})
    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked
