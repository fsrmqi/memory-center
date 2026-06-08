"""Tests for the unified diagnostics contract (A-04).

Covers:
- Unified status vocabulary
- Safe reason sanitizer (no path/secret leakage)
- Entry builder for success / disabled / empty / unavailable
"""
from memory_center.core.diagnostics import DIAG, diag_entry, safe_reason

# --- Status vocabulary ---

class TestDIAGStatus:
    def test_valid_statuses(self):
        for s in [DIAG.SUCCESS, DIAG.DISABLED, DIAG.EMPTY,
                   DIAG.UNAVAILABLE, DIAG.UNKNOWN, DIAG.ACTIVE, DIAG.PARTIAL]:
            assert DIAG.validate(s) == s

    def test_invalid_status_falls_back_to_unknown(self):
        assert DIAG.validate("bogus") == DIAG.UNKNOWN
        assert DIAG.validate("") == DIAG.UNKNOWN


# --- safe_reason ---

class TestSafeReason:
    def test_none_returns_empty(self):
        assert safe_reason() == ""

    def test_exception_type_name(self):
        assert safe_reason(exc=ValueError("bad")) == "ValueError"

    def test_literal_reason(self):
        assert safe_reason(reason="module disabled") == "module disabled"

    def test_strips_macos_paths(self):
        r = safe_reason(reason="failed /Users/john/.memory-center/graph.db")
        assert "/Users/" not in r

    def test_strips_linux_paths(self):
        r = safe_reason(reason="error at /home/bob/project/foo")
        assert "/home/" not in r

    def test_strips_api_keys(self):
        r = safe_reason(reason="auth failed api_key=sk-abc123secretvalue")
        assert "sk-abc123" not in r
        assert "REDACTED" in r

    def test_strips_traceback(self):
        r = safe_reason(reason="Traceback (most recent call last): File \"/x/y.py\"")
        assert "Traceback" not in r

    def test_truncates_long_reason(self):
        long = "x" * 300
        r = safe_reason(reason=long)
        assert len(r) <= 200

    def test_exception_with_path_leak(self):
        class PathError(Exception):
            pass
        try:
            raise PathError("/Users/secret/project/data.db locked")
        except PathError as e:
            r = safe_reason(exc=e)
        assert "/Users/" not in r
        assert "PathError" in r


# --- diag_entry ---

class TestDiagEntry:
    def test_success_entry(self):
        entry = diag_entry(DIAG.SUCCESS)
        assert entry == {"status": "success"}

    def test_disabled_entry(self):
        entry = diag_entry(DIAG.DISABLED, reason="vector backend not installed")
        assert entry["status"] == "disabled"
        assert entry["reason"] == "vector backend not installed"

    def test_empty_entry(self):
        entry = diag_entry(DIAG.EMPTY)
        assert entry == {"status": "empty"}

    def test_unavailable_with_exception(self):
        try:
            raise RuntimeError("disk full")
        except RuntimeError as e:
            entry = diag_entry(DIAG.UNAVAILABLE, exc=e)
        assert entry["status"] == "unavailable"
        assert "RuntimeError" in entry["reason"]

    def test_unknown_entry(self):
        entry = diag_entry(DIAG.UNKNOWN)
        assert entry == {"status": "unknown"}

    def test_extra_fields_preserved(self):
        entry = diag_entry(DIAG.ACTIVE, returned=5, total=10)
        assert entry["status"] == "active"
        assert entry["returned"] == 5
        assert entry["total"] == 10

    def test_invalid_status_normalized(self):
        entry = diag_entry("WRONG_STATUS")
        assert entry["status"] == "unknown"
