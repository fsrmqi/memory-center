"""cProfile-based performance profiler for reindex_workspace.

P1-0 baseline tool. The P0 UCAP benchmark showed that ~71% of reindex
wall-clock on Java-heavy monorepos lives outside SQLite write — in
the Java parsing + IO + Python assembly pipeline. To know which sub-
layer to attack next, we need a real-flame profile, not more guesses.

This module wraps :func:`memory_center.core.indexer.reindex_workspace`
in :mod:`cProfile` and emits both the raw ``pstats`` file (for
``snakeviz`` / ``pyprof2calltree``) and a human-readable top-N
summary (so ``memory-center bench-profile`` prints something useful
without extra tooling).

Design notes:

- We profile the entire reindex call, not individual phases. cProfile
  already records per-function timings; downstream pstats can slice
  by callee/caller/cumulative time without us having to instrument
  individual phases.
- The output ``.prof`` filename includes the workspace name + ISO
  timestamp so repeated profiling runs don't clobber each other.
- ``top_n`` defaults to 50 — enough to see every meaningful frame in
  one screen without drowning the terminal in vendor code.
- Cleanup of pre-existing indexes (so each profile run starts cold)
  is delegated to the caller, matching the bench_p0_ucap.py contract.
  That keeps this module unopinionated about hot-vs-cold semantics.

Not a replacement for the bench_p0_ucap.py wall-clock benchmark —
they answer different questions:
- bench_p0_ucap.py: "did P0 change end-to-end reindex time?"
- this module:     "where inside reindex is the time actually spent?"
"""
from __future__ import annotations

import cProfile
import io
import pstats
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ProfileResult:
    """Outcome of one profiling run."""

    pstats_path: Path
    elapsed_s: float
    total_calls: int
    primitive_calls: int
    # Human-readable top-N table as a single string, ready to print or
    # write to disk. Includes a header row and right-aligned columns.
    top_summary: str
    # ``reindex_workspace`` return value, in case the caller wants to
    # cross-check node/edge counts without rerunning anything.
    reindex_result: Any = None
    extra: dict[str, Any] = field(default_factory=dict)


def profile_reindex(
    workspace_file: Path,
    out_dir: Path | None = None,
    *,
    top_n: int = 50,
    sort_by: str = "cumulative",
    label: str = "",
) -> ProfileResult:
    """Run reindex_workspace under cProfile and write a pstats dump.

    Parameters
    ----------
    workspace_file
        Path to the ``.memory-center/workspace.yaml`` to reindex.
    out_dir
        Directory to write the ``.prof`` file into. Defaults to
        ``$workspace/.memory-center/perf-profiles/`` so artefacts stay
        next to the workspace they describe.
    top_n
        How many functions to include in the human-readable summary.
    sort_by
        ``pstats`` sort key. ``cumulative`` is the right default for
        finding "what's expensive across the whole call tree";
        ``tottime`` is better for "what's expensive in this function
        alone". The caller can override per run.
    label
        Free-form tag appended to the output filename. Useful for
        labelling "baseline" vs "after-X" profiles when comparing.
    """
    # Imports inside the function so importing this module is free
    # when no profiling is happening.
    import time

    from memory_center.core.config import load_workspace_config
    from memory_center.core.indexer import reindex_workspace
    from memory_center.core.store import WorkspaceStore

    config = load_workspace_config(str(workspace_file))
    store = WorkspaceStore(workspace_file)

    workspace_name = config.workspace or workspace_file.parent.name
    out_dir = out_dir or (workspace_file.parent / "perf-profiles")
    out_dir.mkdir(parents=True, exist_ok=True)

    # Filename: workspace + label + a deterministic-ish suffix so
    # repeated calls in one session land on different files. Using
    # ``time.time_ns`` avoids the ``Date.now()`` ban in Claude harness
    # workflows while still giving a usable monotonic-ish stamp.
    suffix = f"-{label}" if label else ""
    stamp = time.time_ns()
    pstats_path = out_dir / f"{workspace_name}{suffix}-{stamp}.prof"

    profiler = cProfile.Profile()
    t0 = time.perf_counter()
    profiler.enable()
    try:
        reindex_result = reindex_workspace(config, store)
    finally:
        profiler.disable()
    elapsed = time.perf_counter() - t0
    profiler.dump_stats(str(pstats_path))

    # Build a human-readable top-N table via pstats. ``Stats.print_stats``
    # writes to stdout; redirect to a StringIO so we can capture it.
    buf = io.StringIO()
    stats = pstats.Stats(profiler, stream=buf)
    stats.strip_dirs()
    stats.sort_stats(sort_by)
    stats.print_stats(top_n)
    top_summary = buf.getvalue()

    return ProfileResult(
        pstats_path=pstats_path,
        elapsed_s=elapsed,
        total_calls=stats.total_calls,
        primitive_calls=stats.prim_calls,
        top_summary=top_summary,
        reindex_result=reindex_result,
        extra={
            "workspace": workspace_name,
            "sort_by": sort_by,
            "top_n": top_n,
        },
    )


def aggregate_by_module(
    pstats_path: Path,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Aggregate cProfile stats by module (file) instead of by function.

    Useful for the P1-0 diagnostic question: "which subsystem of
    memory-center is hot — parsing, semantic, graph store, observability?".
    Per-function rows can be noisy; rolling them up to the module level
    gives a clearer picture of where to focus.

    Returns a list of ``{"module": ..., "cumulative_s": ..., "tottime_s":
    ..., "calls": ...}`` dicts sorted by cumulative time descending.
    """
    stats = pstats.Stats(str(pstats_path))
    stats.strip_dirs()

    # stats.stats keys are (file, line, name) tuples. Group by file.
    rollup: dict[str, dict[str, float]] = {}
    # Public-API access — pstats lacks a typed getter for the raw dict.
    # mypy/ruff will whine; we accept that for diagnostic tooling.
    for (file, _line, _name), (cc, _nc, tt, ct, _) in stats.stats.items():  # type: ignore[attr-defined]
        row = rollup.setdefault(file, {"calls": 0.0, "tottime": 0.0, "cumulative": 0.0})
        row["calls"] += cc
        row["tottime"] += tt
        row["cumulative"] += ct

    items = [
        {
            "module": file,
            "calls": int(row["calls"]),
            "tottime_s": round(row["tottime"], 3),
            "cumulative_s": round(row["cumulative"], 3),
        }
        for file, row in rollup.items()
    ]
    items.sort(key=lambda item: -item["cumulative_s"])
    return items[:limit]
