"""检索排序的纯函数，不依赖编排或存储。"""
from __future__ import annotations

from typing import Any

from memory_center.core.foundation.text import base_tokenize


def reciprocal_rank(rank: int, k: int = 60) -> float:
    return 1.0 / (k + rank)


def best_match(matches: list[dict[str, Any]], query: str = "") -> dict[str, Any]:
    if not matches:
        return {}
    query = (query or "").lower()
    priority = {"Class": 0, "FeignClient": 1, "FeignMethod": 2, "Method": 3, "Field": 4, "Endpoint": 5, "MQTopic": 6, "MQConsumer": 7, "ConfigKey": 8, "File": 20}
    def rank(item: dict[str, Any]) -> tuple[int, int, int]:
        name = str(item.get("name", "") or "").lower()
        exact = 0 if name == query or name.endswith(f".{query}") else 1
        return exact, priority.get(str(item.get("type", "") or ""), 10), len(str(item.get("id", "") or ""))
    return min(matches, key=rank)


def tokenize(text: str) -> list[str]:
    return base_tokenize(text)


# Memory Center 领域词表：检索/重排时这些技术名词必须作为独立 token 参与匹配。
_DOMAIN_TOKENS = (
    "kafka", "rocketmq", "feign", "controller", "oldpubtime", "newpubtime", "es", "mongo", "redis", "nacos",
)


def tokenize_with_domain_terms(text: str) -> list[str]:
    """``base_tokenize`` plus Memory Center domain vocabulary."""
    words = base_tokenize(text)
    for token in _DOMAIN_TOKENS:
        if token in text.lower() and token not in words:
            words.append(token)
    return sorted(set(words))
