from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from .config import load_workspace_config
from .graph import GraphStore
from .orchestrator import memory_query, workspace_status
from .store import WorkspaceStore


def doctor(workspace_file: str | Path, self_test: bool = False) -> Dict[str, Any]:
    """Validate workspace configuration, generated indexes, graph health and optional query smoke test."""
    config = load_workspace_config(workspace_file)
    store = WorkspaceStore(workspace_file)
    checks: List[Dict[str, Any]] = []

    checks.append(_check("workspace_file_exists", Path(workspace_file).expanduser().exists(), str(workspace_file)))
    checks.append(_check("root_exists", config.root_path.exists(), str(config.root_path)))

    for service in config.services:
        path = config.root_path / service.path
        checks.append(_check(f"service_path:{service.name}", path.exists(), str(path)))

    for name in [
        "file-index.json",
        "java-symbol-index.json",
        "api-index.json",
        "feign-index.json",
        "mq-index.json",
        "config-index.json",
        "service-topology.json",
    ]:
        p = store.index_dir / name
        checks.append(_check(f"index:{name}", p.exists(), str(p)))

    graph = GraphStore(store.graph_db_path)
    counts = graph.counts()
    checks.append(_check("graph:nodes", counts.get("nodes", 0) > 0, str(counts)))
    checks.append(_check("graph:edges", counts.get("edges", 0) > 0, str(counts)))

    smoke: Dict[str, Any] | None = None
    if self_test:
        status = workspace_status(workspace_file)
        query_text = config.services[0].name if config.services else config.workspace
        query = memory_query(workspace_file, query_text, limit=5)
        smoke = {"status_ok": bool(status.get("workspace")), "query": query_text, "query_matches": len(query.get("matches", []))}
        checks.append(_check("self_test:status", smoke["status_ok"], "workspace_status returned"))
        checks.append(_check("self_test:query", smoke["query_matches"] > 0, f"memory_query matched {query_text!r}"))

    failed = [item for item in checks if not item["ok"]]
    return {
        "workspace": config.workspace,
        "ok": not failed,
        "checks": checks,
        "self_test": smoke,
        "hint": "Run `memory-center reindex --workspace <workspace.yaml>` after fixing failed checks." if failed else "Workspace looks ready.",
    }


def _check(name: str, ok: bool, detail: str) -> Dict[str, Any]:
    return {"name": name, "ok": bool(ok), "detail": detail}
