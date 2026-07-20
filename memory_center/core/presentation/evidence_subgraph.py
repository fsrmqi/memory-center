"""Bounded, explicit evidence subgraph exports for one analysis target."""
from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from memory_center.core.knowledge.assertions import ASSERTION_INDEX_FILE, assertion_id_for
from memory_center.core.presentation.conclusion_cards import build_conclusion_cards
from memory_center.core.storage.graph import GraphStore
from memory_center.core.storage.workspace import WorkspaceStore

_MAX_DEPTH = 3
_MAX_EDGES = 120
_MAX_NODES = 80


def export_evidence_subgraph(
    workspace_file: str | Path,
    target: str,
    *,
    direction: str = "both",
    max_depth: int = 2,
    max_edges: int = 60,
    output_format: str = "json",
) -> dict[str, Any]:
    """Build a small graph export without reading the full graph or source files."""
    normalized_format = output_format.strip().lower()
    if normalized_format not in {"json", "markdown", "html"}:
        raise ValueError("output_format must be one of: json, markdown, html")
    bounded_depth = min(max(1, max_depth), _MAX_DEPTH)
    bounded_edges = min(max(1, max_edges), _MAX_EDGES)
    store = WorkspaceStore(workspace_file)
    with GraphStore(store.graph_db_path) as graph:
        root = graph.node_by_id(target) or _first_match(graph, target)
        if not root:
            return {
                "found": False,
                "target": target,
                "format": normalized_format,
                "limits": _limits(bounded_depth, bounded_edges),
                "reason": "target_not_found",
            }
        edges = graph.neighbors(root["id"], direction=direction, max_depth=bounded_depth, limit=bounded_edges)

    nodes_by_id = {root["id"]: _node(root, is_root=True)}
    assertion_generation = str(store.read_json_prefer_backend(ASSERTION_INDEX_FILE, {}).get("generation", "") or "")
    exported_edges: list[dict[str, Any]] = []
    for edge in edges:
        for side, id_key in (("source", "source_id"), ("target", "target_id")):
            item = edge.get(side, {}) or {}
            node_id = str(edge.get(id_key, "") or "")
            if node_id and len(nodes_by_id) < _MAX_NODES:
                nodes_by_id.setdefault(node_id, _node({"id": node_id, **item}))
        if edge.get("source_id") in nodes_by_id and edge.get("target_id") in nodes_by_id:
            exported_edges.append(_edge(edge, assertion_generation=assertion_generation))

    assertion_statuses = store.memory_backend().assertion_statuses(
        [str(edge.get("assertion_ref", "") or "") for edge in exported_edges]
    )
    for edge in exported_edges:
        assertion_ref = str(edge.get("assertion_ref", "") or "")
        if assertion_ref in assertion_statuses:
            edge["assertion_status"] = assertion_statuses[assertion_ref]
    payload = {
        "schema_version": 1,
        "kind": "evidence_subgraph",
        "found": True,
        "target": _node(root, is_root=True),
        "direction": direction,
        "limits": _limits(bounded_depth, bounded_edges),
        "nodes": list(nodes_by_id.values()),
        "edges": exported_edges,
        "conclusion_cards": build_conclusion_cards(exported_edges),
        "governance_assertions": _governance_assertions_for_target(store, root["id"]),
        "evidence_boundary": "仅导出目标及有界邻接边；不读取源码、不扫描全图、不包含原始工具载荷。",
    }
    payload["content"] = _render(payload, normalized_format)
    payload["format"] = normalized_format
    return payload


def _first_match(graph: GraphStore, target: str) -> dict[str, Any] | None:
    matches = graph.find_nodes(target, limit=1)
    return matches[0] if matches else None


def _governance_assertions_for_target(store: WorkspaceStore, target_id: str) -> list[dict[str, Any]]:
    """Expose only governance assertions directly related to the exported node."""
    index = store.read_json_prefer_backend("governance-assertion-index.json", {}) or {}
    rows = index.get("recent", []) if isinstance(index, dict) else []
    return [
        row
        for row in rows
        if isinstance(row, dict) and target_id in {str(row.get("subject_id", "")), str(row.get("object_id", ""))}
    ][-20:]


def _node(item: dict[str, Any], *, is_root: bool = False) -> dict[str, Any]:
    return {
        "id": item.get("id", ""),
        "name": item.get("name", ""),
        "type": item.get("type", ""),
        "project": item.get("project", ""),
        "file_path": item.get("file_path", ""),
        "line": item.get("line", 0),
        "evidence_level": "EXTRACTED" if is_root else "INFERRED",
    }


def _edge(item: dict[str, Any], *, assertion_generation: str = "") -> dict[str, Any]:
    confidence = float(item.get("confidence", 0) or 0)
    result = {
        "id": item.get("id", ""),
        "source_id": item.get("source_id", ""),
        "target_id": item.get("target_id", ""),
        "type": item.get("type", ""),
        "confidence": confidence,
        "depth": item.get("depth", 0),
        "evidence_level": "EXTRACTED" if confidence >= 0.8 else "INFERRED",
    }
    if assertion_generation:
        result["assertion_ref"] = assertion_id_for(
            str(item.get("source_id", "")), str(item.get("type", "")), str(item.get("target_id", "")), assertion_generation
        )
    return result


def _limits(max_depth: int, max_edges: int) -> dict[str, int]:
    return {"max_depth": max_depth, "max_edges": max_edges, "max_nodes": _MAX_NODES}


def _render(payload: dict[str, Any], output_format: str) -> str:
    if output_format == "json":
        return json.dumps({key: value for key, value in payload.items() if key != "content"}, ensure_ascii=False, indent=2)
    lines = ["# 证据子图", "", f"目标：`{payload['target']['id']}`", "", "## 节点", ""]
    lines.extend(f"- `{node['id']}` · {node['type']} · {node['project']} · `{node['file_path']}` · {node['evidence_level']}" for node in payload["nodes"])
    lines.extend(["", "## 边", ""])
    lines.extend(f"- `{edge['source_id']}` --{edge['type']}--> `{edge['target_id']}` · {edge['evidence_level']} · confidence={edge['confidence']:.2f}" for edge in payload["edges"])
    markdown = "\n".join(lines) + "\n"
    if output_format == "markdown":
        return markdown
    return "<html><body><pre>" + html.escape(markdown) + "</pre></body></html>"
