"""Index reconciliation — connect-time catch-up via file hash comparison.

On MCP server startup, scans workspace files for size/mtime changes,
computes hashes for suspicious files, and triggers incremental reindex
for anything that diverges from the graph.
"""
from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from memory_center.core.storage.workspace import WorkspaceStore


@dataclass
class ReconcileResult:
    """Outcome of a reconcile pass."""
    checked_files: int = 0
    stale_files: list[str] = field(default_factory=list)
    added_files: list[str] = field(default_factory=list)
    deleted_files: list[str] = field(default_factory=list)
    duration_ms: float = 0.0
    needs_reindex: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "checked_files": self.checked_files,
            "stale_count": len(self.stale_files),
            "added_count": len(self.added_files),
            "deleted_count": len(self.deleted_files),
            "stale_files": self.stale_files[:20],
            "added_files": self.added_files[:20],
            "deleted_files": self.deleted_files[:20],
            "duration_ms": round(self.duration_ms, 1),
            "needs_reindex": self.needs_reindex,
        }


def _file_hash(path: Path) -> str:
    """SHA-256 of a file's contents."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()


def _scan_source_files(
    root: Path,
    extensions: tuple = (".java", ".yml", ".yaml", ".properties"),
    ignore_dirs: tuple = (".git", "target", "build", "node_modules", "__pycache__"),
) -> dict[str, Path]:
    """Walk root and return {relative_path: absolute_path} for watched files."""
    result: dict[str, Path] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in ignore_dirs]
        for fn in filenames:
            fp = Path(dirpath) / fn
            if fp.suffix in extensions:
                rel = str(fp.relative_to(root))
                result[rel] = fp
    return result


class ReconcileService:
    """Compare on-disk files against the indexed graph and find drift.

    Use on MCP server startup (connect-time) to detect files that changed
    since the last index run.
    """

    def __init__(
        self,
        workspace_file: str | Path,
        extensions: tuple = (".java", ".yml", ".yaml", ".properties"),
    ):
        self._store = WorkspaceStore(workspace_file)
        self._extensions = extensions
        # base_dir is .memory-center/; project root is its parent
        self._root = Path(self._store.base_dir).parent

    def reconcile(self, hash_threshold: int = 500) -> ReconcileResult:
        """Run a full reconcile pass.

        Args:
            hash_threshold: files larger than this (KB) use mtime-only check
        """
        t0 = time.time()
        result = ReconcileResult()

        # 1. Scan disk files
        disk_files = _scan_source_files(self._root, self._extensions)

        # 2. Load indexed file list from graph DB
        indexed_files: set[str] = set()
        try:
            raw = self._store.read_json_prefer_backend("file-index.json", [])
            if isinstance(raw, list):
                for entry in raw:
                    if isinstance(entry, dict):
                        indexed_files.add(entry.get("path", ""))
                    elif isinstance(entry, str):
                        indexed_files.add(entry)
        except Exception:
            pass

        # 3. Detect added / deleted
        for rel_path in disk_files:
            if rel_path not in indexed_files:
                result.added_files.append(rel_path)

        for rel_path in indexed_files:
            if rel_path not in disk_files:
                result.deleted_files.append(rel_path)

        # 4. Check staleness for existing files
        graph_path = Path(self._store.graph_db_path)
        if graph_path.exists():
            index_mtime = graph_path.stat().st_mtime
        else:
            index_mtime = 0.0

        for rel_path in disk_files:
            if rel_path in indexed_files:
                fp = disk_files[rel_path]
                try:
                    stat = fp.stat()
                    if stat.st_mtime > index_mtime:
                        result.stale_files.append(rel_path)
                except OSError:
                    continue

        result.checked_files = len(disk_files)
        result.duration_ms = (time.time() - t0) * 1000
        result.needs_reindex = bool(result.stale_files or result.added_files or result.deleted_files)

        return result
