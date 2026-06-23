from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import load_workspace_config
from .graph import GraphStore
from .orchestrator import memory_query, workspace_status
from .semantic import SEMANTIC_INDEX_FILE, semantic_index_stats
from .store import WorkspaceStore
from .workspace_shape import analyze_workspace_shape


def doctor(workspace_file: str | Path, self_test: bool = False) -> dict[str, Any]:
    """Validate workspace configuration, generated indexes, graph health and optional query smoke test."""
    config = load_workspace_config(workspace_file)
    store = WorkspaceStore(workspace_file)
    checks: list[dict[str, Any]] = []
    advisories: list[dict[str, Any]] = []

    checks.append(_check("workspace_file_exists", Path(workspace_file).expanduser().exists(), str(workspace_file)))
    checks.append(_check("root_exists", config.root_path.exists(), str(config.root_path)))

    for service in config.services:
        path = config.resolve_service_path(service)
        checks.append(_check(f"service_path:{service.name}", path.exists(), str(path)))

    for name in [
        "file-index.json",
        "java-symbol-index.json",
        "api-index.json",
        "feign-index.json",
        "mq-index.json",
        "config-index.json",
        "service-topology.json",
        SEMANTIC_INDEX_FILE,
    ]:
        p = store.index_dir / name
        checks.append(_check(f"index:{name}", p.exists(), str(p)))

    with GraphStore(store.graph_db_path) as graph:
        counts = graph.counts()
        # Surface the actual PRAGMA state so doctor users can tell at a
        # glance whether their SQLite connection is tuned for reindex
        # throughput (WAL, large cache, MEMORY temp store, mmap).
        from .storage.pragmas import read_pragma_state

        pragma_state = read_pragma_state(graph.connect())
    checks.append(_check("graph:nodes", counts.get("nodes", 0) > 0, str(counts)))
    checks.append(_check("graph:edges", counts.get("edges", 0) > 0, str(counts)))
    checks.append(
        _check(
            "graph:pragma_wal",
            str(pragma_state.get("journal_mode", "")).lower() == "wal",
            f"journal_mode={pragma_state.get('journal_mode')}",
        )
    )
    semantic = semantic_index_stats(workspace_file)
    checks.append(_check("semantic:docs", semantic.get("doc_count", 0) > 0, str(semantic)))
    workspace_shape = analyze_workspace_shape(config)
    checks.append(
        _check(
            "workspace_shape:service_roots",
            workspace_shape.get("warning_count", 0) == 0,
            f"risk={workspace_shape.get('risk_level', 'unknown')}, warnings={workspace_shape.get('warning_count', 0)}",
        )
    )
    if workspace_shape.get("warnings"):
        advisories.extend(
            {
                "category": "workspace_shape",
                "severity": item.get("severity", "medium"),
                "code": item.get("code", ""),
                "message": item.get("message", ""),
            }
            for item in workspace_shape.get("warnings", [])
        )

    smoke: dict[str, Any] | None = None
    if self_test:
        status = workspace_status(workspace_file)
        query_text = config.services[0].name if config.services else config.workspace
        query = memory_query(workspace_file, query_text, limit=5)
        smoke = {"status_ok": bool(status.get("workspace")), "query": query_text, "query_matches": len(query.get("matches", []))}
        checks.append(_check("self_test:status", smoke["status_ok"], "workspace_status returned"))
        checks.append(_check("self_test:query", smoke["query_matches"] > 0, f"memory_query matched {query_text!r}"))

    failed = [item for item in checks if not item["ok"]]
    suggested_fixes = workspace_shape.get("recommendations", [])
    if failed:
        hint = "Run `memory-center reindex --workspace <workspace.yaml>` after fixing failed checks."
        if suggested_fixes:
            hint += " 先处理 workspace service root 冲突，再重建索引会更稳。"
    else:
        hint = "Workspace looks ready."
    return {
        "workspace": config.workspace,
        "ok": not failed,
        "checks": checks,
        "workspace_shape": workspace_shape,
        "advisories": advisories,
        "suggested_fixes": suggested_fixes,
        "self_test": smoke,
        "hint": hint,
        "sqlite_pragmas": pragma_state,
    }


def _check(name: str, ok: bool, detail: str) -> dict[str, Any]:
    return {"name": name, "ok": bool(ok), "detail": detail}
