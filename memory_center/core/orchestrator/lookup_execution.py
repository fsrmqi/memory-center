"""Hybrid retrieval execution isolated from lookup orchestration."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from memory_center.core.storage.runtime import RuntimeStore
from memory_center.core.storage.workspace import WorkspaceStore


def execute_hybrid_retrieval(
    store: WorkspaceStore,
    workspace_file: str | Path,
    query: str,
    *,
    config: Any,
    node_types: list[str] | None,
    limit: int,
    freshness: dict[str, Any],
    learned_weights: dict[str, Any],
    effective_project: str,
) -> tuple[dict[str, Any], bool, bool]:
    """Run the bounded retrieval against a project shard or global graph."""
    from ..retrieval.hybrid import hybrid_retrieve

    graph_path = store.graph_db_path
    shard_graph_used = False
    shard_available = True
    if effective_project:
        try:
            from ..indexing.control_plane import index_control_status
            from ..indexing.shards import service_shard_graph_path

            generation = str(index_control_status(store).get("active_generation", "") or "")
            shard_path = service_shard_graph_path(store, generation, effective_project) if generation else None
            if shard_path:
                graph_path = shard_path
                shard_graph_used = True
            else:
                # 后台定向刷新与查询并发时，active_generation 可能已写入而 shard
                # 文件尚未落盘（发布中间态）。短退避后重读一次 generation 与
                # shard 路径，跨过中间态；仍缺失才视为 shard 未发布。
                import time as _time

                _time.sleep(0.05)
                generation = str(index_control_status(store).get("active_generation", "") or "")
                shard_path = service_shard_graph_path(store, generation, effective_project) if generation else None
                if shard_path:
                    graph_path = shard_path
                    shard_graph_used = True
                else:
                    shard_available = False
        except Exception:
            shard_available = False
    if not shard_available:
        return ({
            "results": [], "total_found": 0, "returned": 0,
            "retrieval_summary": {"total": 0, "reason": "service_shard_not_published"},
            "progressive": {"summary": [], "details": [], "evidence": []},
            "index_scope_unavailable": True, "index_source": "service_shard_unavailable",
        }, shard_graph_used, shard_available)
    with RuntimeStore(graph_path) as graph:
        result = hybrid_retrieve(
            graph=graph, workspace_file=str(workspace_file), query=query, config=config,
            node_types=node_types, limit=limit, freshness=freshness, learned_weights=learned_weights,
        )
    result["index_source"] = "service_graph_shard" if shard_graph_used else "global_graph"
    return result, shard_graph_used, shard_available


__all__ = ["execute_hybrid_retrieval"]
