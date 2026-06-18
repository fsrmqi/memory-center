from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping


_CASE_FIELDS = {
    "case_id",
    "query",
    "mode",
    "expected_anchors",
    "expected_edges",
    "forbidden_anchors",
    "max_latency_ms",
}


@dataclass(frozen=True)
class GoldenCase:
    case_id: str
    query: str
    mode: str
    expected_anchors: tuple[str, ...]
    expected_edges: tuple[str, ...]
    forbidden_anchors: tuple[str, ...] = ()
    max_latency_ms: float = 5000.0

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "GoldenCase":
        unsupported = sorted(set(data) - _CASE_FIELDS)
        if unsupported:
            raise ValueError(f"unsupported fields: {', '.join(unsupported)}")
        case_id = str(data.get("case_id", "") or "").strip()
        query = str(data.get("query", "") or "").strip()
        mode = str(data.get("mode", "walkthrough") or "walkthrough").strip().lower()
        if not case_id or not query:
            raise ValueError("case_id and query are required")
        if mode not in {"walkthrough", "hybrid"}:
            raise ValueError(f"unsupported golden mode: {mode}")
        return cls(
            case_id=case_id,
            query=query,
            mode=mode,
            expected_anchors=_logical_values(data.get("expected_anchors", [])),
            expected_edges=_logical_values(data.get("expected_edges", [])),
            forbidden_anchors=_logical_values(data.get("forbidden_anchors", [])),
            max_latency_ms=max(1.0, float(data.get("max_latency_ms", 5000.0) or 5000.0)),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "case_id": self.case_id,
            "query": self.query,
            "mode": self.mode,
            "expected_anchors": list(self.expected_anchors),
            "expected_edges": list(self.expected_edges),
            "forbidden_anchors": list(self.forbidden_anchors),
            "max_latency_ms": self.max_latency_ms,
        }


def _logical_values(raw: Any) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, (list, tuple)):
        raise ValueError("golden anchors and edges must be lists")
    values = tuple(str(value).strip() for value in raw if str(value).strip())
    for value in values:
        if value.startswith(("/", "~")) or "\\" in value:
            raise ValueError("golden cases must use logical identifiers, not filesystem paths")
    return values
