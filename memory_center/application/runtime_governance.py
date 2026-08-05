"""Read-only operating view for real workspace performance and storage."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from memory_center.core.storage.workspace import WorkspaceStore


def workspace_runtime_governance(workspace_file: str | Path, *, warning_gib: int = 8) -> dict[str, Any]:
    """Aggregate bounded operating signals without scanning source or writing state."""
    store = WorkspaceStore(workspace_file)
    storage = store.storage_budget_report(warning_bytes=max(1, warning_gib) * 1024**3)
    initialized = store.graph_db_path.exists()
    if initialized:
        snapshots = store.read_jsonl("workspace-performance-snapshots.jsonl", limit=20)
        latest = snapshots[-1] if snapshots else {}
        performance = {
            "samples": len(snapshots),
            "status": "healthy" if snapshots else "baseline_missing",
            "latest": latest,
            "next_action": "保持当前采样节奏。" if snapshots else "运行 performance-snapshot 建立 P95 基线。",
        }
        hnsw_path = store.graph_db_path.with_suffix(".hnsw")
        vector_ann = {"ann_ready": hnsw_path.exists(), "hnsw_index_present": hnsw_path.exists(), "status": "file_probe"}
        index = store.read_json("index-control.json", {}) or {}
        jobs = store.read_json("workspace-jobs.json", []) or []
    else:
        performance = {
            "samples": 0,
            "status": "not_indexed",
            "next_action": "完成显式 reindex 后再建立性能快照。",
            "snapshots": [],
        }
        vector_ann = {"ann_ready": False, "dense_doc_count": 0, "status": "not_indexed"}
        index = {
            "status": "uninitialized",
            "active_generation": "",
            "previous_generation": "",
            "staging_generation": "",
        }
        jobs = []
    active_jobs = [job for job in jobs if job.get("status") in {"queued", "running", "cancel_requested"}]
    findings: list[dict[str, str]] = []
    if performance.get("status") != "healthy":
        findings.append(
            {
                "area": "performance",
                "severity": "warning",
                "action": str(performance.get("next_action", "运行 performance-snapshot。")),
            }
        )
    if storage.get("status") != "healthy":
        findings.append(
            {"area": "storage", "severity": "warning", "action": str(storage.get("next_action", "查看空间预算。"))}
        )
    if index.get("status") != "ready":
        findings.append(
            {
                "area": "index",
                "severity": "warning",
                "action": "先确认索引 generation 状态；仅在需要时显式局部刷新或重建。",
            }
        )
    if active_jobs:
        findings.append(
            {"area": "jobs", "severity": "info", "action": "轮询 job-status；任务终态后再评估 P95 和空间变化。"}
        )
    return {
        "schema_version": 1,
        "mode": "read_only",
        "performance": performance,
        "storage": storage,
        "index": {
            key: index.get(key)
            for key in ("status", "active_generation", "previous_generation", "staging_generation", "updated_at")
        },
        "vector_ann": vector_ann,
        "active_jobs": active_jobs,
        "findings": findings,
        "status": "warning" if any(item["severity"] == "warning" for item in findings) else "healthy",
        "next_action": findings[0]["action"] if findings else "运行性能快照并在变更后复查；当前不需要维护动作。",
    }
