"""Incremental diff indexing — git diff based incremental reindex.

Uses git diff to detect changed files and only re-parses them,
instead of re-indexing the entire workspace.
"""
from __future__ import annotations

import fnmatch
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Set

from ..storage.unified import UnifiedStore


@dataclass
class ChangedFile:
    """A file that changed according to git."""
    path: str
    status: str  # A=added, M=modified, D=deleted, R=renamed
    previous_path: str = ""


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
            previous_path = parts[-2] if status == "R" and len(parts) >= 3 else ""
            changed.append(ChangedFile(path=path, status=status, previous_path=previous_path))

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
            previous_path = parts[-2] if status == "R" and len(parts) >= 3 else ""
            changed.append(ChangedFile(path=path, status=status, previous_path=previous_path))

    return changed


class IncrementalIndexer:
    """Perform incremental reindex based on git diff."""

    def __init__(
        self,
        store: UnifiedStore,
        repo_root: str | Path,
        workspace_file: str | Path | None = None,
    ):
        self._store = store
        self._repo_root = Path(repo_root)
        self._workspace_file = self._resolve_workspace_file(workspace_file)

    def _resolve_workspace_file(self, workspace_file: str | Path | None) -> Path | None:
        if workspace_file:
            return Path(workspace_file).expanduser().resolve()

        candidates = [
            self._repo_root / ".memory-center" / "workspace.yaml",
            self._store.db_path.parent.parent / "workspace.yaml",
        ]
        return next((candidate.resolve() for candidate in candidates if candidate.exists()), None)

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
        for change in changes["renamed"]:
            if change.previous_path:
                deleted_node_ids.update(self.remove_by_file_path(change.previous_path))

        # Reconcile every changed scope. Deleted/old rename paths produce no
        # refreshed rows, which intentionally removes stale deterministic data.
        reparse_changes = changes["added"] + changes["modified"] + changes["renamed"]
        affected_paths = [c.path for c in reparse_changes]
        affected_paths.extend(c.path for c in changes["deleted"])
        affected_paths.extend(c.previous_path for c in changes["renamed"] if c.previous_path)
        affected_paths = list(dict.fromkeys(path for path in affected_paths if path))

        # Actually re-parse added/modified files using reindex_workspace
        reindex_result: Dict[str, Any] = {}
        reindex_error = ""
        if affected_paths:
            try:
                from ..store import WorkspaceStore
                from ..config import load_workspace_config
                from ..indexer import reindex_workspace

                if self._workspace_file:
                    config = load_workspace_config(self._workspace_file)
                    store = WorkspaceStore(self._workspace_file)
                    reindex_result = reindex_workspace(config, store, paths=affected_paths)
                else:
                    reindex_error = "workspace_file_not_found"
            except Exception as exc:
                reindex_error = str(exc)[:200]

        return {
            "mode": "incremental",
            "deleted_count": len(changes["deleted"]),
            "deleted_node_ids": list(deleted_node_ids),
            "added_count": len(changes["added"]),
            "modified_count": len(changes["modified"]),
            "affected_paths": affected_paths,
            "renamed_count": len(changes["renamed"]),
            "needs_reparse": len(reparse_changes) > 0,
            "reindexed": bool(reindex_result),
            "reindex_result": reindex_result,
            "reindex_error": reindex_error,
        }


# --- H-05: Structured Diff Scope ---
# Deterministic diff scope with binary detection, exclusion rules, and preview.

_BINARY_EXTENSIONS = frozenset({
    '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico', '.svg',
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
    '.zip', '.tar', '.gz', '.rar', '.7z', '.bz2', '.xz',
    '.exe', '.dll', '.so', '.dylib', '.bin',
    '.pyc', '.pyo', '.class', '.jar', '.war',
    '.mp3', '.mp4', '.avi', '.mov', '.wav', '.flac',
    '.ttf', '.otf', '.woff', '.woff2',
    '.sqlite', '.db', '.db-shm', '.db-wal',
})

_EXCLUDED_PATTERNS: List[tuple] = [
    ("__pycache__", "Python bytecode cache"),
    ("node_modules", "npm dependencies"),
    (".git", "Git internals"),
    ("target/", "Java/Maven build output"),
    ("/build/", "Gradle build output"),
    ("/dist/", "Distribution output"),
    (".idea", "JetBrains IDE config"),
    (".vscode", "VS Code IDE config"),
    ("*.pyc", "Compiled Python bytecode"),
    ("*.pyo", "Optimized Python bytecode"),
    ("*.class", "Compiled Java bytecode"),
    ("*.jar", "Java archive"),
    ("*.war", "Java web archive"),
    ("package-lock.json", "npm lockfile"),
    ("yarn.lock", "yarn lockfile"),
    ("Pipfile.lock", "pipenv lockfile"),
    ("poetry.lock", "poetry lockfile"),
    (".memory-center/", "Memory Center internal data"),
]


@dataclass
class DiffScope:
    """Structured diff scope for deterministic change detection.

    Attributes:
        scope_type: workspace | commit | branch_range | unstaged
        included: Files that should enter review/verification
        excluded: Files excluded with reasons
        excluded_reasons: Map from file path to exclusion reason
        binary_files: Binary files detected
        total_files: Total changed files before filtering
    """
    scope_type: str
    included: List[ChangedFile]
    excluded: List[ChangedFile]
    excluded_reasons: Dict[str, str]
    binary_files: List[str]
    total_files: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scope_type": self.scope_type,
            "total_files": self.total_files,
            "included_count": len(self.included),
            "excluded_count": len(self.excluded),
            "binary_count": len(self.binary_files),
            "included": [{"path": c.path, "status": c.status} for c in self.included],
            "excluded": [{"path": c.path, "status": c.status} for c in self.excluded],
            "excluded_reasons": self.excluded_reasons,
            "binary_files": self.binary_files,
        }


def detect_diff_scope(
    repo_root: str | Path,
    scope_type: str = "workspace",
    since: str = "HEAD",
) -> DiffScope:
    """Detect diff scope with deterministic inclusion/exclusion rules.

    Args:
        repo_root: Root of the git repository
        scope_type: workspace | commit | branch_range | unstaged
        since: Git ref to diff against (for commit/branch_range)

    Returns:
        DiffScope with included/excluded files and reasons
    """
    if scope_type == "unstaged":
        changes = git_changed_files_unstaged(repo_root)
    else:
        changes = git_changed_files(repo_root, since)

    included: List[ChangedFile] = []
    excluded: List[ChangedFile] = []
    excluded_reasons: Dict[str, str] = {}
    binary_files: List[str] = []

    for change in changes:
        path = change.path
        ext = Path(path).suffix.lower()

        # Check binary
        if ext in _BINARY_EXTENSIONS:
            binary_files.append(path)
            excluded.append(change)
            excluded_reasons[path] = f"Binary file ({ext})"
            continue

        # Check excluded patterns
        is_excluded = False
        for pattern, reason in _EXCLUDED_PATTERNS:
            if '*' in pattern:
                if fnmatch.fnmatch(path, pattern):
                    excluded.append(change)
                    excluded_reasons[path] = reason
                    is_excluded = True
                    break
            elif pattern in path or pattern.rstrip('/') in path:
                excluded.append(change)
                excluded_reasons[path] = reason
                is_excluded = True
                break

        if not is_excluded:
            included.append(change)

    return DiffScope(
        scope_type=scope_type,
        included=included,
        excluded=excluded,
        excluded_reasons=excluded_reasons,
        binary_files=binary_files,
        total_files=len(changes),
    )


def preview_diff_scope(
    repo_root: str | Path,
    scope_type: str = "workspace",
    since: str = "HEAD",
) -> Dict[str, Any]:
    """Preview diff scope without executing Agent.

    Returns structured preview with inclusion/exclusion details,
    suitable for dry-run inspection before code review or verification.
    """
    scope = detect_diff_scope(repo_root, scope_type, since)
    return scope.to_dict()
