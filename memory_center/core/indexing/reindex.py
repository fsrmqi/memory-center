from __future__ import annotations

import hashlib
import re
import time
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any

import yaml

from memory_center.core.storage.graph import GraphEdge, GraphNode, edge_id, node_id
from memory_center.core.storage.runtime import RuntimeStore

from ..contracting.static import (
    CONTRACT_DIFF_FILE,
    CONTRACT_SNAPSHOT_FILE,
    build_contract_snapshot,
    diff_contract_snapshots,
)
from .control_plane import (
    activate_generation,
    begin_generation,
    build_shard_manifest,
    fail_generation,
    index_control_status,
)
from .java_call_resolver import JavaCallResolver, build_java_class_index
from .reindex_state import workspace_reindex_lock
from .shards import cleanup_generations, write_generation_shards

# Keep the tree-sitter wrapper active so fallback reasons remain observable.
try:
    from .tree_sitter_parser import TreeSitterJavaParser
    _ts_parser = TreeSitterJavaParser()
    _JAVA_PARSER = _ts_parser
    from . import RegexJavaParser  # keep import for emergency fallback path
except Exception:
    from . import RegexJavaParser
    _JAVA_PARSER = RegexJavaParser()
from memory_center.core.foundation.models import (    ApiEndpoint,
    FeignClient,
    JavaSymbol,
    MqEndpoint,
    WorkspaceConfig,
    to_dict,
)
from memory_center.core.indexing import job_coordinator
from memory_center.core.indexing.precision import parser_precision_from_diagnostics
from memory_center.core.observability.operations import observe_operation
from memory_center.core.retrieval.semantic import (
    build_workspace_semantic_index,
    build_workspace_semantic_index_partial,
    semantic_index_stats,
)
from memory_center.core.storage.workspace import WorkspaceStore

JAVA_EXTENSIONS = {".java"}
CONFIG_NAMES = {"application.yml", "application.yaml", "bootstrap.yml", "bootstrap.yaml"}
IGNORED_DIRS = {
    ".git", ".idea", ".vscode", "target", "build", "dist", "node_modules",
    ".memory-center", ".project-ai", ".symbio", ".claude", ".codex", ".codex-hooks", "__pycache__",
}


@observe_operation(
    "reindex_workspace",
    workspace_resolver=lambda args, kwargs: args[1].workspace_file if len(args) > 1 else kwargs["store"].workspace_file,
    tags_resolver=lambda args, kwargs: {"parallel": bool(kwargs.get("parallel", True))},
)
def _reindex_workspace_unlocked(
    config: WorkspaceConfig,
    store: WorkspaceStore,
    *,
    projects: Sequence[str] | None = None,
    paths: Sequence[str] | None = None,
    parallel: bool = True,
    pool: Any = None,
    cache: Any = None,
    source_digests: dict[str, str] | None = None,
    progress: Callable[[str, int, str], None] | None = None,
    generation: str = "",
    resolve_all_relations: bool = False,
) -> dict[str, Any]:
    """Rebuild deterministic indexes and the local evidence graph."""
    pipeline_started = time.perf_counter()
    checkpoint = pipeline_started
    timing_ms: dict[str, float] = {}

    def mark(stage: str) -> None:
        nonlocal checkpoint
        now = time.perf_counter()
        timing_ms[stage] = round((now - checkpoint) * 1000, 2)
        checkpoint = now

    project_filter = {item.strip() for item in (projects or []) if item and item.strip()}
    path_filters = [item.strip() for item in (paths or []) if item and item.strip()]
    partial = bool(project_filter or path_filters)

    old_file_index: list[dict[str, Any]] = store.read_json_prefer_backend("file-index.json", [])
    old_symbol_index: list[dict[str, Any]] = store.read_json_prefer_backend("java-symbol-index.json", [])
    old_api_index: list[dict[str, Any]] = store.read_json_prefer_backend("api-index.json", [])
    old_feign_index: list[dict[str, Any]] = store.read_json_prefer_backend("feign-index.json", [])
    old_mq_index: list[dict[str, Any]] = store.read_json_prefer_backend("mq-index.json", [])
    old_config_index: list[dict[str, Any]] = store.read_json_prefer_backend("config-index.json", [])
    old_contract_snapshot = store.read_json_prefer_backend(CONTRACT_SNAPSHOT_FILE, {})
    mark("load_indexes")

    # Coverage ledger: one row per discovered file (parsed/partial/skipped/
    # failed + bounded reason). Partial refreshes inherit the previous
    # generation's rows so coverage always describes the full merged index.
    from memory_center.core.indexing.coverage import (
        STATUS_PARSED,
        STATUS_SKIPPED,
        CoverageLedger,
        attach_coverage_summary,
        write_coverage,
    )

    ledger = CoverageLedger()
    if partial:
        for row in store.read_json_prefer_backend("index-coverage.json", {}).get("files", []):
            ledger.record(str(row.get("path", "")), str(row.get("status", "parsed")), str(row.get("reason", "")))

    file_index: list[dict[str, Any]] = []
    symbol_index: list[dict[str, Any]] = []
    api_index: list[dict[str, Any]] = []
    feign_index: list[dict[str, Any]] = []
    mq_index: list[dict[str, Any]] = []
    config_index: list[dict[str, Any]] = []
    # Collect feign files for deferred parsing (need complete constant_map first)
    pending_feigns: list[tuple] = []
    java_tasks: list[tuple] = []
    # 扫描/切块阶段已算好的内容 sha256（键为绝对路径字符串）。有值时 Java 解析不再
    # 重复读文件、不重复哈希，缓存命中即完全不碰盘；缺失的路径回退为解析侧自读。
    source_digests = source_digests or {}

    reset_parser_diagnostics = getattr(_JAVA_PARSER, "reset_diagnostics", None)
    if callable(reset_parser_diagnostics):
        reset_parser_diagnostics()

    _report_progress(progress, "scanning", 10, "正在扫描工作区文件")
    for svc in config.services:
        if project_filter and svc.name not in project_filter:
            continue
        service_root = config.resolve_service_path(svc)
        if not service_root.exists():
            continue
        for path in _walk_scoped_project(config, svc, service_root, path_filters):
            rel = config.service_logical_file_path(svc, path)
            file_index.append(
                {
                    "project": svc.name,
                    "service_name": svc.service_name or svc.name,
                    "path": rel,
                    "abs_path": str(path.resolve()),
                    "service_root": str(service_root),
                    "suffix": path.suffix,
                    "source_mtime_ns": path.stat().st_mtime_ns,
                    "source_size": path.stat().st_size,
                }
            )
            if path.suffix in JAVA_EXTENSIONS:
                java_tasks.append((svc.name, rel, path, cache, source_digests.get(str(path), "")))
            elif path.name in CONFIG_NAMES:
                config_index.append({"project": svc.name, "path": rel, **parse_yaml_config(path)})
                ledger.record(rel, STATUS_PARSED)
            else:
                ledger.record(rel, STATUS_SKIPPED, "unsupported_syntax")
    mark("scan_scope")

    _report_progress(progress, "parsing", 30, f"正在解析 {len(java_tasks)} 个 Java 文件")
    # 解析 Java 文件。三级优先：显式工作池 > 遗留线程池 > 串行。
    # 工作池走进程，是真正能提速 tree-sitter 的方式（该绑定不释放 GIL，
    # 实测 8 线程比串行慢 24%，见 docs/benchmarks/V5_SERVICE_INDEX_STAGE_BASELINE.md）；
    # 线程池只为尚未接入服务排程的调用方保留。两条并行路径都按任务顺序收敛结果，
    # 使 symbol_index 顺序与串行一致——原地按完成顺序追加会让产物不可复现。
    # 传入 cache 时逐文件按内容取用解析结果；命中与未命中的返回形状完全一致。
    if pool is not None and pool.parallel and len(java_tasks) > 1:
        parsed = pool.map(_parse_java_task, java_tasks)
    elif parallel and len(java_tasks) > 10:
        from concurrent.futures import ThreadPoolExecutor

        from .parallel import estimate_optimal_workers
        with ThreadPoolExecutor(max_workers=estimate_optimal_workers(len(java_tasks))) as executor:
            parsed = list(executor.map(_parse_java_task, java_tasks))
    else:
        parsed = [_parse_java_task(task) for task in java_tasks]

    for (_svc_name, rel, _path, _cache, _digest), result in zip(java_tasks, parsed, strict=True):
        if result["symbol"]:
            symbol_index.append(result["symbol"])
            ledger.record(rel, STATUS_PARSED)
        else:
            ledger.record(rel, "failed", "parse_error")
        api_index.extend(result["apis"])
        if result["pending_feign"]:
            pending_feigns.append(result["pending_feign"])
        mq_index.extend(result["mq"])

    # Build constant map from completed symbol scan, then resolve feign target_service
    merge_paths = [] if resolve_all_relations and project_filter else path_filters
    if partial:
        merged_symbol_index = _merge_index_rows(old_symbol_index, symbol_index, project_filter, merge_paths, path_key="file")
    else:
        merged_symbol_index = symbol_index
    constant_map = _build_constant_map(merged_symbol_index)
    for project, rel, path, symbol in pending_feigns:
        # Feign 目标解析确实需要源码文本，但只有 Feign 接口自身需要——其数量远小于
        # 全部 Java 文件，故在此按需读取，避免解析产物跨阶段驻留整份源码。
        feign_index.extend(to_dict(x) for x in parse_feign_clients(project, rel, safe_read(path), symbol, constant_map))
    mark("parse_and_merge")

    if partial:
        merged_file_index = _merge_index_rows(old_file_index, file_index, project_filter, merge_paths)
        merged_api_index = _merge_index_rows(old_api_index, api_index, project_filter, merge_paths, path_key="file")
        merged_feign_index = _merge_index_rows(old_feign_index, feign_index, project_filter, merge_paths, path_key="file")
        merged_mq_index = _merge_index_rows(old_mq_index, mq_index, project_filter, merge_paths, path_key="file")
        merged_config_index = _merge_index_rows(old_config_index, config_index, project_filter, merge_paths)
    else:
        merged_file_index = file_index
        merged_api_index = api_index
        merged_feign_index = feign_index
        merged_mq_index = mq_index
        merged_config_index = config_index

    _report_progress(progress, "graph", 50, "正在构建契约、拓扑和知识图谱")
    topology = build_topology(config, merged_feign_index, merged_api_index, merged_mq_index, merged_config_index)
    store.write_json("file-index.json", merged_file_index)
    store.write_json("java-symbol-index.json", merged_symbol_index)
    store.write_json("api-index.json", merged_api_index)
    store.write_json("feign-index.json", merged_feign_index)
    store.write_json("mq-index.json", merged_mq_index)
    store.write_json("config-index.json", merged_config_index)
    store.write_json("service-topology.json", topology)
    contract_snapshot = build_contract_snapshot(merged_api_index, merged_feign_index, merged_mq_index, merged_symbol_index)
    contract_diff = diff_contract_snapshots(old_contract_snapshot, contract_snapshot)
    store.write_json(CONTRACT_SNAPSHOT_FILE, contract_snapshot)
    store.write_json(CONTRACT_DIFF_FILE, contract_diff)
    mark("persist_indexes")
    if resolve_all_relations:
        current_paths = {str(row.get("path", "")) for row in merged_file_index}
        current_ledger = CoverageLedger()
        for row in ledger.to_rows():
            if row["path"] in current_paths:
                current_ledger.record(row["path"], row["status"], row.get("reason", ""))
        ledger = current_ledger
    coverage_aggregate = write_coverage(store, generation, ledger, mode="partial" if partial else "full")
    # 服务平台的增量刷新只重读变化服务，但跨文件关系必须在完整合并事实上重算，
    # 否则被删／改的目标会留下未变化调用方的旧边。
    graph_counts = build_graph_store(config, store, project_filter=set() if resolve_all_relations else project_filter,
                                     path_filters=[] if resolve_all_relations else path_filters)
    mark("graph_update")
    # Phase D: project stored call edges through the explicit IR boundary
    # and publish unified resolution diagnostics for failure-category work.
    resolution_summary = _resolution_diagnostics(store)
    # Task step 3: persist the Java adapter's explicit IR output (additive).
    # The legacy graph projection stays authoritative; this payload is the
    # boundary the differential gate (step 4) compares against.
    #
    # Perf fix (long task: scoped refresh hot path): on a partial refresh we
    # must NOT rebuild the full 678k-candidate IR index every time (that was
    # ~13s and dominated graph_update). Only re-resolve the scoped symbols and
    # inherit unchanged files' candidates from the previous generation, like
    # the other merged indexes.
    from memory_center.core.indexing.java_ir import build_java_ir_index

    if partial and not resolve_all_relations:
        ir_payload = _merge_ir_partial(store, merged_symbol_index, project_filter, path_filters)
    else:
        ir_payload = build_java_ir_index(merged_symbol_index)
    store.write_json("java-ir-index.json", ir_payload)
    mark("graph_update")
    changed_ids: set[str] = set()
    _report_progress(progress, "semantic", 68, "正在构建语义索引")
    if partial and not resolve_all_relations:
        changed_ids = set(graph_counts.get("changed_node_ids", []))
        semantic_counts = build_workspace_semantic_index_partial(store.workspace_file, changed_ids) if changed_ids else {
            **semantic_index_stats(store.workspace_file),
            "mode": "partial-noop",
            "changed_node_count": 0,
        }
    else:
        semantic_counts = build_workspace_semantic_index(store.workspace_file)
    mark("semantic_update")
    _report_progress(progress, "retrieval", 82, "正在同步检索索引")
    retrieval_counts = _sync_retrieval_indexes(
        store,
        semantic_counts,
        changed_node_ids=changed_ids if partial and not resolve_all_relations else None,
    )
    mark("retrieval_update")
    parser_diagnostics = _parser_diagnostics(len(java_tasks))
    parser_precision = parser_precision_from_diagnostics(parser_diagnostics)
    graph_summary = {
        **graph_counts,
        "parser": parser_diagnostics["selected_parser"],
        "parser_diagnostics": parser_diagnostics,
        "parser_precision": parser_precision,
    }
    attach_coverage_summary(graph_summary, coverage_aggregate)
    graph_summary["resolution_summary"] = resolution_summary
    graph_summary["ir_index"] = {
        "file_count": ir_payload["file_count"],
        "symbol_count": ir_payload["symbol_count"],
        "candidate_count": ir_payload["candidate_count"],
    }
    store.write_json("graph-summary.json", graph_summary)
    counts = {
        "mode": "partial" if partial else "full",
        "filtered_projects": sorted(project_filter),
        "filtered_paths": path_filters,
        "scanned_files": len(file_index),
        "files": len(merged_file_index),
        "symbols": len(merged_symbol_index),
        "apis": len(merged_api_index),
        "feigns": len(merged_feign_index),
        "mq": len(merged_mq_index),
        "configs": len(merged_config_index),
        "contract_breaking_changes": contract_diff["breaking_count"],
        "graph_nodes": graph_counts.get("nodes", 0),
        "graph_edges": graph_counts.get("edges", 0),
        "semantic_docs": semantic_counts.get("doc_count", 0),
        "semantic_backend": semantic_counts.get("backend", "sparse"),
        "requested_semantic_backend": semantic_counts.get("requested_backend", "sparse"),
        "semantic_model": semantic_counts.get("model"),
        "requested_semantic_model": semantic_counts.get("requested_model"),
        "vector_scope": semantic_counts.get("requested_vector_scope", "selective"),
        "vector_candidate_count": semantic_counts.get("vector_candidate_count", 0),
        "dense_doc_count": semantic_counts.get("dense_doc_count", 0),
        "vector_status": semantic_counts.get("vector_status", "unknown"),
        "vector_disabled_reason": semantic_counts.get("vector_disabled_reason"),
        "parser": parser_diagnostics["selected_parser"],
        "parser_fallback_count": parser_diagnostics["fallback_count"],
        "parser_critical_disagreement_count": parser_diagnostics["critical_disagreement_count"],
        "parser_diagnostics": parser_diagnostics,
        "parser_precision": parser_precision,
        "coverage_summary": {
            key: coverage_aggregate[key]
            for key in ("parsed", "partial", "skipped", "failed", "total_files")
            if key in coverage_aggregate
        } if coverage_aggregate else {},
        "coverage_reasons": coverage_aggregate.get("reasons", []) if coverage_aggregate else [],
        "resolution_summary": resolution_summary,
        **retrieval_counts,
    }
    _report_progress(progress, "finalizing", 92, "正在写入索引摘要")
    store.write_json(
        "index-summary.json",
        {
            "schema_version": 1,
            "mode": counts["mode"],
            "files": counts["files"],
            "symbols": counts["symbols"],
            "apis": counts["apis"],
            "feigns": counts["feigns"],
            "mq": counts["mq"],
            "configs": counts["configs"],
            "graph_nodes": counts["graph_nodes"],
            "graph_edges": counts["graph_edges"],
            "semantic_docs": counts["semantic_docs"],
            "semantic_backend": counts["semantic_backend"],
            "semantic_model": counts["semantic_model"],
            "vector_status": counts["vector_status"],
        },
    )
    mark("write_summary")
    timing_ms["pipeline_total"] = round((time.perf_counter() - pipeline_started) * 1000, 2)
    counts["timing_ms"] = timing_ms
    return counts


def _resolution_diagnostics(store: WorkspaceStore) -> dict[str, Any]:
    """Phase D: collect unified resolution/unresolved diagnostics (bounded).

    Reads stored CALLS_METHOD edges back through the explicit IR boundary,
    aggregates unproven targets by reason code and file, and persists the
    reviewable ``index-resolution.json`` export. Only counts, short reason
    codes, and already-persisted workspace-relative paths are retained.
    """
    from memory_center.core.indexing.ir import (
        call_edges_to_relation_candidates,
        summarize_unresolved,
        unresolved_by_file,
    )

    edges: list[dict[str, Any]] = []
    source_files: dict[str, str] = {}
    with RuntimeStore(store.graph_db_path) as graph:
        conn = graph.connect()
        try:
            rows = conn.execute(
                "SELECT source_id, target_id, confidence, metadata_json FROM edges"
                " WHERE type='CALLS_METHOD' ORDER BY id LIMIT 20000"
            ).fetchall()
            keys = ("source_id", "target_id", "confidence", "metadata_json")
            edges = [dict(zip(keys, row)) for row in rows]
            # Resolve node-id -> logical path in bounded chunks so per-file
            # breakdowns can locate failure categories.
            source_ids = sorted({str(row["source_id"]) for row in edges if row["source_id"]})
            for start in range(0, len(source_ids), 500):
                chunk = source_ids[start : start + 500]
                placeholders = ",".join("?" for _ in chunk)
                n_rows = conn.execute(
                    f"SELECT id, file_path FROM nodes WHERE id IN ({placeholders})",
                    tuple(chunk),
                ).fetchall()
                for node_id_value, file_path in n_rows:
                    source_files[str(node_id_value)] = str(file_path or "")
        finally:
            pass
    candidates = call_edges_to_relation_candidates(edges, source_file_by_id=source_files)
    summary = summarize_unresolved(candidates)
    payload = {
        "schema_version": 1,
        "truncated": len(edges) >= 20000,
        **summary,
        "unresolved_by_file": unresolved_by_file(candidates),
    }
    store.write_json("index-resolution.json", payload)
    return {
        "calls_total": summary["total_calls"],
        "calls_resolved": summary["resolved"],
        "calls_unresolved": summary["unresolved"],
        "evidence_levels": summary["evidence_levels"],
        "top_unresolved_reasons": summary["unresolved_reasons"][:8],
    }


def _merge_ir_partial(
    store: WorkspaceStore,
    merged_symbols: list[dict[str, Any]],
    project_filter: set[str],
    path_filters: list[str],
) -> dict[str, Any]:
    """Rebuild only the scoped files' IR candidates; inherit unchanged files'
    candidates from the previous generation's java-ir-index.json.

    Resolving the full 678k-candidate IR index on every partial refresh was
    the dominant cost of graph_update on real workspaces; this keeps it
    bounded to the changed scope without lowering evidence or coverage.
    """
    from memory_center.core.indexing.java_ir import build_java_ir_index

    old_ir = store.read_json_prefer_backend("java-ir-index.json", {})
    old_candidates = old_ir.get("relation_candidates", []) or []

    # Determine which files are in scope: any symbol whose file matches the
    # project/path filters (mirrors _row_matches_scope).
    scoped_syms: list[dict[str, Any]] = []
    changed_files: set[str] = set()
    for sym in merged_symbols:
        if _row_matches_scope(sym, project_filter, path_filters, path_key="file"):
            scoped_syms.append(sym)
            changed_files.add(str(sym.get("file", "")))

    new_payload = build_java_ir_index(scoped_syms)
    new_candidates = new_payload.get("relation_candidates", []) or []

    # Keep candidates from unchanged files (source_file not in changed set).
    inherited = [
        cand
        for cand in old_candidates
        if str(cand.get("source_file", "")) not in changed_files
    ]
    merged_candidates = inherited + new_candidates
    # file_records/symbol_records are small metadata lists; inherit all old and
    # overlay the scoped files' new records (they are not the perf hot path —
    # the 678k relation_candidates are).
    merged_file_records = list(old_ir.get("file_records", []) or []) + list(new_payload.get("file_records", []) or [])
    merged_symbol_records = list(old_ir.get("symbol_records", []) or []) + list(new_payload.get("symbol_records", []) or [])
    return {
        "schema_version": 1,
        "file_count": len(merged_file_records),
        "symbol_count": len(merged_symbol_records),
        "candidate_count": len(merged_candidates),
        "file_records": merged_file_records,
        "symbol_records": merged_symbol_records,
        "relation_candidates": merged_candidates,
    }


def _publish_smoke(store: WorkspaceStore, generation: str) -> dict[str, Any]:
    """Post-publish read-only smoke check (design doc §8.5).

    Only anonymous metadata and internal counters are read back; no project
    facts or source content. Failure means the published pointer must be
    rolled back rather than served.
    """
    try:
        control = store.read_json_prefer_backend("index-control.json", {})
        if not isinstance(control, dict) or control.get("active_generation") != generation:
            return {"ok": False, "reason": "control_pointer_mismatch"}
        manifest = store.read_json_prefer_backend("shard-manifest.json", {})
        if not isinstance(manifest, dict) or str(manifest.get("generation", "")) != generation:
            return {"ok": False, "reason": "manifest_generation_mismatch"}
        counts = control.get("counts")
        if not isinstance(counts, dict):
            return {"ok": False, "reason": "missing_publication_counts"}
        # Structural read-back of the summary, when the pipeline produced
        # one: stubbed/benchmark paths may legitimately skip it.
        summary = store.read_json_prefer_backend("graph-summary.json", None)
        if summary is not None and not isinstance(summary, dict):
            return {"ok": False, "reason": "graph_summary_unreadable"}
        return {"ok": True}
    except Exception as exc:
        from memory_center.core.observability.diagnostics import safe_reason

        return {"ok": False, "reason": safe_reason(reason=str(exc))[:120]}


def reindex_workspace(
    config: WorkspaceConfig,
    store: WorkspaceStore,
    *,
    projects: Sequence[str] | None = None,
    paths: Sequence[str] | None = None,
    parallel: bool = True,
    lock_timeout: float = 0.0,
    progress: Callable[[str, int, str], None] | None = None,
    materialize_assertions: bool = True,
    pool: Any = None,
    cache: Any = None,
    source_digests: dict[str, str] | None = None,
    owner_actor: str = "local",
    owner_session_id: str = "",
    resolve_all_relations: bool = False,
) -> dict[str, Any]:
    """Rebuild workspace indexes with one writer per workspace.

    Phase C coordination: requests are admitted through the job
    coordinator before the writer lock is taken. An identical in-flight
    request coalesces onto the active job (nothing runs twice); an
    overlapping scope with a different request is refused as a conflict.
    The publication is atomic with a post-commit smoke check that rolls
    back to the previous generation on failure.
    """
    reindex_started = time.perf_counter()

    filtered_projects = [item for item in (projects or []) if item and item.strip()]
    filtered_paths = [item for item in (paths or []) if item and item.strip()]
    admission = job_coordinator.admit_reindex_job(
        store,
        projects=filtered_projects,
        paths=filtered_paths,
        parallel=parallel,
        owner_actor=owner_actor,
        owner_session_id=owner_session_id,
    )
    if admission.get("coalesced"):
        return {
            "coalesced": True,
            "reason_code": "reindex_coalesced",
            "job_id": admission.get("job_id", ""),
            "owner_staging_generation": admission.get("staging_generation", ""),
            "next_action": "相同刷新正在由该 job 执行，直接读取其状态或等待其完成。",
        }
    if admission.get("conflict"):
        raise job_coordinator.JobCoordinatorError(admission)
    job_id = str(admission["job_id"])
    previous_active_for_rollback = ""

    with workspace_reindex_lock(
        store,
        projects=projects,
        paths=paths,
        timeout_seconds=lock_timeout,
    ):
        control = begin_generation(
            store,
            mode="partial" if projects or paths else "full",
            projects={item for item in (projects or []) if item},
            paths=list(paths or []),
        )
        generation = str(control["staging_generation"])
        previous_active_for_rollback = str(control.get("active_generation", "") or "")
        try:
            job_coordinator.mark_stage(store, job_id, "running")

            def _coordinated_progress(stage: str, percent: int, message: str) -> None:
                job_coordinator.record_heartbeat(store, job_id)
                if progress is not None:
                    progress(stage, percent, message)

            _report_progress(_coordinated_progress, "scanning", 8, "已获取工作区写锁，开始构建索引")
            # Generation-local staging: this run's merged intermediate
            # indexes are buffered in an overlay and only committed to the
            # canonical index_mirror atomically at publish time. Parallel
            # non-overlapping refreshes can build their own staging without
            # clobbering each other; a failed/cancelled run discards it.
            from memory_center.core.indexing.staging import with_staging

            staging_store = with_staging(store)
            reindex_kwargs: dict[str, Any] = {
                "projects": projects,
                "paths": paths,
                "parallel": parallel,
                "pool": pool,
                "cache": cache,
                "source_digests": source_digests,
                "generation": generation,
                "progress": _coordinated_progress,
            }
            if resolve_all_relations:
                reindex_kwargs['resolve_all_relations'] = True
            counts = _reindex_workspace_unlocked(config, staging_store, **reindex_kwargs)
            _report_progress(progress, "finalizing", 94, "正在发布索引代际")
            publication_started = time.perf_counter()
            manifest = build_shard_manifest(
                generation,
                staging_store.read_json_prefer_backend("file-index.json", []),
                staging_store.read_json_prefer_backend("api-index.json", []),
                staging_store.read_json_prefer_backend("feign-index.json", []),
                staging_store.read_json_prefer_backend("mq-index.json", []),
                staging_store.read_json_prefer_backend("config-index.json", []),
                staging_store.read_json_prefer_backend("service-topology.json", {}),
            )
            physical_shards = write_generation_shards(
                staging_store,
                generation,
                file_index=staging_store.read_json_prefer_backend("file-index.json", []),
                symbol_index=staging_store.read_json_prefer_backend("java-symbol-index.json", []),
                api_index=staging_store.read_json_prefer_backend("api-index.json", []),
                feign_index=staging_store.read_json_prefer_backend("feign-index.json", []),
                mq_index=staging_store.read_json_prefer_backend("mq-index.json", []),
                config_index=staging_store.read_json_prefer_backend("config-index.json", []),
                topology=staging_store.read_json_prefer_backend("service-topology.json", {}),
                reuse_generation=str(control.get("active_generation", "") or "") if (projects or paths) else "",
                    affected_projects={s.name for s in config.services} if resolve_all_relations else _affected_shard_projects(
                        staging_store.read_json_prefer_backend("file-index.json", []),
                        {item.strip() for item in (projects or []) if item and item.strip()},
                        [item.strip() for item in (paths or []) if item and item.strip()],
                ) if (projects or paths) else None,
            )
            generation_timing_ms = dict(physical_shards.get("timing_ms", {}))
            manifest["physical_shards"] = physical_shards
            # Stage boundary: cooperative cancellation stops here. Once the
            # publish transaction starts it may only complete or roll back.
            job_coordinator.mark_stage(store, job_id, "validating")
            if job_coordinator.cancel_requested(store, job_id):
                from memory_center.core.workspace.jobs import WorkspaceJobCancelled

                raise WorkspaceJobCancelled("publishing 前确认到取消请求")
            job_coordinator.mark_stage(store, job_id, "publishing")
            # Commit the generation-local staging overlay atomically with the
            # pointer flip. publish_generation_payloads runs inside a single
            # BEGIN IMMEDIATE transaction; a failure rolls everything back and
            # the previous active generation keeps serving.
            staging_store.publish(publication={
                "published_generation": generation,
                "previous_generation": previous_active_for_rollback,
                "publishing_job_id": job_id,
                "mode": str(control.get("mode", "full")),
                "outcome": "published",
            })
            activate_generation(
                store,
                generation,
                counts=counts,
                shard_manifest=manifest,
                publishing_job_id=job_id,
            )
            control = index_control_status(store)
            smoke = _publish_smoke(store, generation)
            if not smoke["ok"]:
                from memory_center.core.indexing.control_plane import rollback_generation

                store.record_publication_outcome({
                    "published_generation": generation,
                    "previous_generation": previous_active_for_rollback,
                    "publishing_job_id": job_id,
                    "mode": str(control.get("mode", "")),
                    "outcome": "publish_smoke_failed",
                })
                rollback_generation(store, previous_active_for_rollback)
                raise RuntimeError(f"publish_smoke_failed: {smoke['reason']}")
            job_coordinator.finish_job(store, job_id, "completed")
            counts["job_id"] = job_id
            counts["generation_gc"] = cleanup_generations(
                store,
                active_generation=str(control.get("active_generation", "") or ""),
                previous_generation=str(control.get("previous_generation", "") or ""),
                keep=2,
                apply=True,
            )
            publication_finished = time.perf_counter()
            # The assertion sidecar is auxiliary: the graph generation is
            # already visible, so an assertion write failure must never roll
            # back or delay the usable index.
            try:
                if not materialize_assertions:
                    raise RuntimeError("assertion_sidecar_disabled_for_benchmark")
                from memory_center.core.knowledge.assertions import materialize_static_assertions

                materialize_static_assertions(
                    store,
                    generation,
                    paths=list(paths or []),
                    projects=list(projects or []),
                )
            except Exception as exc:
                if not materialize_assertions:
                    _report_progress(progress, "finalizing", 98, "索引代际已发布（断言侧车基准已跳过）")
                    finished = time.perf_counter()
                    timing_ms = dict(counts.get("timing_ms", {}))
                    timing_ms["generation_publish"] = round((publication_finished - publication_started) * 1000, 2)
                    _merge_generation_stage_timings(timing_ms, generation_timing_ms)
                    timing_ms["assertion_projection"] = round((finished - publication_finished) * 1000, 2)
                    timing_ms["total"] = round((finished - reindex_started) * 1000, 2)
                    counts["timing_ms"] = timing_ms
                    return counts
                store.write_json(
                    "assertion-index.json",
                    {"schema_version": 1, "generation": generation, "status": "unavailable", "reason": str(exc)[:200]},
                )
            finished = time.perf_counter()
            timing_ms = dict(counts.get("timing_ms", {}))
            timing_ms["generation_publish"] = round((publication_finished - publication_started) * 1000, 2)
            _merge_generation_stage_timings(timing_ms, generation_timing_ms)
            timing_ms["assertion_projection"] = round((finished - publication_finished) * 1000, 2)
            timing_ms["total"] = round((finished - reindex_started) * 1000, 2)
            counts["timing_ms"] = timing_ms
            if projects or paths:
                from memory_center.core.retrieval.planner import record_scoped_refresh_performance

                counts["refresh_performance"] = record_scoped_refresh_performance(
                    store.workspace_file,
                    timing_ms=timing_ms,
                    path_count=len(paths or []),
                    project_count=len(projects or []),
                    scanned_files=int(counts.get("scanned_files", 0) or 0),
                    generation=generation,
                    paths=list(paths or []),
                    projects=list(projects or []),
                )
            _report_progress(progress, "finalizing", 98, "索引代际已发布")
            # Preserve the historical reindex return schema. Generation and
            # shard routing are published through index-control/status files.
            return counts
        except BaseException as exc:
            fail_generation(store, generation, str(exc) or type(exc).__name__)
            from memory_center.core.workspace.jobs import WorkspaceJobCancelled

            if isinstance(exc, WorkspaceJobCancelled):
                job_coordinator.finish_job(store, job_id, "cancelled")
            else:
                from memory_center.core.observability.diagnostics import safe_reason as _safe_reason

                job_coordinator.finish_job(store, job_id, "failed", failure_code=_safe_reason(reason=str(exc) or type(exc).__name__))
            raise


def _merge_generation_stage_timings(timing_ms: dict[str, Any], generation_timing_ms: dict[str, Any]) -> None:
    for stage in ("inherit", "service_payloads", "graph_shards", "shared_shards"):
        timing_ms[f"generation_{stage}"] = round(float(generation_timing_ms.get(stage, 0.0) or 0.0), 2)


def _report_progress(
    progress: Callable[[str, int, str], None] | None,
    stage: str,
    percent: int,
    message: str,
) -> None:
    if progress:
        progress(stage, percent, message)


def _affected_shard_projects(file_index: list[dict[str, Any]], project_filter: set[str], path_filters: list[str]) -> set[str]:
    if project_filter:
        return set(project_filter)
    projects = {
        str(item.get("project", "") or "")
        for item in file_index
        # Keep generation-shard routing aligned with partial index merging.
        # File records keep a workspace-relative path plus the source absolute
        # path, while CLI refresh accepts either form.
        if _row_matches_scope(item, set(), path_filters)
    }
    return {project for project in projects if project}


def _graph_scope_path_filters(file_index: list[dict[str, Any]], path_filters: Sequence[str]) -> list[str]:
    """Convert matching absolute refresh paths to graph-stable logical paths."""
    resolved: set[str] = set()
    for raw_filter in path_filters:
        matched = [
            str(item.get("path", "") or "")
            for item in file_index
            if _row_matches_scope(item, set(), [raw_filter])
        ]
        if matched:
            resolved.update(path for path in matched if path)
        else:
            # Preserve the original path for the no-match safe path. It will
            # not delete unrelated graph nodes, while shard publication falls
            # back to a complete rebuild for correctness.
            resolved.add(raw_filter)
    return sorted(resolved)


def _parser_diagnostics(parse_count: int) -> dict[str, Any]:
    diagnostics = getattr(_JAVA_PARSER, "diagnostics", None)
    if isinstance(diagnostics, dict):
        return dict(diagnostics)
    return {
        "selected_parser": getattr(_JAVA_PARSER, "name", "regex") or "regex",
        "tree_sitter_available": False,
        "parse_count": parse_count,
        "native_success_count": 0,
        "fallback_count": 0,
        "fallback_reasons": {},
        "native_disagreement_count": 0,
        "critical_disagreement_count": 0,
    }


def _path_matches_filters(config: WorkspaceConfig, svc, path: Path, path_filters: Sequence[str]) -> bool:
    logical = config.service_logical_file_path(svc, path).replace("\\", "/")
    absolute = str(path.resolve()).replace("\\", "/")
    candidates = {logical, absolute}
    for raw_filter in path_filters:
        normalized = raw_filter.replace("\\", "/").strip("/")
        normalized_abs = raw_filter.replace("\\", "/")
        for candidate in candidates:
            probe = candidate.strip("/")
            if probe == normalized or probe.startswith(normalized + "/"):
                return True
            if candidate == normalized_abs or candidate.startswith(normalized_abs.rstrip("/") + "/"):
                return True
    return False


def _row_matches_scope(
    row: dict[str, Any],
    project_filter: set[str],
    path_filters: Sequence[str],
    *,
    path_key: str = "path",
) -> bool:
    project = str(row.get("project", "") or "")
    # A row is in scope if it matches BOTH project AND path filters.
    # If only project_filter is given (no path_filters), project match suffices.
    # If only path_filters is given (no project_filter), path match suffices.
    # If both are given, the row must match at least one of them.
    project_match = project_filter and project in project_filter
    path_match = False
    if path_filters:
        path_value = str(row.get(path_key, "") or row.get("path", "") or "")
        abs_path = str(row.get("abs_path", "") or "")
        for raw_filter in path_filters:
            normalized = raw_filter.replace("\\", "/").strip("/")
            normalized_abs = raw_filter.replace("\\", "/")
            probe = path_value.replace("\\", "/").strip("/")
            if probe == normalized or probe.startswith(normalized + "/"):
                path_match = True
                break
            if probe and (normalized.endswith(probe) or normalized_abs.endswith(probe)):
                path_match = True
                break
            if abs_path and (abs_path == normalized_abs or abs_path.startswith(normalized_abs.rstrip("/") + "/")):
                path_match = True
                break
    if project_filter and path_filters:
        # Both filters present: row must match project AND/OR path.
        # For _merge_index_rows (removal), we want to remove rows that
        # match the project filter, but only those that also match path
        # if path filters are specified — otherwise over-deletion occurs.
        return project_match and (not path_filters or path_match)
    return project_match or path_match


def _merge_index_rows(
    existing: list[dict[str, Any]],
    refreshed: list[dict[str, Any]],
    project_filter: set[str],
    path_filters: Sequence[str],
    *,
    path_key: str = "path",
) -> list[dict[str, Any]]:
    kept = [
        row for row in existing
        if not _row_matches_scope(row, project_filter, path_filters, path_key=path_key)
    ]
    return kept + refreshed


def walk_project(root: Path) -> Iterable[Path]:
    import os
    for dirpath, dirnames, filenames in os.walk(root):
        # Prune ignored directories so os.walk doesn't descend into them
        dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS]
        for filename in filenames:
            path = Path(dirpath) / filename
            yield path


def _walk_scoped_project(
    config: WorkspaceConfig,
    service: Any,
    service_root: Path,
    path_filters: Sequence[str],
) -> Iterable[Path]:
    """Resolve exact scoped paths directly and scan only scoped directories."""
    if not path_filters:
        yield from walk_project(service_root)
        return

    prefix = config.service_logical_prefix(service).replace("\\", "/").strip("/")
    resolved_root = service_root.resolve()
    candidates: list[Path] = []
    for raw_filter in path_filters:
        raw_text = str(raw_filter or "").replace("\\", "/")
        raw_path = Path(raw_filter).expanduser()
        candidate: Path | None = None
        if raw_path.is_absolute():
            try:
                raw_path.resolve().relative_to(resolved_root)
            except ValueError:
                continue
            candidate = raw_path.resolve()
        else:
            normalized = raw_text.strip("/")
            if normalized == prefix:
                candidate = resolved_root
            elif normalized.startswith(prefix + "/"):
                candidate = resolved_root / normalized[len(prefix) + 1 :]
        if candidate is not None:
            candidates.append(candidate)

    seen: set[str] = set()
    for candidate in candidates:
        if candidate.is_file():
            key = str(candidate)
            if key not in seen:
                seen.add(key)
                yield candidate
        elif candidate.is_dir():
            for path in walk_project(candidate):
                key = str(path)
                if key not in seen:
                    seen.add(key)
                    yield path


def safe_read(path: Path, limit: int | None = None) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[:limit]
    except Exception:
        return ""


def _parse_java_task(task: tuple[str, str, Path, Any, str]) -> dict[str, Any]:
    """单参数适配层，供 ``WorkPool.map`` 与 ``ThreadPoolExecutor.map`` 共用。

    工作池按引用 pickle 任务函数，故这里必须是模块级函数而非 lambda。
    """
    return _parse_java_file(*task)


def _decode_java_result(payload: dict[str, Any], project: str, rel: str, path: Path) -> dict[str, Any]:
    """把缓存载荷还原成 ``_parse_java_file`` 的返回形状。

    ``pending_feign`` 里的 ``JavaSymbol`` 不入缓存（避免把源码再存一份），
    改为从缓存下来的 ``symbol`` 字典重建。延迟解析的 Feign 阶段改按 ``path``
    读取文本，因此命中路径不必为 Feign 先读一遍源码，四元组仍与未命中路径逐值一致。
    """
    symbol_payload = payload.get("symbol")
    if not symbol_payload:
        return {"symbol": None, "apis": [], "pending_feign": None, "mq": []}
    symbol = JavaSymbol(**symbol_payload)
    return {"symbol": symbol_payload,
            "apis": list(payload.get("apis") or []),
            "pending_feign": (project, rel, path, symbol) if payload.get("feign") else None,
            "mq": list(payload.get("mq") or [])}


def _parse_java_file(project: str, rel: str, path: Path, cache: Any = None, digest: str = "") -> dict[str, Any]:
    """Parse a single Java file for deferred assembly into indexes.

    ``cache`` 为 :class:`memory_center.platform.parse_cache.ParseCache`。产物依赖
    （项目, 相对路径, 源码）三项，三者都进缓存键——只按内容寻址会让内容相同但分属
    不同项目的文件互相顶掉，产物里的 ``project``/``file`` 字段就会错位。
    跨文件的 Feign 目标服务解析不在此缓存（它依赖 ``constant_map``）。

    ``digest`` 为调用方（扫描/切块阶段）已算好的内容 sha256；有值时本函数不再重复
    读取与哈希，**缓存命中即完全不碰盘**。为空串时自行读取并计算，行为与旧版一致。
    """
    try:
        text = None
        if not digest:
            text = safe_read(path)
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if cache is not None:
            cached = cache.get(project, rel, digest)
            if cached is not None:
                return _decode_java_result(cached, project, rel, path)
        if text is None:
            text = safe_read(path)
        symbol = parse_java_symbols(project, rel, text)
        apis = [to_dict(x) for x in parse_controllers(project, rel, text, symbol)]
        mq = [to_dict(x) for x in parse_mq_endpoints(project, rel, text, symbol)]
        mq.extend(to_dict(x) for x in parse_mq_producers(project, rel, text))
        # 与原实现保持同一求值顺序：上面的解析器可能补齐 symbol，故产物在全部解析之后生成。
        symbol_payload = to_dict(symbol)
        has_feign = "FeignClient" in symbol.annotations
        if cache is not None:
            cache.put(project, rel, digest,
                      value={"symbol": symbol_payload, "apis": apis, "mq": mq, "feign": has_feign})
        return {"symbol": symbol_payload, "apis": apis,
                "pending_feign": (project, rel, path, symbol) if has_feign else None, "mq": mq}
    except Exception:
        return {"symbol": None, "apis": [], "pending_feign": None, "mq": []}


def _sync_retrieval_indexes(
    store: WorkspaceStore,
    semantic_index: dict[str, Any],
    *,
    changed_node_ids: set[str] | None = None,
) -> dict[str, int | str]:
    """Synchronize BM25 and dense vector indexes from the rebuilt graph."""
    from ..retrieval.inverted import InvertedIndex
    from ..storage.runtime import RuntimeStore
    from ..storage.vector_index import VectorIndex

    dense_docs = [
        doc
        for doc in semantic_index.get("docs", [])
        if doc.get("node_id") and doc.get("dense_vector")
    ]
    if changed_node_ids is not None:
        dense_docs = [doc for doc in dense_docs if str(doc.get("node_id", "")) in changed_node_ids]
    dense_items = [
        (str(doc.get("node_id", "")), [float(value) for value in doc.get("dense_vector", [])])
        for doc in dense_docs
    ]

    with RuntimeStore(store.graph_db_path) as unified:
        bm25_index = InvertedIndex(unified)
        if changed_node_ids is not None and bm25_index.can_incrementally_update():
            changed_nodes = unified.nodes_by_ids(changed_node_ids)
            bm25_stats = bm25_index.replace_nodes(changed_nodes, changed_node_ids)
        else:
            # First partial refresh after an upgrade has no persisted raw term
            # frequencies. Rebuild once, then later scoped refreshes stay local.
            bm25_stats = {
                **bm25_index.rebuild(unified.all_nodes()),
                "mode": "full" if changed_node_ids is None else "full-legacy-fallback",
            }

        # Only touch VectorIndex when the rebuilt semantic_index actually
        # produced dense vectors. A reindex run with the default ``sparse``
        # backend (no ``MEMORY_CENTER_SEMANTIC_BACKEND=sentence-transformers``)
        # would otherwise silently wipe out the dense embeddings produced
        # by a previous ST run, leaving ``vector.embedding_count = 0`` even
        # though ``semantic_index_stats`` still reports a ready vector
        # candidate set from a stale on-disk file.
        vector_sync_mode = "preserved"
        vector_deleted = 0
        if dense_items:
            vector_dimension = len(dense_items[0][1])
            vector_index = VectorIndex(unified, dimension=vector_dimension)
            if changed_node_ids is None:
                vector_index.clear()
                vector_sync_mode = "full"
            else:
                vector_sync_mode = "partial"
                # Remove stale embeddings for every changed node first;
                # nodes that remain vector-eligible are then upserted from
                # ``dense_items``. This handles changed dense candidates,
                # nodes that no longer qualify for vector indexing, and
                # deleted nodes without clearing the whole VectorIndex.
                for node_id in changed_node_ids:
                    vector_index.delete_embedding(str(node_id))
                    vector_deleted += 1
            vector_count = vector_index.upsert_embeddings_batch(dense_items)
        else:
            vector_count = 0
            if changed_node_ids is not None:
                # Sparse-only or non-vector partial rebuild. Still remove
                # embeddings for changed nodes because those nodes may have
                # been deleted or may no longer be vector-eligible. Preserve
                # all other embeddings.
                vector_index = VectorIndex(unified)
                for node_id in changed_node_ids:
                    vector_index.delete_embedding(str(node_id))
                    vector_deleted += 1
                vector_sync_mode = "partial-delete-only"

    return {
        "bm25_docs": int(bm25_stats.get("doc_count", 0)),
        "bm25_sync_mode": str(bm25_stats.get("mode", "full")),
        "bm25_changed_docs": int(bm25_stats.get("changed_doc_count", 0)),
        "vector_embeddings": vector_count,
        "vector_deleted": vector_deleted,
        "vector_sync_mode": vector_sync_mode,
    }


def _method_line(symbol_by_project_file: dict[tuple[str, str], dict[str, Any]], project: str, file_path: str, method: str) -> int:
    sym = symbol_by_project_file.get((project, file_path), {})
    return int((sym.get("method_lines") or {}).get(method, 0) or 0)


def _class_or_interface_line(symbol_by_project_file: dict[tuple[str, str], dict[str, Any]], project: str, file_path: str, name: str) -> int:
    sym = symbol_by_project_file.get((project, file_path), {})
    return int((sym.get("class_lines") or {}).get(name, 0) or (sym.get("interface_lines") or {}).get(name, 0) or 0)


def parse_java_symbols(project: str, rel: str, text: str) -> JavaSymbol:
    parsed = _JAVA_PARSER.parse(text, rel)
    return JavaSymbol(
        project=project,
        file=rel,
        parser=getattr(_JAVA_PARSER, "selected_parser", getattr(_JAVA_PARSER, "name", "")),
        package=parsed.package,
        classes=parsed.classes,
        interfaces=parsed.interfaces,
        type_kinds=parsed.type_kinds,
        type_supertypes=parsed.type_supertypes,
        methods=parsed.methods,
        method_signatures=parsed.method_signatures,
        fields=parsed.fields,
        class_lines=parsed.class_lines,
        interface_lines=parsed.interface_lines,
        method_lines=parsed.method_lines,
        field_lines=parsed.field_lines,
        annotations=parsed.annotations,
        imports=parsed.imports,
        field_types=parsed.field_types,
        constants=parsed.constants,
        method_variable_types=parsed.method_variable_types,
        bean_injections=parsed.bean_injections,
        method_calls=parsed.method_calls,
        dto_field_usages=parsed.dto_field_usages,
        config_usages=parsed.config_usages,
        data_resources=parsed.data_resources,
    )


def parse_controllers(project: str, rel: str, text: str, symbol: JavaSymbol) -> list[ApiEndpoint]:
    if "RestController" not in symbol.annotations and "Controller" not in symbol.annotations:
        return []
    context = (
        _annotated_type_context(text, "RestController", ("class",))
        or _annotated_type_context(text, "Controller", ("class",))
    )
    controller = context[0] if context else (symbol.classes or [Path(rel).stem])[0]
    declaration = context[1] if context else text
    body = context[2] if context else text
    constant_map = dict(symbol.constants)
    class_prefix = _mapping_path(extract_annotation_args(declaration, "RequestMapping") or "", constant_map)
    endpoints: list[ApiEndpoint] = []
    pattern = re.compile(
        r"@(GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping|RequestMapping)\s*(?:\(([^)]*)\))?"
        r"\s*(?:\n|\r|\s)*(?:@[\w()\"=,{}./\s]+\s*)*[^;{=]+?\s+(\w+)\s*\(",
        re.MULTILINE,
    )
    for mapping, args, method_name in pattern.findall(body):
        http = extract_method_from_args(args) if mapping == "RequestMapping" else mapping.replace("Mapping", "").upper()
        endpoints.append(ApiEndpoint(project, rel, controller, http or "REQUEST", join_path(class_prefix, _mapping_path(args, constant_map)), method_name))
    return endpoints


def parse_feign_clients(project: str, rel: str, text: str, symbol: JavaSymbol, constant_map: dict[str, str] | None = None) -> list[FeignClient]:
    if "FeignClient" not in symbol.annotations:
        return []
    interface = (
        _annotated_type_name(text, "FeignClient", ("interface", "class"))
        or (symbol.interfaces or symbol.classes or [Path(rel).stem])[0]
    )
    context = _annotated_type_context(text, "FeignClient", ("interface", "class"))
    body = context[2] if context else text
    ann_args = extract_annotation_args(text, "FeignClient") or ""
    resolved_constants = {**dict(symbol.constants), **dict(constant_map or {})}
    target = extract_named_value(ann_args, "name") or extract_named_value(ann_args, "value") or extract_named_value(ann_args, "serviceId")
    if not target and resolved_constants:
        ref = extract_named_ref(ann_args, "name") or extract_named_ref(ann_args, "value") or extract_named_ref(ann_args, "serviceId")
        if ref:
            target = resolved_constants.get(ref) or resolved_constants.get(ref.split(".")[-1])
    if not target:
        target = "unknown-service"
    # 优化 4: 当 target 是类名格式（驼峰、小写开头）而非服务名时，尝试从 url 获取外部地址
    if target and target[0].islower() and not target.startswith("ucap-") and "-" not in target:
        url = extract_named_value(ann_args, "url") or ""
        if url:
            target = f"external:{url}"
    base_path = (
        _named_constant_or_value(ann_args, "path", resolved_constants)
        or extract_named_value(ann_args, "url")
        or ""
    )
    methods: list[dict[str, Any]] = []
    pattern = re.compile(
        r"@(GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping|RequestMapping)\s*(?:\(([^)]*)\))?"
        r"\s*(?:\n|\r|\s)*(?:@[\w()\"=,{}./\s]+\s*)*[^;{=]+?\s+(\w+)\s*\(",
        re.MULTILINE,
    )
    for mapping, args, method_name in pattern.findall(body):
        http = extract_method_from_args(args) if mapping == "RequestMapping" else mapping.replace("Mapping", "").upper()
        methods.append({"method_name": method_name, "http_method": http or "REQUEST", "path": join_path(base_path, _mapping_path(args, resolved_constants))})
    return [FeignClient(project, rel, interface, target, base_path, methods)]


def parse_mq_endpoints(project: str, rel: str, text: str, symbol: JavaSymbol) -> list[MqEndpoint]:
    endpoints: list[MqEndpoint] = []
    class_name = (symbol.classes or [Path(rel).stem])[0]
    for args, method_name in _listener_annotations(text, "KafkaListener"):
        raw_topic = extract_named_value(args, "topics") or extract_named_value(args, "topic") or extract_first_string(args) or ""
        topic, placeholder = _topic_value(raw_topic)
        if not topic and not placeholder:
            topic = "unknown-topic"
        group = extract_named_value(args, "groupId") or extract_named_value(args, "group")
        endpoints.append(MqEndpoint(project, rel, "kafka", topic, group, class_name, method_name, topic_placeholder=placeholder))
    for args, method_name in _listener_annotations(text, "RocketMQMessageListener"):
        raw_topic = extract_named_value(args, "topic") or ""
        topic, placeholder = _topic_value(raw_topic)
        if not topic and not placeholder:
            topic = "unknown-topic"
        group = extract_named_value(args, "consumerGroup") or extract_named_value(args, "selectorExpression")
        endpoints.append(MqEndpoint(project, rel, "rocketmq", topic, group, class_name, method_name, topic_placeholder=placeholder))
    if _is_function_consumer(text):
        binding_name = _camel_to_binding_name(class_name)
        endpoints.append(MqEndpoint(
            project=project, file=rel, kind="kafka-stream",
            topic="", group="", class_name=class_name, method_name="apply",
            topic_placeholder=f"spring.cloud.stream.bindings.{binding_name}-in-0.destination",
        ))
    return endpoints


def parse_yaml_config(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8", errors="ignore")) or {}
        values = flatten_dict(data)
        stream_bindings = _extract_stream_bindings(data)
        custom_kafka = _extract_custom_kafka_consumers(data)
        return {"values": values, "stream_bindings": stream_bindings, "custom_kafka_consumers": custom_kafka}
    except Exception:
        return {"values": {}, "stream_bindings": {}, "custom_kafka_consumers": {}}


def _extract_stream_bindings(data: dict[str, Any]) -> dict[str, str]:
    """Extract spring.cloud.stream.bindings.<name>.destination → topic mapping."""
    result: dict[str, str] = {}
    spring = data.get("spring", {})
    cloud = spring.get("cloud", {}) if isinstance(spring, dict) else {}
    stream = cloud.get("stream", {}) if isinstance(cloud, dict) else {}
    bindings = stream.get("bindings", {}) if isinstance(stream, dict) else {}
    if isinstance(bindings, dict):
        for binding_name, config in bindings.items():
            if isinstance(config, dict) and "destination" in config:
                result[binding_name] = str(config["destination"])
    return result


def _extract_custom_kafka_consumers(data: dict[str, Any]) -> dict[str, str]:
    """Extract ucap.kafka.consumers.<name>.topic → topic mapping."""
    result: dict[str, str] = {}
    ucap = data.get("ucap", {})
    kafka = ucap.get("kafka", {}) if isinstance(ucap, dict) else {}
    consumers = kafka.get("consumers", {}) if isinstance(kafka, dict) else {}
    if isinstance(consumers, dict):
        for consumer_name, config in consumers.items():
            if isinstance(config, dict) and "topic" in config:
                result[consumer_name] = str(config["topic"])
    return result


def build_topology(config: WorkspaceConfig, feigns: list[dict], apis: list[dict], mq: list[dict], config_index: list[dict]) -> dict[str, Any]:
    services = [
        {
            "name": s.name,
            "service_name": s.service_name or s.name,
            "path": s.path,
            "resolved_path": str(config.resolve_service_path(s)),
            "logical_prefix": config.service_logical_prefix(s),
            "type": s.type,
            "tags": s.tags,
        }
        for s in config.services
    ]
    service_names = {s["service_name"]: s["name"] for s in services}
    feign_edges = [{"from_project": f["project"], "to_service": f["target_service"], "to_project": service_names.get(f["target_service"]), "client": f["interface"], "file": f["file"]} for f in feigns]
    mq_topics: dict[str, dict[str, Any]] = {}
    for m in mq:
        kind = m.get("kind", "")
        is_producer = kind in ("kafka-producer", "rocketmq-producer")
        key = m["topic"] or m.get("topic_placeholder", "unknown")
        if not key:
            key = "unknown-topic"
        item = mq_topics.setdefault(key, {"topic": key, "consumers": [], "producers": []})
        entry = {"project": m["project"], "file": m["file"], "class": m.get("class_name"), "kind": kind}
        if is_producer:
            item["producers"].append(entry)
        else:
            item["consumers"].append(entry)
    return {"services": services, "feign_edges": feign_edges, "api_count": len(apis), "mq_topics": list(mq_topics.values()), "configs": config_index}


def extract_annotation_args(text: str, annotation: str) -> str | None:
    m = re.search(rf"@{annotation}\s*\((.*?)\)", text, flags=re.S)
    return m.group(1) if m else None


def _annotated_type_name(text: str, annotation: str, type_keywords: tuple[str, ...]) -> str:
    context = _annotated_type_context(text, annotation, type_keywords)
    return context[0] if context else ""


def _annotated_type_context(
    text: str,
    annotation: str,
    type_keywords: tuple[str, ...],
) -> tuple[str, str, str] | None:
    pattern = re.compile(
        rf"@{re.escape(annotation)}\s*(?:\([^)]*\))?"
        rf"(?:\s*@\w+(?:\([^)]*\))?)*"
        rf"\s*(?:public\s+|protected\s+|private\s+|abstract\s+|final\s+)*"
        rf"(?:{'|'.join(re.escape(keyword) for keyword in type_keywords)})\s+(\w+)[^{{]*{{",
        re.S,
    )
    match = pattern.search(text)
    if not match:
        return None
    open_brace = text.find("{", match.start(), match.end())
    if open_brace < 0:
        return None
    close_brace = _matching_brace(text, open_brace)
    return match.group(1), text[match.start():open_brace], text[open_brace + 1:close_brace]


def _matching_brace(text: str, open_brace: int) -> int:
    depth = 0
    for index in range(open_brace, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return index
    return len(text)


def _named_constant_or_value(args: str, name: str, constant_map: dict[str, str]) -> str:
    value = extract_named_value(args, name)
    if value is not None:
        return value
    ref = extract_named_ref(args, name)
    if not ref:
        return ""
    return constant_map.get(ref) or constant_map.get(ref.split(".")[-1], "")


def _mapping_path(args: str, constant_map: dict[str, str]) -> str:
    value = extract_named_value(args, "value") or extract_named_value(args, "path") or extract_first_string(args)
    if value is not None:
        return value
    ref = extract_named_ref(args, "value") or extract_named_ref(args, "path")
    if not ref:
        match = re.search(r"^\s*([\w.]+)\s*$", args or "")
        ref = match.group(1) if match else ""
    return constant_map.get(ref) or constant_map.get(ref.split(".")[-1], "") if ref else ""


def extract_annotation_value(text: str, annotation: str) -> str | None:
    args = extract_annotation_args(text, annotation)
    if args is None:
        return None
    return extract_named_value(args, "value") or extract_first_string(args)


def extract_first_string(args: str) -> str | None:
    m = re.search(r'"([^"]*)"', args or "")
    return m.group(1) if m else None


def extract_named_value(args: str, name: str) -> str | None:
    m = re.search(rf"\b{name}\s*=\s*(?:\{{\s*)?\"([^\"]+)\"", args or "")
    return m.group(1) if m else None


def extract_named_ref(args: str, name: str) -> str | None:
    """Extract a non-string named value (constant reference like ClassName.CONSTANT_NAME)."""
    m = re.search(rf'\b{name}\s*=\s*([\w.]+)', args or "")
    # Filter out string literals that were already handled by extract_named_value
    if m and m.group(1).startswith('"'):
        return None
    return m.group(1) if m else None


def _build_constant_map(symbol_index: list[dict[str, Any]]) -> dict[str, str]:
    """Build a map from CONSTANT_NAME and ClassName.CONSTANT_NAME to string values,
    using dedicated constants with field_types as a legacy fallback."""
    constant_map: dict[str, str] = {}
    for sym in symbol_index:
        values = sym.get("constants") or sym.get("field_types", {})
        for fname, fval in values.items():
            if fval and isinstance(fval, str) and not fval.startswith(("com.", "java.", "org.", "List", "Map", "Set", "Integer", "Long", "Boolean")):
                constant_map[fname] = fval
                for cls in sym.get("classes", []) + sym.get("interfaces", []):
                    constant_map[f"{cls}.{fname}"] = fval
    return constant_map


def _extract_topic_placeholder(raw: str | None) -> str:
    m = re.search(r"\$\{([^}:]+)(?::[^}]*)?\}", raw or "")
    return m.group(1) if m else ""


def _topic_value(raw: str | None) -> tuple[str, str]:
    if not raw:
        return "", ""
    placeholder = _extract_topic_placeholder(raw)
    if placeholder:
        return "", placeholder
    return clean_topic(raw), ""


def _camel_to_binding_name(value: str) -> str:
    if not value:
        return ""
    return value[:1].lower() + value[1:]


def extract_method_from_args(args: str) -> str | None:
    m = re.search(r"RequestMethod\.(GET|POST|PUT|DELETE|PATCH)", args or "")
    return m.group(1) if m else None


def join_path(a: str, b: str) -> str:
    left = (a or "").strip()
    right = (b or "").strip()
    value = "/" + "/".join(x.strip("/") for x in [left, right] if x.strip("/"))
    return value if value != "/" else ""


def clean_topic(topic: str) -> str:
    return topic.strip().strip("{}").strip().strip('"')


def _listener_annotations(text: str, annotation: str) -> list[tuple[str, str | None]]:
    pattern = re.compile(
        rf"@{annotation}\s*\(([^)]*)\)\s*(?:\n|\r|\s)*(?:@[\w()\"=,{{}}./\s]+\s*)*"
        r"(?:public|private|protected)\s+(?:static\s+)?[\w<>, ?\.\[\]]+\s+(\w+)\s*\(",
        re.MULTILINE,
    )
    return [(args, method_name) for args, method_name in pattern.findall(text)]


def _is_function_consumer(text: str) -> bool:
    """Detect Spring Cloud Stream function-style consumers: implements Function<ConsumerRecord<...>> or similar patterns."""
    if re.search(r'\b(?:implements|extends)\s+[\w\s,<>.]*Function\s*<', text):
        if 'ConsumerRecord' in text:
            return True
        # Also detect spring.messaging Message<?> pattern
        if 'Message<' in text or 'org.springframework.messaging' in text:
            return True
    return False


def parse_mq_producers(project: str, rel: str, text: str) -> list[MqEndpoint]:
    producers: list[MqEndpoint] = []
    # KafkaTemplate.send(topic, ...) - literal topic
    for m in re.finditer(r'kafkaTemplate\s*\.\s*(?:send|sendDefault)\s*\(\s*"([^"]+)"', text):
        producers.append(MqEndpoint(project=project, file=rel, kind="kafka-producer", topic=m.group(1)))
    # RocketMQTemplate.syncSend / asyncSend / send(topic, ...) - literal topic
    for m in re.finditer(r'rocketMQTemplate\s*\.\s*(?:syncSend|asyncSend|send)\s*\(\s*"([^"]+)"', text):
        producers.append(MqEndpoint(project=project, file=rel, kind="rocketmq-producer", topic=m.group(1)))
    return producers


def flatten_dict(data: dict[str, Any], prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in data.items():
        key = f"{prefix}.{k}" if prefix else str(k)
        if isinstance(v, dict):
            out.update(flatten_dict(v, key))
        else:
            out[key] = str(v)
    return out


def build_graph_store(config: WorkspaceConfig, store: WorkspaceStore, *, project_filter: set[str] | None = None, path_filters: Sequence[str] | None = None) -> dict[str, Any]:
    with RuntimeStore(store.graph_db_path) as graph:
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        partial = bool(project_filter or path_filters)
        pf = project_filter or set()
        pfs = list(path_filters or [])

        ws_id = node_id("Workspace", config.workspace)
        nodes.append(GraphNode(ws_id, "Workspace", config.workspace))

        file_index = store.read_json_prefer_backend("file-index.json", [])
        if pfs:
            pfs = _graph_scope_path_filters(file_index, pfs)
        symbols = store.read_json_prefer_backend("java-symbol-index.json", [])
        # A scoped refresh must write only the changed graph slice, while
        # resolving calls against the complete persisted workspace symbol
        # index. Restricting the resolver to changed files turns every
        # cross-file call into an unresolved edge on an otherwise harmless
        # local refresh.
        resolver_symbols = list(symbols)
        apis_full = store.read_json_prefer_backend("api-index.json", [])
        feigns = store.read_json_prefer_backend("feign-index.json", [])
        mq = store.read_json_prefer_backend("mq-index.json", [])
        configs = store.read_json_prefer_backend("config-index.json", [])
        topology = store.read_json_prefer_backend("service-topology.json", {})
        symbol_by_project_file = {
            (sym.get("project", ""), sym.get("file", "")): sym
            for sym in symbols
        }
        if partial:
            file_index = [r for r in file_index if _row_matches_scope(r, pf, pfs)]
            symbols = [r for r in symbols if _row_matches_scope(r, pf, pfs, path_key="file")]
            apis = [r for r in apis_full if _row_matches_scope(r, pf, pfs, path_key="file")]
            feigns = [r for r in feigns if _row_matches_scope(r, pf, pfs, path_key="file")]
            mq = [r for r in mq if _row_matches_scope(r, pf, pfs, path_key="file")]
            configs = [r for r in configs if _row_matches_scope(r, pf, pfs)]
        else:
            apis = apis_full

        # Index APIs by (http_method, normalized_path) so the Feign->Endpoint
        # association becomes O(|feign_methods|) instead of |feign_methods| *
        # |apis|.  Partial reindex still wires Feign methods against the full
        # API set so cross-project links survive a scoped rebuild.
        feign_match_pool = apis_full if partial else apis
        api_lookup = _build_api_lookup(feign_match_pool)

        class_locations: dict[str, list[dict[str, Any]]] = {}
        declared_method_ids: set[str] = {
            node_id("Method", sym["project"], cls, method)
            for sym in resolver_symbols
            for cls in sym.get("classes", []) + sym.get("interfaces", [])
            for method in sym.get("methods", [])
        }
        field_locations: dict[str, list[str]] = {}
        field_locations_by_class: dict[tuple[str, str], list[str]] = {}
        field_type_by_file: dict[str, dict[str, str]] = {}
        call_resolver = JavaCallResolver(build_java_class_index(resolver_symbols))

        for svc in config.services:
            if pf and svc.name not in pf:
                continue
            sid = node_id("Service", svc.name)
            nodes.append(GraphNode(sid, "Service", svc.name, svc.name, metadata={"service_name": svc.service_name or svc.name, "path": svc.path, "type": svc.type, "tags": svc.tags}))
            edges.append(GraphEdge(edge_id("CONTAINS", ws_id, sid), ws_id, sid, "CONTAINS", 1.0, {"evidence": "workspace.yaml service"}))

        for item in file_index:
            fid = node_id("File", item["path"])
            sid = node_id("Service", item["project"])
            nodes.append(GraphNode(fid, "File", Path(item["path"]).name, item["project"], item["path"], metadata=item))
            edges.append(GraphEdge(edge_id("CONTAINS", sid, fid), sid, fid, "CONTAINS", 1.0, {"evidence": "file path under service root"}))

        for cfg in configs:
            fid = node_id("File", cfg["path"])
            for key, value in cfg.get("values", {}).items():
                kid = node_id("ConfigKey", cfg["project"], key)
                nodes.append(GraphNode(kid, "ConfigKey", key, cfg["project"], cfg["path"], metadata={"value": value}))
                edges.append(GraphEdge(edge_id("DECLARES_CONFIG", fid, kid), fid, kid, "DECLARES_CONFIG", 1.0, {"evidence": "YAML config key"}))

        for sym in symbols:
            fid = node_id("File", sym["file"])
            field_type_by_file[sym["file"]] = sym.get("field_types", {})
            class_lines = sym.get("class_lines", {})
            interface_lines = sym.get("interface_lines", {})
            method_lines = sym.get("method_lines", {})
            field_lines = sym.get("field_lines", {})
            for cls in sym.get("classes", []) + sym.get("interfaces", []):
                cid = node_id("Class", sym["project"], cls)
                class_locations.setdefault(cls, []).append({"id": cid, "project": sym["project"], "file": sym["file"]})
                class_line = int(class_lines.get(cls) or interface_lines.get(cls) or 0)
                nodes.append(
                    GraphNode(
                        cid,
                        "Class",
                        cls,
                        sym["project"],
                        sym["file"],
                        class_line,
                        metadata={
                            "package": sym.get("package"),
                            "annotations": sym.get("annotations", []),
                            "type_kind": (sym.get("type_kinds", {}) or {}).get(cls, "class"),
                            "supertypes": (sym.get("type_supertypes", {}) or {}).get(cls, []),
                            "parser": sym.get("parser") or "regex",
                        },
                    )
                )
                edges.append(GraphEdge(edge_id("DECLARES", fid, cid), fid, cid, "DECLARES", 1.0, {"evidence": "class/interface declaration"}))
                for m in sym.get("methods", []):
                    mid = node_id("Method", sym["project"], cls, m)
                    declared_method_ids.add(mid)
                    method_line = int(method_lines.get(m) or 0)
                    signature = next((item for item in sym.get("method_signatures", []) if item.get("name") == m), {})
                    nodes.append(GraphNode(mid, "Method", f"{cls}.{m}", sym["project"], sym["file"], method_line, metadata={"method": m, "return_type": signature.get("return_type", "")}))
                    edges.append(GraphEdge(edge_id("DECLARES", cid, mid), cid, mid, "DECLARES", 1.0, {"evidence": "method declaration"}))
                for fld in sym.get("fields", []):
                    field_id = node_id("Field", sym["project"], cls, fld)
                    field_locations.setdefault(fld, []).append(field_id)
                    field_locations_by_class.setdefault((cls, fld), []).append(field_id)
                    field_line = int(field_lines.get(fld) or 0)
                    nodes.append(GraphNode(field_id, "Field", f"{cls}.{fld}", sym["project"], sym["file"], field_line, metadata={"type": sym.get("field_types", {}).get(fld)}))
                    edges.append(GraphEdge(edge_id("DECLARES", cid, field_id), cid, field_id, "DECLARES", 1.0, {"evidence": "field declaration"}))

        # Dispatch edges: call resolution lands on the declared (often
        # interface) method, which leaves downstream traversals stranded.
        # For every visible override emit DISPATCHES_TO from the parent
        # method into the child method so walks/impacts cross into impls.
        methods_by_class: dict[tuple[str, str], set[str]] = {}
        symbols_by_class_location: dict[tuple[str, str, str], dict[str, Any]] = {}
        for sym in resolver_symbols:
            for cls in sym.get("classes", []) + sym.get("interfaces", []):
                methods_by_class.setdefault((sym.get("project", ""), cls), set()).update(sym.get("methods", []))
                symbols_by_class_location[(sym.get("project", ""), cls, sym.get("file", ""))] = sym
        for sym in symbols:
            supertypes = sym.get("type_supertypes") or {}
            for cls in sym.get("classes", []) + sym.get("interfaces", []):
                for parent in supertypes.get(cls, []):
                    locations = class_locations.get(parent, [])
                    same_project = [loc for loc in locations if loc["project"] == sym["project"]]
                    for loc in same_project or locations:
                        parent_methods = methods_by_class.get((loc["project"], parent), set())
                        parent_symbol = symbols_by_class_location.get((loc["project"], parent, loc["file"]), {})
                        for m in sym.get("methods", []):
                            if m not in parent_methods:
                                continue
                            parent_signatures = _dispatchable_method_identities(parent_symbol, m)
                            child_signatures = _dispatchable_method_identities(sym, m)
                            if parent_signatures == set() or child_signatures == set():
                                continue
                            if (
                                parent_signatures is not None
                                and child_signatures is not None
                                and parent_signatures.isdisjoint(child_signatures)
                            ):
                                continue
                            parent_mid = node_id("Method", loc["project"], parent, m)
                            child_mid = node_id("Method", sym["project"], cls, m)
                            edges.append(GraphEdge(edge_id("DISPATCHES_TO", parent_mid, child_mid), parent_mid, child_mid, "DISPATCHES_TO", 0.9, {"evidence": f"{cls} overrides {parent}.{m}"}))

        # Import edges are file-level probable dependencies.
        for sym in symbols:
            for imp in sym.get("imports", []):
                imported_name = imp.split(".")[-1]
                for target in class_locations.get(imported_name, []):
                    edges.append(GraphEdge(edge_id("IMPORTS", node_id("File", sym["file"]), node_id("File", target["file"])), node_id("File", sym["file"]), node_id("File", target["file"]), "IMPORTS", 0.55, {"evidence": f"import {imp}", "import": imp}))

        for api in apis:
            eid = node_id("Endpoint", api["project"], api["http_method"], api["path"])
            cid = node_id("Class", api["project"], api["controller"])
            mid = node_id("Method", api["project"], api["controller"], api.get("method_name") or "unknown")
            endpoint_line = _method_line(symbol_by_project_file, api["project"], api["file"], api.get("method_name") or "")
            nodes.append(GraphNode(eid, "Endpoint", f"{api['http_method']} {api['path']}", api["project"], api["file"], endpoint_line, metadata=api))
            edges.append(GraphEdge(edge_id("EXPOSES_ENDPOINT", cid, eid), cid, eid, "EXPOSES_ENDPOINT", 1.0, {"evidence": "Spring MVC mapping annotation"}))
            edges.append(GraphEdge(edge_id("HANDLES_ENDPOINT", mid, eid), mid, eid, "HANDLES_ENDPOINT", 0.9, {"evidence": "mapping method"}))

        for f in feigns:
            fc_id = node_id("FeignClient", f["project"], f["interface"])
            cid = node_id("Class", f["project"], f["interface"])
            feign_line = _class_or_interface_line(symbol_by_project_file, f["project"], f["file"], f["interface"])
            nodes.append(GraphNode(fc_id, "FeignClient", f["interface"], f["project"], f["file"], feign_line, metadata=f))
            edges.append(GraphEdge(edge_id("DECLARES", cid, fc_id), cid, fc_id, "DECLARES", 1.0, {"evidence": "@FeignClient"}))
            target_project = topology_service_project(topology, f.get("target_service")) or f.get("target_service", "unknown")
            target_service_id = node_id("Service", target_project)
            edges.append(GraphEdge(edge_id("CALLS_SERVICE", fc_id, target_service_id), fc_id, target_service_id, "CALLS_SERVICE", 0.9, {"evidence": "@FeignClient target service", "target_service": f.get("target_service")}))
            for method in f.get("methods", []):
                fm_id = node_id("FeignMethod", f["project"], f["interface"], method.get("method_name", "unknown"))
                feign_method_line = _method_line(symbol_by_project_file, f["project"], f["file"], method.get("method_name", "unknown"))
                nodes.append(GraphNode(fm_id, "FeignMethod", f"{f['interface']}.{method.get('method_name')}", f["project"], f["file"], feign_method_line, metadata=method))
                edges.append(GraphEdge(edge_id("DECLARES", fc_id, fm_id), fc_id, fm_id, "DECLARES", 1.0, {"evidence": "Feign interface method"}))
                for api in _candidate_apis_for_feign_method(api_lookup, f, method):
                    if _endpoint_matches(f, method, api):
                        ep_id = node_id("Endpoint", api["project"], api["http_method"], api["path"])
                        edges.append(GraphEdge(edge_id("IMPLEMENTS_FEIGN", fm_id, ep_id), fm_id, ep_id, "IMPLEMENTS_FEIGN", 0.78, {"evidence": "HTTP method/path matched Feign method to Controller endpoint"}))

        for m in mq:
            kind = m.get("kind", "")
            topic = m["topic"] or m.get("topic_placeholder", "unknown")
            if not topic:
                topic = "unknown-topic"
            topic_id = node_id("MQTopic", topic)
            is_producer = kind in ("kafka-producer", "rocketmq-producer")
            node_kind = "MQProducer" if is_producer else "MQConsumer"
            node_name = m.get("class_name") or Path(m["file"]).stem
            node_id_val = node_id(node_kind, m["project"], node_name, topic)
            edge_type = "PRODUCES_TOPIC" if is_producer else "CONSUMES_TOPIC"
            evidence = f"{kind} {'producer' if is_producer else 'listener'}"
            nodes.append(GraphNode(topic_id, "MQTopic", topic, metadata={"kind": kind}))
            nodes.append(GraphNode(node_id_val, node_kind, node_name, m["project"], m["file"], metadata=m))
            edges.append(GraphEdge(edge_id(edge_type, node_id_val, topic_id), node_id_val, topic_id, edge_type, 1.0, {"evidence": evidence}))
            edges.append(GraphEdge(edge_id("CONTAINS", node_id("Service", m["project"]), node_id_val), node_id("Service", m["project"]), node_id_val, "CONTAINS"))

        # Relationship facts extracted from Java bodies/fields.
        for sym in symbols:
            owner_classes = sym.get("classes", []) + sym.get("interfaces", [])
            owner_class = owner_classes[0] if owner_classes else Path(sym["file"]).stem
            owner_class_id = node_id("Class", sym["project"], owner_class)

            for inj in sym.get("bean_injections", []):
                target_type = inj.get("type")
                target_candidates = class_locations.get(target_type, [])
                target_id = target_candidates[0]["id"] if target_candidates else node_id("Bean", sym["project"], target_type or inj.get("field_name", "unknown"))
                if not target_candidates:
                    nodes.append(
                        GraphNode(
                            target_id,
                            "Bean",
                            target_type or inj.get("field_name", "unknown"),
                            sym["project"],
                            sym["file"],
                            metadata=inj,
                        )
                    )
                edges.append(GraphEdge(edge_id("INJECTS_BEAN", owner_class_id, target_id), owner_class_id, target_id, "INJECTS_BEAN", 0.82, {"evidence": inj}))

            for call in sym.get("method_calls", []):
                resolved = call_resolver.resolve_call(sym, call)
                source_id = _source_method_id(sym, resolved.source_class or owner_class, call) or owner_class_id
                target_id = node_id("Method", resolved.target_project, resolved.target_class, resolved.target_method)
                if target_id not in declared_method_ids:
                    nodes.append(
                        GraphNode(
                            target_id,
                            "Method",
                            f"{resolved.target_class}.{resolved.target_method}",
                            resolved.target_project,
                            resolved.target_file,
                            metadata={
                                "inferred": True,
                                "resolution_level": resolved.resolution_level,
                                "target_fqcn": resolved.target_fqcn,
                            },
                        )
                    )
                edges.append(
                    GraphEdge(
                        edge_id("CALLS_METHOD", source_id, target_id),
                        source_id,
                        target_id,
                        "CALLS_METHOD",
                        resolved.confidence,
                        {
                            "evidence": resolved.evidence,
                            "receiver": resolved.receiver,
                            "receiver_type": resolved.receiver_type,
                            "resolution_level": resolved.resolution_level,
                            "target_fqcn": resolved.target_fqcn,
                            "target_file": resolved.target_file,
                            "arg_count": resolved.arg_count,
                            "matched_signature": resolved.matched_signature,
                            "inferred_target": resolved.inferred_target,
                            "unresolved_reason": resolved.unresolved_reason,
                        },
                    )
                )

            for usage in sym.get("dto_field_usages", []):
                source_id = _source_method_id(sym, owner_class, usage) or owner_class_id
                receiver_type = usage.get("receiver_type")
                matching_fields = []
                if receiver_type:
                    matching_fields.extend(
                        field_locations_by_class.get((receiver_type, usage.get("field")), [])
                    )
                if not matching_fields:
                    matching_fields = field_locations.get(usage.get("field"), [])[:5]
                for fid in matching_fields[:5]:
                    edges.append(
                        GraphEdge(
                            edge_id("READS_FIELD", source_id, fid),
                            source_id,
                            fid,
                            "READS_FIELD",
                            0.74 if receiver_type else 0.62,
                            {"evidence": usage, "receiver_type": receiver_type},
                        )
                    )

            for usage in sym.get("config_usages", []):
                key = usage.get("key")
                kid = node_id("ConfigKey", sym["project"], key)
                nodes.append(GraphNode(kid, "ConfigKey", key, sym["project"], sym["file"], metadata=usage))
                edges.append(GraphEdge(edge_id("READS_CONFIG", owner_class_id, kid), owner_class_id, kid, "READS_CONFIG", 0.84, {"evidence": usage}))

            for resource in sym.get("data_resources", []):
                # Keep the ontology type stable while retaining the concrete
                # storage technology in metadata for filtering and display.
                resource_metadata = {**resource, "resource_kind": resource.get("kind", "DataResource")}
                rid = node_id("DataResource", resource.get("kind", "DataResource"), resource.get("name", "unknown"))
                nodes.append(GraphNode(rid, "DataResource", resource.get("name", "unknown"), sym["project"], sym["file"], metadata=resource_metadata))
                edges.append(GraphEdge(edge_id("USES_DATA_RESOURCE", owner_class_id, rid), owner_class_id, rid, "USES_DATA_RESOURCE", 0.72, {"evidence": resource}))

        # ── Multi-language structural pass ────────────────────────────────
        #
        # Non-Java files registered in language_registry get walked by
        # the cross-language structural parser and contribute generic
        # graph nodes/edges (Module / Class / Function + DEFINES /
        # IMPORTS / CALLS). This is the entry point added in P0-2.
        #
        # The path filter mirrors the Java collection above so partial
        # reindex still respects --project / --path scopes.
        from . import multilang_indexer

        def _multilang_filter(svc, path):
            if path_filters and not _path_matches_filters(config, svc, path, path_filters):
                return False
            return True

        service_by_root = {
            str(config.resolve_service_path(service).resolve()): service
            for service in config.services
            if not project_filter or service.name in project_filter
        }

        def _multilang_scope_walker(root: Path) -> Iterable[Path]:
            service = service_by_root.get(str(root.resolve()))
            if service is None:
                return ()
            return _walk_scoped_project(config, service, root, path_filters or [])

        multilang_tasks = multilang_indexer.collect_multilang_files(
            (s for s in config.services if not project_filter or s.name in project_filter),
            config,
            _multilang_scope_walker,
            _multilang_filter,
        )
        for ml_project, ml_rel, ml_path in multilang_tasks:
            ml_result = multilang_indexer.parse_structural(ml_path)
            if ml_result is None or ml_result.is_empty():
                continue
            ml_nodes, ml_edges = multilang_indexer.emit_graph_elements(
                ml_project, ml_rel, ml_result
            )
            nodes.extend(ml_nodes)
            edges.extend(ml_edges)

        if partial:
            graph_counts = graph.partial_rebuild(nodes, edges, pf, pfs)
        else:
            graph.rebuild(nodes, edges, clear_search=False)
            graph_counts = {**graph.counts(), **graph.rebuild_search_index()}
        store.write_json("graph-summary.json", graph_counts)
        return graph_counts


_STANDARD_HTTP_METHODS = {"GET", "POST", "PUT", "DELETE", "PATCH"}

def _normalize_path_params(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "{param}", path)


_API_LOOKUP_WILDCARD = ""


def _build_api_lookup(apis: list[dict[str, Any]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """Index APIs by ``(http_method, normalized_path)``.

    Two keys are stored per API: the http method, and the "wildcard" key
    ``""`` for methods whose http method is non-standard (rare).  The
    wildcard bucket is consulted as a fallback so legacy non-standard methods
    keep matching exactly like the legacy linear scan.
    """
    lookup: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for api in apis:
        method = (api.get("http_method") or "").upper()
        norm = _normalize_path_params((api.get("path") or "").strip("/"))
        lookup.setdefault((method, norm), []).append(api)
        lookup.setdefault((_API_LOOKUP_WILDCARD, norm), []).append(api)
    return lookup


def _candidate_apis_for_feign_method(
    api_lookup: dict[tuple[str, str], list[dict[str, Any]]],
    feign: dict[str, Any],
    method: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return APIs that could match a Feign method without scanning the full list.

    We consult two normalized keys: the path declared on the Feign method and
    the composed ``base_path + method_path``.  The standard http method is
    used as the primary key; the wildcard bucket is consulted if the method's
    http method is non-standard so legacy behaviour is preserved.
    """
    feign_http = (method.get("http_method") or "").upper()
    method_norm = _normalize_path_params((method.get("path") or "").strip("/"))
    base_path = feign.get("base_path") or ""
    composed_norm = (
        _normalize_path_params(join_path(base_path, method.get("path") or "").strip("/"))
        if base_path
        else ""
    )
    out: list[dict[str, Any]] = []
    seen: set[int] = set()

    def _extend(key: tuple[str, str]) -> None:
        for api in api_lookup.get(key, []):
            ident = id(api)
            if ident in seen:
                continue
            seen.add(ident)
            out.append(api)

    keys: list[tuple[str, str]] = [
        (feign_http, method_norm),
    ]
    if composed_norm and composed_norm != method_norm:
        keys.append((feign_http, composed_norm))
    if feign_http not in _STANDARD_HTTP_METHODS:
        keys.append((_API_LOOKUP_WILDCARD, method_norm))
        if composed_norm and composed_norm != method_norm:
            keys.append((_API_LOOKUP_WILDCARD, composed_norm))
    for key in keys:
        _extend(key)
    return out


def _endpoint_matches(feign: dict[str, Any], method: dict[str, Any], api: dict[str, Any]) -> bool:
    api_path = (api.get("path") or "").strip("/")
    feign_http = (method.get("http_method") or "").upper()
    api_http = (api.get("http_method") or "").upper()

    if feign_http in _STANDARD_HTTP_METHODS and api_http in _STANDARD_HTTP_METHODS and feign_http != api_http:
        return False

    feign_norm = _normalize_path_params((method.get("path") or "").strip("/"))
    api_norm = _normalize_path_params(api_path)

    # Direct match: method path already includes base_path prefix
    if feign_norm == api_norm:
        return True

    # Compose full path: base_path + method_path for cases where method.path
    # does NOT include the base (e.g. base=/article, method path=/move)
    base_norm = _normalize_path_params((feign.get("base_path") or "").strip("/"))
    if base_norm:
        composed_norm = _normalize_path_params(join_path(feign.get("base_path") or "", method.get("path") or "").strip("/"))
        if composed_norm == api_norm:
            return True

    return False


def _source_method_id(sym: dict[str, Any], owner_class: str, fact: dict[str, Any]) -> str | None:
    owner_method = fact.get("owner_method")
    if not owner_method:
        return None
    return node_id("Method", sym["project"], owner_class, owner_method)


def _dispatchable_method_identities(sym: dict[str, Any], method_name: str) -> set[str] | None:
    """Return provably dispatchable signatures, or None for legacy unknown data."""

    signatures = [
        item
        for item in (sym.get("method_signatures", []) or [])
        if str(item.get("name") or "") == method_name
    ]
    if not signatures:
        return None
    modifiers_by_identity: dict[str, set[str]] = {}
    for signature in signatures:
        identity = str(signature.get("identity") or "")
        if identity:
            modifiers_by_identity.setdefault(identity, set()).update(
                str(value) for value in (signature.get("modifiers", []) or [])
            )
    return {
        identity
        for identity, modifiers in modifiers_by_identity.items()
        if not modifiers & {"private", "static"}
    }


def topology_service_project(topology: dict[str, Any], service_name: str | None) -> str | None:
    if not service_name:
        return None
    for svc in topology.get("services", []):
        if svc.get("service_name") == service_name or svc.get("name") == service_name:
            return svc.get("name")
    # Fuzzy: strip -app suffix from either side (Spring app name vs workspace project name)
    service_no_app = service_name[:-4] if service_name.endswith("-app") else service_name
    for svc in topology.get("services", []):
        svc_name = svc.get("service_name") or ""
        svc_proj = svc.get("name") or ""
        if svc_name == service_no_app or svc_proj == service_no_app:
            return svc.get("name")
        svc_name_no_app = svc_name[:-4] if svc_name.endswith("-app") else svc_name
        svc_proj_no_app = svc_proj[:-4] if svc_proj.endswith("-app") else svc_proj
        if service_no_app == svc_name_no_app or service_no_app == svc_proj_no_app:
            return svc.get("name")
    return None
