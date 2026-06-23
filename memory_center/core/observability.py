from __future__ import annotations

import functools
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .metrics import MetricsCollector
from .store import WorkspaceStore

OPERATION_EVENTS_FILE = "operation-events.jsonl"


def _safe_tags(tags: dict[str, Any] | None) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in (tags or {}).items():
        normalized = str(key).lower()
        if any(token in normalized for token in ("path", "file", "workspace", "secret", "token", "key")):
            safe[str(key)] = "[redacted]"
        elif isinstance(value, (str, int, float, bool)) or value is None:
            text = str(value)
            safe[str(key)] = "[redacted]" if isinstance(value, str) and ("/" in text or "\\" in text) else value
    return safe


class OperationObserver:
    def __init__(self, workspace_file: str | Path, operation: str, *, tags: dict[str, Any] | None = None):
        self.workspace_file = Path(workspace_file)
        self.operation = operation
        self.tags = _safe_tags(tags)
        self.result_count = 0
        self._started = 0.0

    def __enter__(self) -> OperationObserver:
        self._started = time.monotonic()
        return self

    def set_result_count(self, count: int) -> None:
        self.result_count = max(0, int(count or 0))

    def __exit__(self, exc_type, exc, traceback) -> bool:
        duration_ms = round((time.monotonic() - self._started) * 1000, 3)
        event = {
            "operation": self.operation,
            "outcome": "error" if exc_type else "success",
            "error_type": exc_type.__name__ if exc_type else "",
            "duration_ms": duration_ms,
            "result_count": self.result_count,
            "tags": self.tags,
        }
        try:
            WorkspaceStore(self.workspace_file).append_jsonl(OPERATION_EVENTS_FILE, event)
            metrics = MetricsCollector(self.workspace_file)
            metrics.record(f"{self.operation}.duration", duration_ms, unit="ms", tags={"outcome": event["outcome"]})
            metrics.record(f"{self.operation}.result_count", self.result_count, unit="count", tags={"outcome": event["outcome"]})
        except Exception:
            pass
        return False


def _result_count(result: Any) -> int:
    if isinstance(result, dict):
        for key in ("returned", "files", "count", "total_found", "graph_nodes"):
            value = result.get(key)
            if isinstance(value, int):
                return value
        for key in ("results", "matches", "items"):
            value = result.get(key)
            if isinstance(value, list):
                return len(value)
    if isinstance(result, (list, tuple, set)):
        return len(result)
    return 0


def observe_operation(
    operation: str,
    *,
    workspace_resolver: Callable[[tuple[Any, ...], dict[str, Any]], str | Path],
    tags_resolver: Callable[[tuple[Any, ...], dict[str, Any]], dict[str, Any]] | None = None,
):
    def decorator(function):
        @functools.wraps(function)
        def wrapped(*args, **kwargs):
            workspace = workspace_resolver(args, kwargs)
            tags = tags_resolver(args, kwargs) if tags_resolver else {}
            with OperationObserver(workspace, operation, tags=tags) as observer:
                result = function(*args, **kwargs)
                observer.set_result_count(_result_count(result))
                return result
        return wrapped
    return decorator
