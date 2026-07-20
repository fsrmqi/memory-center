"""Tests for the worker-count and serial-fallback behaviour of
indexing.parallel.

The previous estimator returned 0 workers for any project with fewer
than 10 files, silently bypassing the thread pool. The rewrite picks
sensible counts for tiny / small / large batches and still falls back
to a serial loop when only one worker is worth spinning up.
"""
from __future__ import annotations

from pathlib import Path

from memory_center.core.indexing.parallel import (
    estimate_optimal_workers,
    parse_files_parallel,
)


def test_estimate_returns_one_for_tiny_batches() -> None:
    """Spinning up a thread pool for a couple of files costs more than
    it saves; the estimator must say 'just go serial' here."""
    for n in (0, 1, 2, 3, 4):
        assert estimate_optimal_workers(n) == 1, n


def test_estimate_scales_with_cpu_for_medium_batches() -> None:
    """Anything beyond a handful of files should hit at least 2 workers,
    and small batches should not silently fall back to 0 as the
    previous estimator did."""
    assert estimate_optimal_workers(8) >= 2
    assert estimate_optimal_workers(50) >= 2


def test_estimate_respects_max_cap() -> None:
    """A huge file count must still be capped at the explicit max."""
    assert estimate_optimal_workers(10_000, max_workers=6) == 6


def test_estimate_does_not_exceed_file_count() -> None:
    """Don't over-provision workers when only a few files exist."""
    assert estimate_optimal_workers(5) <= 5


# ── parse_files_parallel ──────────────────────────────────────────────────


def test_parse_files_parallel_returns_all_results(tmp_path: Path) -> None:
    files: list[tuple[str, Path]] = []
    for i in range(20):
        path = tmp_path / f"f{i}.java"
        path.write_text(f"class C{i} {{}}", encoding="utf-8")
        files.append(("svc", path))

    def parse_fn(text: str, file_path: str) -> object:
        return {"text_len": len(text), "path": file_path}

    results = parse_files_parallel(files, parse_fn)  # type: ignore[arg-type]
    # Every file should be represented in the output.
    assert len(results) == 20
    paths = {str(p) for _, p, _ in results}
    assert paths == {str(p) for _, p in files}
    # Every successful parse contains a dict; failures (none here) → None.
    assert all(r is not None for _, _, r in results)


def test_parse_files_parallel_handles_read_errors_gracefully(tmp_path: Path) -> None:
    """A read failure on one file must not blow up the whole batch."""
    good = tmp_path / "good.java"
    good.write_text("class G {}", encoding="utf-8")
    missing = tmp_path / "missing.java"  # never created

    def parse_fn(text: str, file_path: str) -> object:
        return {"len": len(text)}

    results = parse_files_parallel(
        [("s", good), ("s", missing)], parse_fn  # type: ignore[arg-type]
    )
    by_path = {str(p): r for _, p, r in results}
    assert by_path[str(good)] is not None
    assert by_path[str(missing)] is None


def test_parse_files_parallel_serial_fallback_when_workers_eq_one(tmp_path: Path) -> None:
    """Forcing max_workers=1 must still execute every file (no silent
    skip when the pool would otherwise have been bypassed)."""
    files: list[tuple[str, Path]] = []
    for i in range(3):
        p = tmp_path / f"x{i}.java"
        p.write_text(f"class X{i} {{}}", encoding="utf-8")
        files.append(("svc", p))

    def parse_fn(text: str, file_path: str) -> object:
        return text

    results = parse_files_parallel(files, parse_fn, max_workers=1)  # type: ignore[arg-type]
    assert len(results) == 3
    assert all(r is not None for _, _, r in results)
