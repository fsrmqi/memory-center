"""Tests for the cProfile-based reindex profiler (P1-0 tooling).

We don't assert anything about the *contents* of the profile — those
depend on whichever code paths reindex_workspace happens to traverse
on a given fixture and would be flaky. Instead we verify the contract:
- a .prof file is written
- the human-readable summary is non-empty and looks like pstats output
- the module rollup helper returns rows in cumulative-descending order
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from memory_center.core.perf import aggregate_by_module, profile_reindex


@pytest.fixture
def demo_workspace_copy(tmp_path: Path) -> Path:
    """Copy the spring-cloud-demo workspace into ``tmp_path``.

    We must work on a copy because ``profile_reindex`` will rewrite
    the index/graph/etc. under ``.memory-center/`` and the fixture
    tree is shared across the test suite.
    """
    src = Path(__file__).parent.parent / "examples" / "spring-cloud-demo"
    if not src.exists():
        pytest.skip("examples/spring-cloud-demo missing — cannot exercise profiler")
    dst = tmp_path / "spring-cloud-demo"
    shutil.copytree(src, dst)
    # Drop generated artefacts so profile starts cold.
    for sub in ("index", "graph", "semantic", "evaluation", "perf-profiles"):
        leftover = dst / ".memory-center" / sub
        if leftover.exists():
            shutil.rmtree(leftover, ignore_errors=True)
    # Patch root path inside workspace.yaml so the copy is self-contained.
    ws_file = dst / ".memory-center" / "workspace.yaml"
    text = ws_file.read_text(encoding="utf-8")
    # Replace the original absolute root with the copy's path.
    text = text.replace("/Users/cuijiaqi/Ai-common-skills/memory-center/examples/spring-cloud-demo", str(dst))
    ws_file.write_text(text, encoding="utf-8")
    return ws_file


def test_profile_reindex_writes_pstats(demo_workspace_copy: Path) -> None:
    result = profile_reindex(demo_workspace_copy, top_n=10)
    assert result.pstats_path.exists(), "pstats file should be written to disk"
    assert result.pstats_path.stat().st_size > 0
    assert result.elapsed_s > 0.0
    assert result.total_calls > 0
    # The pstats header lives at the top of the summary string.
    assert "function calls" in result.top_summary.lower()


def test_profile_reindex_respects_top_n(demo_workspace_copy: Path) -> None:
    """Top-N should be reflected in the printed summary length. We
    don't pin an exact line count (the rendered table includes a
    header and ordering noise) but a smaller N must produce a strictly
    shorter summary than a larger N on the same run."""
    small = profile_reindex(demo_workspace_copy, top_n=3, label="small")
    big = profile_reindex(demo_workspace_copy, top_n=30, label="big")
    assert len(big.top_summary) > len(small.top_summary)


def test_aggregate_by_module_returns_sorted_rows(demo_workspace_copy: Path) -> None:
    result = profile_reindex(demo_workspace_copy, top_n=5)
    rows = aggregate_by_module(result.pstats_path, limit=10)
    assert rows, "module rollup must surface at least one entry"
    # Sorted by cumulative_s descending.
    cumulative_seq = [row["cumulative_s"] for row in rows]
    assert cumulative_seq == sorted(cumulative_seq, reverse=True)
    # Schema sanity.
    sample = rows[0]
    assert set(sample.keys()) == {"module", "calls", "tottime_s", "cumulative_s"}
    assert isinstance(sample["module"], str)
    assert isinstance(sample["calls"], int)
    assert isinstance(sample["tottime_s"], float)
    assert isinstance(sample["cumulative_s"], float)
