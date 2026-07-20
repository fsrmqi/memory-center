"""Shared JSON serialization helpers for SQLite-backed stores.

Memory Center writes graph metadata as a JSON string in many hot paths
(``RuntimeStore.rebuild``, ``RuntimeStore.bulk_write``,
``RuntimeStore.partial_rebuild``, ``RuntimeStore._upsert_search_rows``,
``retrieval/inverted.py``, ``semantic.py``). On real UCAP workspaces
``json.dumps`` is called ~4.6M times during one reindex; ``{}`` itself is
by far the most common payload (most nodes carry no extra metadata).

``metadata_json`` exists so every hot path serializes metadata the same way
and so the empty-dict fast path is centralized. Callers should not embed
a literal ``json.dumps(node.metadata or {}, ...)`` anymore.
"""
from __future__ import annotations

import json
from typing import Any

_EMPTY_JSON = "{}"


def metadata_json(metadata: dict[str, Any] | None) -> str:
    """Serialize a metadata dict to JSON, fast-pathing empty / ``None`` cases.

    The output is byte-equivalent to
    ``json.dumps(metadata or {}, ensure_ascii=False)`` for both empty and
    non-empty inputs; the fast path only skips constructing a fresh JSON
    encoder instance for the empty case.
    """
    if not metadata:
        return _EMPTY_JSON
    return json.dumps(metadata, ensure_ascii=False)


__all__ = ["metadata_json"]
