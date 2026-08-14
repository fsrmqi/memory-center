"""物理、版本化的服务与契约分片。"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from filelock import FileLock

from memory_center.core.storage.runtime import RuntimeStore
from memory_center.core.storage.workspace import WorkspaceStore

GENERATIONS_DIR = "generations"
_GRAPH_SECONDARY_INDEXES = (
    "idx_nodes_type_name",
    "idx_nodes_project",
    "idx_nodes_file_path",
    "idx_nodes_name",
    "idx_edges_source",
    "idx_edges_target",
    "idx_edges_type",
    "idx_edges_source_type",
    "idx_edges_target_type",
)
_GRAPH_SECONDARY_INDEX_DDL = (
    "CREATE INDEX idx_nodes_type_name ON nodes(type, name)",
    "CREATE INDEX idx_nodes_project ON nodes(project)",
    "CREATE INDEX idx_nodes_file_path ON nodes(file_path)",
    "CREATE INDEX idx_nodes_name ON nodes(name)",
    "CREATE INDEX idx_edges_source ON edges(source_id)",
    "CREATE INDEX idx_edges_target ON edges(target_id)",
    "CREATE INDEX idx_edges_type ON edges(type)",
    "CREATE INDEX idx_edges_source_type ON edges(source_id, type)",
    "CREATE INDEX idx_edges_target_type ON edges(target_id, type)",
)


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
    started = time.perf_counter()
    root = store.index_dir / GENERATIONS_DIR / generation
    service_dir = root / "services"
    with FileLock(str(store.lock_file)):
        if root.exists():
            shutil.rmtree(root)
        projects = sorted({str(item.get("project", "") or "") for item in file_index if item.get("project")})
        rebuild_projects = set(projects) if affected_projects is None else set(affected_projects)
        # An unresolvable filter must remain correct, so rebuild all instead
        # of publishing a generation that silently omits fresh source facts.
        if not rebuild_projects or not rebuild_projects.issubset(set(projects)):
            rebuild_projects = set(projects)

        previous = _generation_root(store, reuse_generation) if reuse_generation else None
        if previous and (previous / "services").exists():
            _inherit_unchanged_service_shards(
                previous / "services",
                service_dir,
                projects=set(projects),
                rebuild_projects=rebuild_projects,
            )
        service_dir.mkdir(parents=True, exist_ok=True)
        inherited_finished = time.perf_counter()

        service_files: dict[str, str] = {}
        graph_jobs: list[tuple[Path, str]] = []
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
            graph_jobs.append((service_dir / f"{_safe_name(project)}.graph.db", project))
        payloads_finished = time.perf_counter()

        # Full builds stay sequential to avoid turning a large workspace into
        # an unbounded I/O burst. Partial multi-project publication is bounded
        # because each worker writes one independent immutable shard.
        graph_workers = min(3, len(graph_jobs)) if reuse_generation and len(graph_jobs) > 1 else 1
        if graph_workers > 1:
            with ThreadPoolExecutor(max_workers=graph_workers, thread_name_prefix="memory-center-shard") as executor:
                list(
                    executor.map(
                        lambda job: _atomic_project_graph_shard(job[0], store.graph_db_path, job[1]),
                        graph_jobs,
                    )
                )
        else:
            for shard_db, project in graph_jobs:
                _atomic_project_graph_shard(shard_db, store.graph_db_path, project)
        graphs_finished = time.perf_counter()

        _atomic_json(root / "contracts.json", {"schema_version": 1, "generation": generation, "apis": api_index, "feigns": feign_index, "mq": mq_index, "configs": config_index})
        _atomic_json(root / "topology.json", {"schema_version": 1, "generation": generation, "topology": topology})
        shared_finished = time.perf_counter()
        timing_ms = {
            "inherit": round((inherited_finished - started) * 1000, 2),
            "service_payloads": round((payloads_finished - inherited_finished) * 1000, 2),
            "graph_shards": round((graphs_finished - payloads_finished) * 1000, 2),
            "shared_shards": round((shared_finished - graphs_finished) * 1000, 2),
        }
        manifest = {
            "schema_version": 1,
            "generation": generation,
            "services": service_files,
            "contracts": "contracts.json",
            "topology": "topology.json",
            "copy_on_write": bool(reuse_generation),
            "rebuilt_services": sorted(rebuild_projects),
            "graph_export_mode": "sqlite_attach_select",
            "graph_export_workers": graph_workers,
            "timing_ms": timing_ms,
        }
        _atomic_json(root / "manifest.json", manifest)
    return {"root": str(root), **manifest}


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


def _atomic_project_graph_shard(path: Path, source_db: Path, project: str) -> None:
    """Export one project inside SQLite without materializing graph rows in Python."""
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    os.close(fd)
    temp_path = Path(raw)
    temp_path.unlink(missing_ok=True)
    try:
        with RuntimeStore(temp_path) as shard:
            conn = shard.connect()
            # The destination is an unpublished, fully reproducible temporary
            # database. Disabling its journal avoids writing the same project
            # graph twice before the atomic rename.
            conn.execute("PRAGMA journal_mode=OFF")
            conn.execute("PRAGMA synchronous=OFF")
            for index_name in _GRAPH_SECONDARY_INDEXES:
                conn.execute(f"DROP INDEX IF EXISTS {index_name}")
            conn.execute("ATTACH DATABASE ? AS source_graph", (str(source_db),))
            try:
                conn.execute("DELETE FROM edges")
                conn.execute("DELETE FROM nodes")
                conn.execute("DELETE FROM file_generations")
                try:
                    conn.execute("DELETE FROM node_search")
                except sqlite3.OperationalError as exc:
                    if "node_search" not in str(exc):
                        raise
                conn.execute(
                    """
                    INSERT INTO nodes(id, type, name, project, file_path, line, metadata_json)
                    SELECT id, type, name, project, file_path, line, metadata_json
                    FROM source_graph.nodes
                    WHERE project = ?
                    """,
                    (project,),
                )
                conn.execute(
                    """
                    INSERT INTO edges(id, source_id, target_id, type, confidence, metadata_json)
                    SELECT edge.id, edge.source_id, edge.target_id, edge.type,
                           edge.confidence, edge.metadata_json
                    FROM source_graph.edges AS edge
                    JOIN source_graph.nodes AS source_node ON source_node.id = edge.source_id
                    JOIN source_graph.nodes AS target_node ON target_node.id = edge.target_id
                    WHERE source_node.project = ? AND target_node.project = ?
                    """,
                    (project, project),
                )
                for statement in _GRAPH_SECONDARY_INDEX_DDL:
                    conn.execute(statement)
                try:
                    conn.execute(
                        """
                        INSERT INTO node_search(id, type, name, project, file_path, content)
                        SELECT id, type, name, project, file_path,
                               id || ' ' || type || ' ' || name || ' ' ||
                               COALESCE(project, '') || ' ' || COALESCE(file_path, '') || ' ' ||
                               COALESCE(metadata_json, '')
                        FROM nodes
                        """
                    )
                except sqlite3.OperationalError as exc:
                    if "node_search" not in str(exc):
                        raise
                conn.commit()
            finally:
                conn.execute("DETACH DATABASE source_graph")
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)
        for suffix in ("-journal", "-shm", "-wal"):
            temp_path.with_name(temp_path.name + suffix).unlink(missing_ok=True)


def _inherit_unchanged_service_shards(
    previous_service_dir: Path,
    service_dir: Path,
    *,
    projects: set[str],
    rebuild_projects: set[str],
) -> None:
    """Hard-link only expected, unchanged service artifacts from the parent."""
    service_dir.mkdir(parents=True, exist_ok=True)
    for project in sorted(projects - rebuild_projects):
        stem = _safe_name(project)
        for suffix in (".json", ".graph.db"):
            source = previous_service_dir / f"{stem}{suffix}"
            if source.exists():
                _link_or_copy(str(source), str(service_dir / source.name))


def _link_or_copy(source: str, destination: str) -> str:
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)
    return destination


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
