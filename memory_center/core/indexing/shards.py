"""Physical, versioned service and contract shards with legacy fallbacks."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from filelock import FileLock

from memory_center.core.storage.graph import GraphStore
from memory_center.core.storage.workspace import WorkspaceStore

GENERATIONS_DIR = "generations"


def write_generation_shards(
    store: WorkspaceStore,
    generation: str,
    *,
    file_index: list[dict[str, Any]],
    symbol_index: list[dict[str, Any]],
    api_index: list[dict[str, Any]],
    feign_index: list[dict[str, Any]],
    mq_index: list[dict[str, Any]],
    config_index: list[dict[str, Any]],
    topology: dict[str, Any],
    reuse_generation: str = "",
    affected_projects: set[str] | None = None,
) -> dict[str, Any]:
    """Build immutable shard files before the generation is activated."""
    root = store.index_dir / GENERATIONS_DIR / generation
    service_dir = root / "services"
    with FileLock(str(store.lock_file)):
        if root.exists():
            shutil.rmtree(root)
        previous = _generation_root(store, reuse_generation) if reuse_generation else None
        if previous and (previous / "services").exists():
            shutil.copytree(previous, root)
        service_dir.mkdir(parents=True, exist_ok=True)
        projects = sorted({str(item.get("project", "") or "") for item in file_index if item.get("project")})
        rebuild_projects = set(projects) if affected_projects is None else set(affected_projects)
        # An unresolvable filter must remain correct, so rebuild all instead
        # of publishing a generation that silently omits fresh source facts.
        if not rebuild_projects or not rebuild_projects.issubset(set(projects)):
            rebuild_projects = set(projects)
        service_files: dict[str, str] = {}
        with GraphStore(store.graph_db_path) as graph:
            for project in projects:
                service_files[project] = f"services/{_safe_name(project)}.json"
                if project not in rebuild_projects:
                    continue
                payload = {
                    "schema_version": 1,
                    "generation": generation,
                    "project": project,
                    "files": _by_project(file_index, project),
                    "symbols": _by_project(symbol_index, project, path_key="file"),
                    "apis": _by_project(api_index, project, path_key="file"),
                    "feigns": _by_project(feign_index, project, path_key="file"),
                    "mq": _by_project(mq_index, project, path_key="file"),
                    "configs": _by_project(config_index, project),
                }
                _atomic_json(service_dir / f"{_safe_name(project)}.json", payload)
                nodes, edges = graph.project_subgraph(project)
                shard_db = service_dir / f"{_safe_name(project)}.graph.db"
                with GraphStore(shard_db) as shard:
                    shard.clear()
                    shard.bulk_write(nodes, edges)
                    shard.rebuild_search_index()
        _atomic_json(root / "contracts.json", {"schema_version": 1, "generation": generation, "apis": api_index, "feigns": feign_index, "mq": mq_index, "configs": config_index})
        _atomic_json(root / "topology.json", {"schema_version": 1, "generation": generation, "topology": topology})
        _atomic_json(root / "manifest.json", {"schema_version": 1, "generation": generation, "services": service_files, "contracts": "contracts.json", "topology": "topology.json", "copy_on_write": bool(reuse_generation), "rebuilt_services": sorted(rebuild_projects)})
    return {"root": str(root), "services": service_files, "contracts": "contracts.json", "topology": "topology.json", "copy_on_write": bool(reuse_generation), "rebuilt_services": sorted(rebuild_projects)}


def load_service_shard(store: WorkspaceStore, generation: str, project: str) -> dict[str, Any] | None:
    path = _generation_root(store, generation) / "services" / f"{_safe_name(project)}.json"
    return _read_json(path)


def service_shard_graph_path(store: WorkspaceStore, generation: str, project: str) -> Path | None:
    path = _generation_root(store, generation) / "services" / f"{_safe_name(project)}.graph.db"
    return path if path.exists() else None


def load_contract_shard(store: WorkspaceStore, generation: str) -> dict[str, Any] | None:
    return _read_json(_generation_root(store, generation) / "contracts.json")


def load_topology_shard(store: WorkspaceStore, generation: str) -> dict[str, Any] | None:
    payload = _read_json(_generation_root(store, generation) / "topology.json")
    return payload.get("topology", {}) if payload else None


def cleanup_generations(store: WorkspaceStore, *, active_generation: str, previous_generation: str = "", keep: int = 2, apply: bool = False) -> dict[str, Any]:
    base = store.index_dir / GENERATIONS_DIR
    entries = sorted((path for path in base.iterdir() if path.is_dir()), key=lambda path: path.stat().st_mtime_ns, reverse=True) if base.exists() else []
    protected = {value for value in (active_generation, previous_generation) if value}
    retained = {path.name for path in entries[:max(0, keep)]} | protected
    candidates = [path for path in entries if path.name not in retained]
    if apply:
        with FileLock(str(store.lock_file)):
            for path in candidates:
                shutil.rmtree(path, ignore_errors=True)
    return {"active_generation": active_generation, "retained": sorted(retained), "candidates": [path.name for path in candidates], "removed": len(candidates) if apply else 0}


def _by_project(rows: list[dict[str, Any]], project: str, path_key: str = "path") -> list[dict[str, Any]]:
    return [item for item in rows if str(item.get("project", "") or "") == project]


def _generation_root(store: WorkspaceStore, generation: str) -> Path:
    return store.index_dir / GENERATIONS_DIR / generation


def _safe_name(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_", "."} else "_" for char in value)


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)
        os.replace(raw, path)
    finally:
        Path(raw).unlink(missing_ok=True)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
