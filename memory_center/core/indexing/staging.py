"""Generation-local index staging (task: Generation-local staging + publish-only merge).

The index pipeline currently writes merged intermediate artifacts
(``file-index.json``, ``java-symbol-index.json``, …) straight into the
canonical ``index_mirror`` during ``_reindex_workspace_unlocked``. Under
the Phase C admission rules, non-overlapping projects may *parse and build*
in parallel, but the canonical writes serialize on a shared namespace — a
slow or failed project leaves its half-merged slice visible, and two
parallel refreshes can clobber each other's rows.

This module gives every reindex run its own **staging namespace**:

- ``IndexStaging`` wraps the workspace store so reads prefer staging data
  and writes land only in the staging overlay, never the canonical
  ``index_mirror``.
- ``publish()`` takes the staged payloads and commits them into the
  canonical ``index_mirror`` inside a single ``BEGIN IMMEDIATE``
  transaction (reusing ``WorkspaceStore.publish_generation_payloads``), so
  the pointer flip and every intermediate artifact are atomic. A failed or
  cancelled run simply discards its staging overlay; the previous active
  generation is untouched.

The overlay is in-memory (bounded to the already-bounded intermediate
indexes), so no extra filesystem or SQLite table is needed.
"""
from __future__ import annotations

import copy
import threading
from pathlib import Path
from typing import Any

# Intermediate artifacts that must be generation-local during a run and
# published together at the end. Excludes files that are genuinely global
# (graph-summary, coverage ledger, control plane).
STAGED_INDEXES = frozenset(
    {
        "file-index.json",
        "java-symbol-index.json",
        "api-index.json",
        "feign-index.json",
        "mq-index.json",
        "config-index.json",
        "service-topology.json",
        "contract-snapshot.json",
        "contract-diff.json",
    }
)


class IndexStaging:
    """Staging-first read/write facade over a WorkspaceStore.

    Writes of the large merged indexes go into an in-memory overlay instead
    of the canonical ``index_mirror``. Reads return the staged value when
    present, otherwise fall through to the canonical backend. Nothing is
    visible to readers until ``publish()`` commits the overlay atomically.
    """

    def __init__(self, store) -> None:
        self._store = store
        self._overlay: dict[str, Any] = {}
        self._lock = threading.Lock()

    # -- reads ---------------------------------------------------------

    def read_json_prefer_backend(self, name: str, default: Any) -> Any:
        if name in STAGED_INDEXES:
            with self._lock:
                if name in self._overlay:
                    return copy.deepcopy(self._overlay[name])
            # Fall through to canonical for anything not staged yet.
        return self._store.read_json_prefer_backend(name, default)

    def read_json(self, name: str, default: Any) -> Any:
        return self.read_json_prefer_backend(name, default)

    # -- writes --------------------------------------------------------

    def write_json(self, name: str, data: Any) -> None:
        if name in STAGED_INDEXES:
            with self._lock:
                self._overlay[name] = copy.deepcopy(data)
            return
        # Non-staged artifacts (graph-summary, index-resolution, …) still
        # write through to canonical — they are per-run diagnostics, not
        # shard inputs, and their staleness is already covered by the
        # generation pointer.
        self._store.write_json(name, data)

    # -- publish -------------------------------------------------------

    def publish(self, *, publication: dict[str, str] | None = None) -> None:
        """Atomically commit all staged intermediates into the canonical store."""
        with self._lock:
            payloads = [(name, copy.deepcopy(value)) for name, value in sorted(self._overlay.items())]
        if payloads:
            self._store.publish_generation_payloads(payloads, publication=publication)
        # Diagnostics written through during the run stay as-is; staged
        # overlays are cleared after commit (they are no longer authoritative).
        with self._lock:
            self._overlay.clear()

    # -- introspection -------------------------------------------------

    def staged_names(self) -> list[str]:
        with self._lock:
            return sorted(self._overlay.keys())

    @property
    def store(self):
        return self._store

    def __getattr__(self, item: str) -> Any:
        # Delegate any other attribute (graph_db_path, memory_backend, …)
        # to the underlying workspace store so this can stand in for it.
        return getattr(self._store, item)


def with_staging(store) -> IndexStaging:
    """Wrap a store for the duration of one reindex run."""
    return IndexStaging(store)
