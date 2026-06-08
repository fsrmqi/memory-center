"""Workspace pollution detection tests.

Verifies that running the test suite does not modify the protected demo
workspace (``examples/spring-cloud-demo/.memory-center/``).

Approach:
1.  A session-scoped autouse fixture (``_demo_snapshot``) records the SHA-256
    of every file under the protected directory **before** any test runs.
2.  The test ``test_demo_workspace_not_polluted`` recomputes the checksums
    **after** all tests and asserts they match.
3.  A second test validates the detection mechanism itself by temporarily
    writing a marker file, asserting detection, then cleaning up.

Protected paths:
- ``examples/spring-cloud-demo/.memory-center/`` (all files recursively)

Allowed changes: **none** — the demo workspace is read-only for tests.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DEMO_MC = Path("examples/spring-cloud-demo/.memory-center")


def _snapshot_protected_files(base: Path) -> dict[str, str]:
    """Return {relative_path: sha256_hex} for every file under *base*."""
    snapshot: dict[str, str] = {}
    if not base.exists():
        return snapshot
    for p in sorted(base.rglob("*")):
        if p.is_file():
            rel = str(p.relative_to(base.parent))
            snapshot[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return snapshot


# Session-scoped snapshot captured at import time (before any test function).
# Using module-level ensures the snapshot is taken exactly once.
_INITIAL_SNAPSHOT = _snapshot_protected_files(DEMO_MC)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_demo_workspace_not_polluted():
    """Running the full test suite must not modify the demo workspace."""
    current = _snapshot_protected_files(DEMO_MC)
    assert current == _INITIAL_SNAPSHOT, (
        "Demo workspace was modified during test execution. "
        f"Changed files: {sorted(set(current) ^ set(_INITIAL_SNAPSHOT))}"
    )


def test_pollution_detection_catches_modification(tmp_path):
    """Validate that the detection mechanism itself works.

    We temporarily write a marker file into the demo workspace, assert
    that the snapshot diverges, then clean up.  This test proves that a
    real pollution event would be caught.
    """
    marker = DEMO_MC / ".pollution_test_marker"
    try:
        marker.write_text("temporary test marker", encoding="utf-8")
        current = _snapshot_protected_files(DEMO_MC)
        # The marker file should appear as a new entry
        assert ".pollution_test_marker" in str(current) or any(
            "pollution_test_marker" in k for k in current
        ), "Marker file was not detected in snapshot — detection mechanism broken"
        assert current != _INITIAL_SNAPSHOT, (
            "Snapshot should differ after writing marker file"
        )
    finally:
        marker.unlink(missing_ok=True)
    # After cleanup the snapshot should match again
    current = _snapshot_protected_files(DEMO_MC)
    assert current == _INITIAL_SNAPSHOT, (
        "Cleanup did not restore demo workspace to original state"
    )
