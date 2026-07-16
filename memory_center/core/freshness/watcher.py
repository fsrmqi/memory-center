"""File watcher — monitor source files for changes with debounced auto-sync.

Provides file-system-level change detection so the index can be kept fresh
without manual reindex triggers.  Uses mtime-based polling (no inotify/kqueue
dependency) with configurable debounce.
"""
from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class FileSnapshot:
    """Snapshot of a file's state."""
    path: str
    mtime: float
    size: int
    hash: str = ""


@dataclass
class WatchEvent:
    """A detected file change event."""
    path: str
    change_type: str  # added | modified | deleted
    detected_at: float = 0.0

    def __post_init__(self) -> None:
        if self.detected_at == 0.0:
            self.detected_at = time.time()


class FileWatcher:
    """Watch source files for changes using mtime polling.

    Debounces changes so rapid sequences of edits only trigger one reindex.
    """

    def __init__(
        self,
        root: str | Path,
        extensions: tuple[str, ...] = (".java", ".yml", ".yaml", ".properties"),
        debounce_seconds: float = 2.0,
        poll_interval: float = 5.0,
        ignore_dirs: tuple[str, ...] = (".git", "target", "build", "node_modules", "__pycache__"),
    ):
        self._root = Path(root)
        self._extensions = extensions
        self._debounce_seconds = debounce_seconds
        self._poll_interval = poll_interval
        self._ignore_dirs = set(ignore_dirs)

        self._snapshots: dict[str, FileSnapshot] = {}
        self._pending_events: list[WatchEvent] = []
        self._callbacks: list[Callable[[list[WatchEvent]], None]] = []
        self._running = False
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def take_snapshot(self) -> dict[str, FileSnapshot]:
        """Take a snapshot of all watched files."""
        snapshots: dict[str, FileSnapshot] = {}

        for dirpath, dirnames, filenames in os.walk(self._root):
            dirnames[:] = [d for d in dirnames if d not in self._ignore_dirs]

            for filename in filenames:
                filepath = Path(dirpath) / filename
                if filepath.suffix not in self._extensions:
                    continue

                try:
                    stat = filepath.stat()
                    rel_path = str(filepath.relative_to(self._root))
                    snapshots[rel_path] = FileSnapshot(
                        path=rel_path,
                        mtime=stat.st_mtime,
                        size=stat.st_size,
                    )
                except OSError:
                    continue

        return snapshots

    def detect_changes(self) -> list[WatchEvent]:
        """Detect changes by comparing current state to last snapshot."""
        current = self.take_snapshot()
        events: list[WatchEvent] = []

        # Check for modified and deleted files
        for path, old_snap in self._snapshots.items():
            if path not in current:
                events.append(WatchEvent(path=path, change_type="deleted"))
            elif current[path].mtime > old_snap.mtime or current[path].size != old_snap.size:
                events.append(WatchEvent(path=path, change_type="modified"))

        # Check for added files
        for path in current:
            if path not in self._snapshots:
                events.append(WatchEvent(path=path, change_type="added"))

        # Update snapshot
        self._snapshots = current

        return events

    def on_change(self, callback: Callable[[list[WatchEvent]], None]) -> None:
        """Register a callback for file changes."""
        self._callbacks.append(callback)

    def start(self) -> None:
        """Start watching for changes in a background thread."""
        if self._running:
            return

        # Take initial snapshot
        self._snapshots = self.take_snapshot()
        self._running = True

        def _watch_loop() -> None:
            while self._running:
                time.sleep(self._poll_interval)
                if not self._running:
                    break

                events = self.detect_changes()
                if events:
                    with self._lock:
                        self._pending_events.extend(events)

                    # Debounce: wait for quiet period
                    time.sleep(self._debounce_seconds)

                    with self._lock:
                        pending = self._pending_events.copy()
                        self._pending_events.clear()

                    if pending:
                        for callback in self._callbacks:
                            try:
                                callback(pending)
                            except Exception:
                                pass

        self._thread = threading.Thread(target=_watch_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop watching."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=self._poll_interval + self._debounce_seconds + 1)
            self._thread = None

    def status(self) -> dict[str, Any]:
        """Return watcher status."""
        return {
            "running": self._running,
            "root": str(self._root),
            "tracked_files": len(self._snapshots),
            "pending_events": len(self._pending_events),
            "poll_interval": self._poll_interval,
            "debounce_seconds": self._debounce_seconds,
        }


def trigger_incremental_reindex(workspace_file: str | Path, changed_files: list[str]) -> dict[str, Any]:
    """Bridge watcher events to incremental reindex.

    Takes changed file paths from FileWatcher and triggers
    a targeted reindex for only those files.
    """
    from ..jobs import submit_reindex_workspace_job
    from .targeted_refresh import record_dirty_files

    try:
        result = record_dirty_files(workspace_file, changed_files, source="watcher")
        invalidation = result.get("invalidation", {}) or {}
        job = submit_reindex_workspace_job(
            str(workspace_file),
            paths=list(invalidation.get("impacted_paths", []) or changed_files)[:48],
        )
        return {
            "status": "queued",
            "changed_files": len(changed_files),
            "dirty_journal": result,
            "reindex_job": job,
        }
    except Exception as exc:
        return {
            "status": "error",
            "error": str(exc),
            "changed_files": len(changed_files),
        }
