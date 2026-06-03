"""IndexFreshnessService — track whether the graph index is up-to-date.

Provides freshness status so MCP responses can warn agents when the
index may be stale and they should read live files before editing.
"""
from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..store import WorkspaceStore


@dataclass
class FreshnessStatus:
    """Freshness state for a workspace."""
    status: str = "unknown"  # fresh | pending | stale | unknown
    last_indexed_at: str = ""
    changed_files: List[str] = field(default_factory=list)
    pending_files: List[str] = field(default_factory=list)
    staleness_level: str = "unknown"  # low | medium | high | unknown
    message: str = ""

    def to_dict(self) -> Dict[str, Any]:
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
            graph_summary = self._store.read_json_prefer_backend("graph-summary.json", {})
            index_counts = self._store.read_json_prefer_backend("file-index.json", [])
        except Exception:
            return FreshnessStatus(status="unknown", message="无法读取索引元数据")

        if not index_counts:
            return FreshnessStatus(status="stale", staleness_level="high", message="索引为空，需要先运行 reindex")

        # Check graph-summary mtime as proxy for last index time
        graph_path = Path(self._store.graph_db_path)
        if graph_path.exists():
            mtime = graph_path.stat().st_mtime
            age = time.time() - mtime
            if age < threshold_seconds:
                return FreshnessStatus(
                    status="fresh",
                    staleness_level="low",
                    last_indexed_at=time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(mtime)),
                    message=f"索引新鲜（{int(age)}秒前更新）",
                )
            elif age < threshold_seconds * 4:
                return FreshnessStatus(
                    status="pending",
                    staleness_level="medium",
                    last_indexed_at=time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(mtime)),
                    message=f"索引可能过期（{int(age)}秒前更新），建议对关键文件 Read 实时内容",
                )
            else:
                return FreshnessStatus(
                    status="stale",
                    staleness_level="high",
                    last_indexed_at=time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(mtime)),
                    message=f"索引较旧（{int(age)}秒前更新），建议先运行 reindex",
                )

        return FreshnessStatus(status="unknown", message="无法检测索引文件")

    def check_files(self, file_paths: List[str]) -> Dict[str, str]:
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

    def banner(self) -> Dict[str, Any]:
        """Generate a freshness banner for MCP responses."""
        status = self.check()
        return {
            "freshness": status.to_dict(),
            "banner": f"[{status.status.upper()}] {status.message}" if status.message else None,
        }
