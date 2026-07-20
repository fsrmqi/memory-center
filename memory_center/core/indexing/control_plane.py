"""Versioned control plane for workspace index artifacts.

Generation index files remain immutable build artifacts. This module
adds an explicit active generation and a compact shard manifest so writers can
publish a complete index set atomically from the perspective of readers.
"""
from __future__ import annotations

import time
from typing import Any
from uuid import uuid4

from memory_center.core.storage.workspace import WorkspaceStore

CONTROL_FILE = "index-control.json"
SHARD_MANIFEST_FILE = "shard-manifest.json"


def begin_generation(store: WorkspaceStore, *, mode: str, projects: set[str], paths: list[str]) -> dict[str, Any]:
    current = index_control_status(store)
    generation = f"gen-{int(time.time() * 1000)}-{uuid4().hex[:8]}"
    state = {
        "schema_version": 1,
        "active_generation": current.get("active_generation", ""),
        "staging_generation": generation,
        "status": "building",
        "mode": mode,
        "projects": sorted(projects),
        "paths": list(paths)[:100],
        "started_at": time.time(),
        "updated_at": time.time(),
        "last_completed_at": current.get("last_completed_at", 0),
    }
    store.write_json(CONTROL_FILE, state)
    return state


def activate_generation(store: WorkspaceStore, generation: str, *, counts: dict[str, Any], shard_manifest: dict[str, Any]) -> dict[str, Any]:
    current = index_control_status(store)
    if current.get("staging_generation") != generation:
        raise ValueError("staging generation does not match active writer")
    now = time.time()
    state = {
        "schema_version": 1,
        "active_generation": generation,
        "previous_generation": current.get("active_generation", ""),
        "staging_generation": "",
        "status": "ready",
        "mode": current.get("mode", "full"),
        "projects": current.get("projects", []),
        "paths": current.get("paths", []),
        "started_at": current.get("started_at", now),
        "updated_at": now,
        "last_completed_at": now,
        "counts": {key: counts.get(key, 0) for key in ("files", "symbols", "apis", "feigns", "mq", "configs", "graph_nodes", "graph_edges", "semantic_docs")},
    }
    store.write_json(SHARD_MANIFEST_FILE, shard_manifest)
    store.write_json(CONTROL_FILE, state)
    return state


def fail_generation(store: WorkspaceStore, generation: str, error: str) -> None:
    current = index_control_status(store)
    if current.get("staging_generation") != generation:
        return
    store.write_json(CONTROL_FILE, {**current, "status": "failed", "staging_generation": "", "updated_at": time.time(), "error": error[:500]})


def index_control_status(store: WorkspaceStore) -> dict[str, Any]:
    state = store.read_json_prefer_backend(CONTROL_FILE, {})
    if not isinstance(state, dict):
        state = {}
    if not state:
        return {"schema_version": 1, "status": "uninitialized", "active_generation": "", "staging_generation": ""}
    return state


def rollback_generation(store: WorkspaceStore, generation: str = "") -> dict[str, Any]:
    """Atomically repoint readers to the retained previous generation."""
    current = index_control_status(store)
    target = generation or str(current.get("previous_generation", "") or "")
    if not target:
        return {"rolled_back": False, "reason": "no_previous_generation"}
    manifest = store.index_dir / "generations" / target / "manifest.json"
    if not manifest.exists():
        return {"rolled_back": False, "reason": "generation_not_retained", "generation": target}
    state = {
        **current,
        "active_generation": target,
        "previous_generation": current.get("active_generation", ""),
        "status": "ready",
        "updated_at": time.time(),
        "rollback_at": time.time(),
    }
    store.write_json(CONTROL_FILE, state)
    return {"rolled_back": True, "active_generation": target, "previous_generation": state["previous_generation"]}


def build_shard_manifest(
    generation: str,
    file_index: list[dict[str, Any]],
    api_index: list[dict[str, Any]],
    feign_index: list[dict[str, Any]],
    mq_index: list[dict[str, Any]],
    config_index: list[dict[str, Any]],
    topology: dict[str, Any],
) -> dict[str, Any]:
    """Create routing metadata without duplicating full index payloads."""
    services: dict[str, dict[str, int]] = {}
    for item in file_index:
        project = str(item.get("project", "") or "")
        if project:
            services.setdefault(project, {"files": 0, "apis": 0, "feigns": 0, "mq": 0, "configs": 0})["files"] += 1
    for rows, key in ((api_index, "apis"), (feign_index, "feigns"), (mq_index, "mq"), (config_index, "configs")):
        for item in rows:
            project = str(item.get("project", "") or "")
            if project:
                services.setdefault(project, {"files": 0, "apis": 0, "feigns": 0, "mq": 0, "configs": 0})[key] += 1
    return {
        "schema_version": 1,
        "generation": generation,
        "created_at": time.time(),
        "service_shards": services,
        "contract_shard": {"apis": len(api_index), "feigns": len(feign_index), "mq": len(mq_index), "configs": len(config_index)},
        "topology_shard": {"services": len(topology.get("services", []) or topology.get("nodes", []) or []), "keys": sorted(topology.keys())[:20]},
    }
