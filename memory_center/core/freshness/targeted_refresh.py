"""Bounded, query-time graph refresh for recently changed source files."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from ..graph import GraphEdge, GraphNode, GraphStore, edge_id, node_id
from ..indexer import parse_java_symbols, safe_read
from ..store import WorkspaceStore

MAX_REFRESH_FILES = 12


def refresh_query_targets(workspace_file: str | Path, query: str, limit: int = MAX_REFRESH_FILES) -> dict[str, Any]:
    """Refresh only stale indexed Java files plausibly related to ``query``."""
    started = time.perf_counter()
    store = WorkspaceStore(workspace_file)
    files = store.read_json_prefer_backend("file-index.json", [])
    tokens = [part.lower() for part in query.replace("#", " ").replace(".", " ").split() if len(part) > 2]
    candidates: list[dict[str, Any]] = []
    try:
        with GraphStore(store.graph_db_path) as graph:
            for node in graph.find_nodes(" ".join(tokens[:6]), types=["File", "Class", "Method"], limit=limit * 4):
                path = str(node.get("file_path", "") or "")
                if path:
                    candidates.append({"path": path})
    except Exception:
        pass
    for item in files:
        path = str(item.get("path", "") or "")
        if tokens and any(token in path.lower() for token in tokens):
            candidates.append(item)

    by_path = {str(item.get("path", "")): item for item in files}
    selected: list[dict[str, Any]] = []
    for candidate in candidates:
        path = str(candidate.get("path", "") or "")
        item = by_path.get(path, candidate)
        if path and item not in selected:
            selected.append(item)
        if len(selected) >= min(MAX_REFRESH_FILES, max(1, limit)):
            break

    refreshed: list[str] = []
    checked: list[str] = []
    graph_mtime = store.graph_db_path.stat().st_mtime_ns if store.graph_db_path.exists() else 0
    for item in selected:
        abs_path = Path(str(item.get("abs_path", "") or ""))
        rel = str(item.get("path", "") or "")
        if not abs_path.exists() or abs_path.suffix != ".java":
            continue
        checked.append(rel)
        indexed_mtime = int(item.get("source_mtime_ns", graph_mtime) or graph_mtime)
        stat = abs_path.stat()
        if stat.st_mtime_ns <= indexed_mtime and stat.st_size == int(item.get("source_size", stat.st_size) or stat.st_size):
            continue
        _refresh_java_graph(store, item, abs_path)
        refreshed.append(rel)
    return {
        "checked": len(checked),
        "refreshed": bool(refreshed),
        "files": refreshed,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        "mode": "targeted_overlay",
        "coalesced": False,
    }


def _refresh_java_graph(store: WorkspaceStore, item: dict[str, Any], source: Path) -> None:
    project = str(item.get("project", "") or "")
    rel = str(item.get("path", "") or "")
    symbol = parse_java_symbols(project, rel, safe_read(source))
    raw = symbol.__dict__
    file_id = node_id("File", rel)
    nodes = [GraphNode(file_id, "File", Path(rel).name, project, rel, metadata={**item, "source_mtime_ns": source.stat().st_mtime_ns, "source_size": source.stat().st_size, "hot_refreshed": True})]
    edges: list[GraphEdge] = []
    for cls in raw.get("classes", []) + raw.get("interfaces", []):
        class_id = node_id("Class", project, cls)
        nodes.append(GraphNode(class_id, "Class", cls, project, rel, int(raw.get("class_lines", {}).get(cls, 0) or 0), metadata={"hot_refreshed": True}))
        edges.append(GraphEdge(edge_id("DECLARES", file_id, class_id), file_id, class_id, "DECLARES"))
        for method in raw.get("methods", []):
            method_id = node_id("Method", project, cls, method)
            nodes.append(GraphNode(method_id, "Method", f"{cls}.{method}", project, rel, int(raw.get("method_lines", {}).get(method, 0) or 0), metadata={"method": method, "hot_refreshed": True}))
            edges.append(GraphEdge(edge_id("DECLARES", class_id, method_id), class_id, method_id, "DECLARES"))
    with GraphStore(store.graph_db_path) as graph:
        graph.partial_rebuild(nodes, edges, set(), [rel], preserve_incoming=True)
