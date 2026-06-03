"""Incremental diff indexing — git diff based incremental reindex.

Uses git diff to detect changed files and only re-parses them,
instead of re-indexing the entire workspace.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from ..storage.unified import UnifiedStore


@dataclass
class ChangedFile:
    """A file that changed according to git."""
    path: str
    status: str  # A=added, M=modified, D=deleted, R=renamed


def git_changed_files(repo_root: str | Path, since: str = "HEAD") -> List[ChangedFile]:
    """Get files changed since a git ref using git diff --name-status."""
    repo_root = Path(repo_root)
    if not (repo_root / ".git").exists():
        return []

    try:
        result = subprocess.run(
            ["git", "diff", "--name-status", since],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return []
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []

    changed = []
    for line in result.stdout.strip().splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            status = parts[0][0]  # First char: A, M, D, R
            path = parts[-1]
            changed.append(ChangedFile(path=path, status=status))

    return changed


def git_changed_files_unstaged(repo_root: str | Path) -> List[ChangedFile]:
    """Get unstaged changes (working tree vs index)."""
    repo_root = Path(repo_root)
    if not (repo_root / ".git").exists():
        return []

    try:
        result = subprocess.run(
            ["git", "diff", "--name-status"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return []
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []

    changed = []
    for line in result.stdout.strip().splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            status = parts[0][0]
            path = parts[-1]
            changed.append(ChangedFile(path=path, status=status))

    return changed


class IncrementalIndexer:
    """Perform incremental reindex based on git diff."""

    def __init__(self, store: UnifiedStore, repo_root: str | Path):
        self._store = store
        self._repo_root = Path(repo_root)

    def detect_changes(self, since: str = "HEAD") -> Dict[str, List[ChangedFile]]:
        """Detect changed files and categorize them."""
        changes = git_changed_files(self._repo_root, since)

        result: Dict[str, List[ChangedFile]] = {
            "added": [],
            "modified": [],
            "deleted": [],
            "renamed": [],
        }

        for change in changes:
            if change.status == "A":
                result["added"].append(change)
            elif change.status == "M":
                result["modified"].append(change)
            elif change.status == "D":
                result["deleted"].append(change)
            elif change.status == "R":
                result["renamed"].append(change)

        return result

    def remove_by_file_path(self, file_path: str) -> Set[str]:
        """Remove all nodes associated with a file path. Returns removed node IDs."""
        with self._store.pool.transaction() as conn:
            rows = conn.execute(
                "SELECT id FROM nodes WHERE file_path=?", (file_path,)
            ).fetchall()
            if not rows:
                return set()

            removed_ids = {str(r["id"]) for r in rows}
            placeholders = ",".join("?" for _ in removed_ids)
            id_list = list(removed_ids)

            conn.execute(
                f"DELETE FROM edges WHERE source_id IN ({placeholders}) OR target_id IN ({placeholders})",
                id_list * 2,
            )
            conn.execute(f"DELETE FROM nodes WHERE id IN ({placeholders})", id_list)
            try:
                conn.execute(f"DELETE FROM node_search WHERE id IN ({placeholders})", id_list)
            except Exception:
                pass

        return removed_ids

    def incremental_reindex(
        self,
        parse_fn: Any,
        since: str = "HEAD",
    ) -> Dict[str, Any]:
        """Perform incremental reindex for changed files only.

        Args:
            parse_fn: Function that takes (service, path) and returns parsed results
            since: Git ref to diff against

        Returns:
            Summary of changes: added, modified, deleted counts and affected node IDs
        """
        changes = self.detect_changes(since)

        # Handle deletions
        deleted_node_ids: Set[str] = set()
        for change in changes["deleted"]:
            deleted_node_ids.update(self.remove_by_file_path(change.path))

        # Handle additions and modifications (would need to re-parse)
        added_modified = changes["added"] + changes["modified"]
        affected_paths = [c.path for c in added_modified]

        return {
            "mode": "incremental",
            "deleted_count": len(changes["deleted"]),
            "deleted_node_ids": list(deleted_node_ids),
            "added_count": len(changes["added"]),
            "modified_count": len(changes["modified"]),
            "affected_paths": affected_paths,
            "needs_reparse": len(added_modified) > 0,
        }
