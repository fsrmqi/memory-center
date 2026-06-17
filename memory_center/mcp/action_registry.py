from __future__ import annotations

from collections.abc import Callable
from typing import Any, Dict


class ActionRegistry:
    """Small registry seam for MCP admin-style dispatch."""

    def __init__(self) -> None:
        self._handlers: Dict[str, Callable[[], Any]] = {}

    def register_many(self, handlers: Dict[str, Callable[[], Any]]) -> "ActionRegistry":
        self._handlers.update(handlers)
        return self

    def dispatch(self, action: str) -> Any:
        handler = self._handlers.get(action)
        if handler is None:
            valid = ", ".join(sorted(self._handlers.keys()))
            raise ValueError(f"Unknown mc_admin action: {action}. Valid actions: {valid}")
        return handler()
