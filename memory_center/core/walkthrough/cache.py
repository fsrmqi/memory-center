from __future__ import annotations

import copy
import time
from typing import Any


class WalkthroughCache:
    """Small in-process cache for repeated walkthrough reads.

    The interface is intentionally tiny so the implementation can later move to
    SQLite or a file-backed cache without changing orchestrator callers.
    """

    def __init__(self, ttl_seconds: int = 15, max_items: int = 64):
        self.ttl_seconds = ttl_seconds
        self.max_items = max_items
        self._items: dict[str, tuple[float, dict[str, Any]]] = {}

    def get(self, key: str) -> dict[str, Any] | None:
        row = self._items.get(key)
        if not row:
            return None
        created_at, payload = row
        if time.time() - created_at > self.ttl_seconds:
            self._items.pop(key, None)
            return None
        result = copy.deepcopy(payload)
        result["cache"] = {"hit": True, "ttl_seconds": self.ttl_seconds}
        return result

    def put(self, key: str, payload: dict[str, Any]) -> None:
        saved = copy.deepcopy(payload)
        saved["cache"] = {"hit": False, "ttl_seconds": self.ttl_seconds}
        if len(self._items) >= self.max_items:
            oldest = min(self._items.items(), key=lambda item: item[1][0])[0]
            self._items.pop(oldest, None)
        self._items[key] = (time.time(), saved)

    def stats(self) -> dict[str, Any]:
        return {
            "size": len(self._items),
            "ttl_seconds": self.ttl_seconds,
            "max_items": self.max_items,
        }
