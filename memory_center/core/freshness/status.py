"""IndexFreshnessService — track whether the graph index is up-to-date.

Provides freshness status so MCP responses can warn agents when the
index may be stale and they should read live files before editing.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from memory_center.core.storage.workspace import WorkspaceStore
from memory_center.core.workspace.config import load_workspace_config
from memory_center.core.workspace.shape import analyze_workspace_shape


@dataclass
class FreshnessStatus:
    """Freshness state for a workspace."""
    status: str = "unknown"  # fresh | pending | stale | unknown
    last_indexed_at: str = ""
    changed_files: list[str] = field(default_factory=list)
    pending_files: list[str] = field(default_factory=list)
    staleness_level: str = "unknown"  # low | medium | high | unknown
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "last_indexed_at": self.last_indexed_at,
            "changed_files": self.changed_files,
            "pending_files": self.pending_files,
            "staleness_level": self.staleness_level,
            "message": self.message,
        }


class IndexFreshnessService:
    """Check index freshness by comparing file mtimes against last index time."""

    def __init__(self, workspace_file: str | Path):
        self._store = WorkspaceStore(workspace_file)
        self._workspace_file = str(workspace_file)

    def check(self, threshold_seconds: int = 3600) -> FreshnessStatus:
        """Check freshness. Returns status: fresh/pending/stale/unknown."""
        try:
            index_counts = self._store.read_json_prefer_backend("file-index.json", [])
        except Exception:
            return FreshnessStatus(status="unknown", message="无法读取索引元数据")

        if not index_counts:
            return FreshnessStatus(status="stale", staleness_level="high", message="索引为空，需要先运行 reindex")

        # Prefer the published graph summary. Runtime audit, governance, and
        # memory writes share graph.db, so its mtime is not an index timestamp.
        graph_summary_path = self._store.index_dir / "graph-summary.json"
        if graph_summary_path.exists():
            mtime = graph_summary_path.stat().st_mtime
            return self._status_from_index_mtime(mtime, threshold_seconds)

        # Legacy workspaces may not yet have a published graph summary.
        graph_path = Path(self._store.graph_db_path)
        if graph_path.exists():
            return self._status_from_index_mtime(graph_path.stat().st_mtime, threshold_seconds)

        return FreshnessStatus(status="unknown", message="无法检测索引文件")

    @staticmethod
    def _status_from_index_mtime(mtime: float, threshold_seconds: int) -> FreshnessStatus:
        age = time.time() - mtime
        last_indexed_at = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(mtime))
        if age < threshold_seconds:
            return FreshnessStatus(
                status="fresh",
                staleness_level="low",
                last_indexed_at=last_indexed_at,
                message=f"索引新鲜（{int(age)}秒前更新）",
            )
        if age < threshold_seconds * 4:
            return FreshnessStatus(
                status="pending",
                staleness_level="medium",
                last_indexed_at=last_indexed_at,
                message=f"索引可能过期（{int(age)}秒前更新），建议对关键文件 Read 实时内容",
            )
        return FreshnessStatus(
            status="stale",
            staleness_level="high",
            last_indexed_at=last_indexed_at,
            message=f"索引较旧（{int(age)}秒前更新），建议先运行 reindex",
        )

    def check_files(self, file_paths: list[str]) -> dict[str, str]:
        """Check freshness of specific files. Returns {path: fresh|stale|unknown}."""
        results = {}
        for fp in file_paths:
            abs_path = Path(fp)
            if not abs_path.is_absolute():
                # Try to resolve relative to workspace
                abs_path = Path(self._store.base_dir) / fp
            if abs_path.exists():
                mtime = abs_path.stat().st_mtime
                age = time.time() - mtime
                if age < 300:  # 5 minutes
                    results[fp] = "fresh"
                elif age < 3600:
                    results[fp] = "pending"
                else:
                    results[fp] = "stale"
            else:
                results[fp] = "unknown"
        return results

    def banner(self) -> dict[str, Any]:
        """Generate a freshness banner for MCP responses."""
        status = self.check()
        result = {
            "freshness": status.to_dict(),
            "banner": f"[{status.status.upper()}] {status.message}" if status.message else None,
        }
        try:
            workspace_shape = analyze_workspace_shape(load_workspace_config(self._workspace_file))
        except Exception:
            workspace_shape = {}

        warnings = workspace_shape.get("warnings", []) if isinstance(workspace_shape, dict) else []
        if warnings:
            result["workspace_shape"] = {
                "service_count": workspace_shape.get("service_count", 0),
                "unique_root_count": workspace_shape.get("unique_root_count", 0),
                "duplicate_root_group_count": workspace_shape.get("duplicate_root_group_count", 0),
                "nested_service_pair_count": workspace_shape.get("nested_service_pair_count", 0),
                "risk_level": workspace_shape.get("risk_level", "low"),
            }
            result["workspace_warnings"] = warnings
            shape_notice = f"workspace 配置存在 {len(warnings)} 个结构风险"
            if result["banner"]:
                result["banner"] = f'{result["banner"]}；{shape_notice}'
            else:
                result["banner"] = shape_notice
        return result
