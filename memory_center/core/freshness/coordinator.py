"""Cross-agent coordination for bounded query-time refreshes."""
from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from filelock import FileLock, Timeout

_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


class RefreshCoordinator:
    """Serialize a workspace refresh across threads and local processes.

    The lock is deliberately short lived: it protects only graph/manifest
    replacement, not the caller's broader analysis. A competing request waits
    briefly for the newest generation and then reports that it coalesced.
    """

    def __init__(self, workspace_dir: Path):
        self._key = str(workspace_dir.resolve())
        self._file_lock = FileLock(str(workspace_dir / "hot-refresh.lock"))
        with _LOCKS_GUARD:
            self._thread_lock = _LOCKS.setdefault(self._key, threading.Lock())

    def run(self, action: Callable[[], dict[str, Any]], fallback: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        if not self._thread_lock.acquire(timeout=1.0):
            result = fallback()
            result["coalesced"] = True
            return result
        try:
            try:
                with self._file_lock.acquire(timeout=2.0):
                    return action()
            except Timeout:
                result = fallback()
                result["coalesced"] = True
                return result
        finally:
            self._thread_lock.release()
