from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ..graph import GraphStore
from ..store import WorkspaceStore

JAVA_CALL_CASE_FIELDS = {
    "case_id",
    "source",
    "expected_target",
    "project",
    "min_confidence",
    "expected_resolution_levels",
    "allowed_targets",
    "forbidden_targets",
}


@dataclass(frozen=True)
class JavaCallResolutionCase:
    case_id: str
    source: str
    expected_target: str
    project: str = ""
    min_confidence: float = 0.85
    expected_resolution_levels: tuple[str, ...] = ()
    allowed_targets: tuple[str, ...] = ()
    forbidden_targets: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "JavaCallResolutionCase":
        unsupported = sorted(set(data) - JAVA_CALL_CASE_FIELDS)
        if unsupported:
            raise ValueError(f"unsupported java call case fields: {', '.join(unsupported)}")
        case_id = str(data.get("case_id", "") or "").strip()
        source = _validate_anchor(data.get("source", ""), "source")
        expected_target = _validate_anchor(data.get("expected_target", ""), "expected_target")
        if not case_id:
            raise ValueError("case_id is required")
        return cls(
            case_id=case_id,
            source=source,
            expected_target=expected_target,
            project=str(data.get("project", "") or "").strip(),
            min_confidence=max(0.0, min(1.0, float(data.get("min_confidence", 0.85) or 0.85))),
            expected_resolution_levels=_string_tuple(data.get("expected_resolution_levels", [])),
            allowed_targets=_anchor_tuple(data.get("allowed_targets", []), "allowed_targets"),
            forbidden_targets=_anchor_tuple(data.get("forbidden_targets", []), "forbidden_targets"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "source": self.source,
            "expected_target": self.expected_target,
            "project": self.project,
            "min_confidence": self.min_confidence,
            "expected_resolution_levels": list(self.expected_resolution_levels),
            "allowed_targets": list(self.allowed_targets),
            "forbidden_targets": list(self.forbidden_targets),
        }


def load_java_call_resolution_cases(cases_file: str | Path) -> list[JavaCallResolutionCase]:
    path = Path(cases_file).expanduser().resolve()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if set(data) - {"schema_version", "cases"}:
        raise ValueError("java call resolution suite only supports schema_version and cases")
    rows = data.get("cases", [])
    if not isinstance(rows, list):
        raise ValueError("cases must be a list")
    cases = [JavaCallResolutionCase.from_mapping(row) for row in rows if isinstance(row, dict)]
    if not cases:
        raise ValueError("java call resolution suite requires at least one case")
    ids = [case.case_id for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("java call resolution case_id values must be unique")
    return cases


def run_java_call_resolution_suite(
    workspace_file: str | Path,
    cases_file: str | Path,
    *,
    min_recall: float = 0.90,
    min_confidence_rate: float = 0.85,
    max_unresolved_rate: float = 0.10,
    fail_on_unexpected_high_confidence: bool = False,
    fail_on_forbidden_high_confidence: bool = False,
) -> dict[str, Any]:
    cases = load_java_call_resolution_cases(cases_file)
    store = WorkspaceStore(workspace_file)
    case_results: list[dict[str, Any]] = []
    with GraphStore(store.graph_db_path) as graph:
        conn = graph.connect()
        for case in cases:
            case_results.append(_evaluate_case(conn, case))

    case_count = len(case_results)
    found_count = sum(1 for row in case_results if row["target_found"])
    confidence_count = sum(1 for row in case_results if row["confidence_passed"])
    resolution_count = sum(1 for row in case_results if row["resolution_level_passed"])
    unresolved_count = sum(1 for row in case_results if row["unresolved"])
    unexpected_count = sum(len(row["unexpected_high_confidence_edges"]) for row in case_results)
    allowed_count = sum(len(row["allowed_high_confidence_edges"]) for row in case_results)
    forbidden_count = sum(len(row["forbidden_high_confidence_edges"]) for row in case_results)
    recall = found_count / case_count if case_count else 0.0
    confidence_rate = confidence_count / case_count if case_count else 0.0
    resolution_rate = resolution_count / case_count if case_count else 0.0
    unresolved_rate = unresolved_count / case_count if case_count else 0.0
    passed = (
        recall >= min_recall
        and confidence_rate >= min_confidence_rate
        and unresolved_rate <= max_unresolved_rate
        and (not fail_on_unexpected_high_confidence or unexpected_count == 0)
        and (not fail_on_forbidden_high_confidence or forbidden_count == 0)
    )
    return {
        "schema_version": 1,
        "suite": "java_call_resolution",
        "summary": {
            "case_count": case_count,
            "passed_cases": sum(1 for row in case_results if row["passed"]),
            "edge_recall": round(recall, 4),
            "high_confidence_expected_rate": round(confidence_rate, 4),
            "resolution_level_rate": round(resolution_rate, 4),
            "unresolved_rate": round(unresolved_rate, 4),
            "unexpected_high_confidence_edge_count": unexpected_count,
            "allowed_high_confidence_edge_count": allowed_count,
            "forbidden_high_confidence_edge_count": forbidden_count,
            "passed": passed,
        },
        "thresholds": {
            "min_recall": min_recall,
            "min_confidence_rate": min_confidence_rate,
            "max_unresolved_rate": max_unresolved_rate,
            "fail_on_unexpected_high_confidence": fail_on_unexpected_high_confidence,
            "fail_on_forbidden_high_confidence": fail_on_forbidden_high_confidence,
        },
        "cases": case_results,
    }


def review_java_call_resolution_suite(
    workspace_file: str | Path,
    cases_file: str | Path,
    *,
    limit: int = 200,
) -> dict[str, Any]:
    """List unclassified high-confidence calls using logical anchors only."""

    cases = load_java_call_resolution_cases(cases_file)
    store = WorkspaceStore(workspace_file)
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    with GraphStore(store.graph_db_path) as graph:
        conn = graph.connect()
        for case in cases:
            result = _evaluate_case(conn, case)
            for edge in result["unexpected_high_confidence_edges"]:
                key = (
                    str(edge.get("source") or case.source),
                    str(edge.get("target") or ""),
                    str(edge.get("resolution_level") or ""),
                )
                record = grouped.setdefault(
                    key,
                    {
                        "source": key[0],
                        "target": key[1],
                        "resolution_level": key[2],
                        "confidence": 0.0,
                        "case_ids": [],
                        "expected_targets": [],
                        "review_status": "unclassified",
                    },
                )
                record["confidence"] = max(float(record["confidence"]), float(edge.get("confidence", 0.0) or 0.0))
                if case.case_id not in record["case_ids"]:
                    record["case_ids"].append(case.case_id)
                if case.expected_target not in record["expected_targets"]:
                    record["expected_targets"].append(case.expected_target)

    items = sorted(
        grouped.values(),
        key=lambda item: (-float(item["confidence"]), item["source"], item["target"], item["resolution_level"]),
    )
    for item in items:
        item["confidence"] = round(float(item["confidence"]), 4)
        item["case_ids"].sort()
        item["expected_targets"].sort()
    resolution_level_counts: dict[str, int] = {}
    for item in items:
        level = str(item["resolution_level"] or "unknown")
        resolution_level_counts[level] = resolution_level_counts.get(level, 0) + 1
    return {
        "schema_version": 1,
        "suite": "java_call_resolution_review",
        "summary": {
            "case_count": len(cases),
            "unclassified_high_confidence_edge_count": len(items),
            "returned_count": min(max(0, limit), len(items)),
            "resolution_level_counts": dict(sorted(resolution_level_counts.items())),
        },
        "items": items[: max(0, limit)],
        "next_action": "Classify each item into the case's allowed_targets or forbidden_targets; do not add filesystem paths or source snippets.",
    }


def _evaluate_case(conn: sqlite3.Connection, case: JavaCallResolutionCase) -> dict[str, Any]:
    source_name = _method_node_name(case.source)
    expected_target_name = _method_node_name(case.expected_target)
    sources = _find_method_nodes(conn, source_name, project=case.project)
    outgoing_edges = _load_call_edges(conn, [row["id"] for row in sources])
    matched_edges = [edge for edge in outgoing_edges if edge.get("target_name") == expected_target_name]
    best_match = _best_edge(matched_edges)
    target_found = best_match is not None
    confidence = float(best_match.get("confidence", 0.0)) if best_match else 0.0
    metadata = _json_dict(best_match.get("metadata_json")) if best_match else {}
    resolution_level = str(metadata.get("resolution_level", "") or "")
    confidence_passed = target_found and confidence >= case.min_confidence
    resolution_level_passed = (
        target_found
        and (not case.expected_resolution_levels or resolution_level in set(case.expected_resolution_levels))
    )
    allowed_names = _target_names(case.allowed_targets)
    forbidden_names = _target_names(case.forbidden_targets)
    unexpected_high_confidence = [
        _edge_summary(edge)
        for edge in outgoing_edges
        if float(edge.get("confidence", 0.0) or 0.0) >= case.min_confidence
        and edge.get("target_name") not in {expected_target_name, *allowed_names, *forbidden_names}
    ]
    allowed_high_confidence = [
        _edge_summary(edge)
        for edge in outgoing_edges
        if float(edge.get("confidence", 0.0) or 0.0) >= case.min_confidence
        and edge.get("target_name") in allowed_names
    ]
    forbidden_high_confidence = [
        _edge_summary(edge)
        for edge in outgoing_edges
        if float(edge.get("confidence", 0.0) or 0.0) >= case.min_confidence
        and edge.get("target_name") in forbidden_names
    ]
    unresolved = (not target_found) or resolution_level == "unresolved"
    passed = target_found and confidence_passed and resolution_level_passed and not unresolved
    return {
        "case_id": case.case_id,
        "source": case.source,
        "expected_target": case.expected_target,
        "source_candidates": len(sources),
        "call_edge_count": len(outgoing_edges),
        "target_found": target_found,
        "confidence": round(confidence, 4),
        "min_confidence": case.min_confidence,
        "confidence_passed": confidence_passed,
        "resolution_level": resolution_level,
        "expected_resolution_levels": list(case.expected_resolution_levels),
        "allowed_targets": list(case.allowed_targets),
        "forbidden_targets": list(case.forbidden_targets),
        "resolution_level_passed": resolution_level_passed,
        "unresolved": unresolved,
        "unexpected_high_confidence_edges": unexpected_high_confidence,
        "allowed_high_confidence_edges": allowed_high_confidence,
        "forbidden_high_confidence_edges": forbidden_high_confidence,
        "matched_edge": _edge_summary(best_match) if best_match else None,
        "passed": passed,
    }


def _find_method_nodes(conn: sqlite3.Connection, name: str, *, project: str = "") -> list[sqlite3.Row]:
    sql = "SELECT * FROM nodes WHERE type='Method' AND name=?"
    args: list[Any] = [name]
    if project:
        sql += " AND project=?"
        args.append(project)
    rows = conn.execute(sql, args).fetchall()
    if rows or not project:
        return list(rows)
    return list(conn.execute("SELECT * FROM nodes WHERE type='Method' AND name=?", (name,)).fetchall())


def _load_call_edges(conn: sqlite3.Connection, source_ids: Sequence[str]) -> list[dict[str, Any]]:
    if not source_ids:
        return []
    placeholders = ",".join("?" for _ in source_ids)
    sql = f"""
        SELECT
          e.id,
          e.source_id,
          e.target_id,
          e.type,
          e.confidence,
          e.metadata_json,
          s.name AS source_name,
          s.project AS source_project,
          t.name AS target_name,
          t.project AS target_project
        FROM edges e
        JOIN nodes s ON s.id=e.source_id
        JOIN nodes t ON t.id=e.target_id
        WHERE e.type='CALLS_METHOD' AND e.source_id IN ({placeholders})
    """
    return [dict(row) for row in conn.execute(sql, list(source_ids)).fetchall()]


def _best_edge(edges: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    if not edges:
        return None
    return max(edges, key=lambda edge: float(edge.get("confidence", 0.0) or 0.0))


def _edge_summary(edge: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not edge:
        return None
    metadata = _json_dict(edge.get("metadata_json"))
    return {
        "source": _anchor_from_method_name(edge.get("source_name", "")),
        "target": _anchor_from_method_name(edge.get("target_name", "")),
        "confidence": round(float(edge.get("confidence", 0.0) or 0.0), 4),
        "resolution_level": metadata.get("resolution_level", ""),
        "target_fqcn": metadata.get("target_fqcn", ""),
    }


def _json_dict(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(str(raw or "{}"))
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _validate_anchor(raw: Any, field: str) -> str:
    value = str(raw or "").strip()
    if not value:
        raise ValueError(f"{field} is required")
    if value.startswith(("/", "~")) or "\\" in value:
        raise ValueError(f"{field} must be a logical anchor, not a filesystem path")
    if "#" not in value and "." not in value:
        raise ValueError(f"{field} must look like Class#method or Class.method")
    return value


def _method_node_name(anchor: str) -> str:
    text = anchor.strip()
    if "#" in text:
        owner, method = text.split("#", 1)
        return f"{owner.strip()}.{method.strip()}"
    return text


def _target_names(anchors: Sequence[str]) -> set[str]:
    return {_method_node_name(anchor) for anchor in anchors}


def _anchor_from_method_name(name: Any) -> str:
    text = str(name or "").strip()
    if "." not in text:
        return text
    owner, method = text.rsplit(".", 1)
    return f"{owner}#{method}"


def _string_tuple(raw: Any) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, (list, tuple)):
        raise ValueError("expected_resolution_levels must be a list")
    return tuple(str(value).strip() for value in raw if str(value).strip())


def _anchor_tuple(raw: Any, field: str) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, (list, tuple)):
        raise ValueError(f"{field} must be a list")
    return tuple(_validate_anchor(value, field) for value in raw)
