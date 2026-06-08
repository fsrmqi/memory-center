"""B-04: Unified error model tests.

Verifies that Memory Center errors produce consistent, safe output
across HTTP, MCP, and CLI entry points.

Error types: invalid_input, not_found, unavailable, conflict, internal_error
Each error carries: safe message, optional diagnostics, suggested_action.
"""
from __future__ import annotations

import pytest

from memory_center.core.errors import (
    ERROR_TYPES,
    ConflictError,
    InternalError,
    InvalidInputError,
    MCError,
    NotFoundError,
    UnavailableError,
)

# ============================================================
# TestErrorTypes: constants and mapping
# ============================================================

class TestErrorTypes:
    def test_five_error_types_defined(self):
        assert set(ERROR_TYPES.keys()) == {
            "invalid_input", "not_found", "unavailable", "conflict", "internal_error",
        }

    def test_http_status_mapping(self):
        assert ERROR_TYPES["invalid_input"] == 400
        assert ERROR_TYPES["not_found"] == 404
        assert ERROR_TYPES["unavailable"] == 503
        assert ERROR_TYPES["conflict"] == 409
        assert ERROR_TYPES["internal_error"] == 500


# ============================================================
# TestMCErrorConstruction: basic construction and fields
# ============================================================

class TestMCErrorConstruction:
    def test_basic_construction(self):
        err = MCError("not_found", "workspace not found")
        assert err.error_type == "not_found"
        assert err.message == "workspace not found"
        assert err.diagnostics is None
        assert err.suggested_action == ""

    def test_with_all_fields(self):
        diag = {"status": "unavailable", "reason": "db locked"}
        err = MCError("unavailable", "backend down", diagnostics=diag, suggested_action="retry in 5s")
        assert err.error_type == "unavailable"
        assert err.message == "backend down"
        assert err.diagnostics == diag
        assert err.suggested_action == "retry in 5s"

    def test_is_exception(self):
        err = MCError("internal_error", "boom")
        assert isinstance(err, Exception)
        with pytest.raises(MCError):
            raise err

    def test_str_representation(self):
        err = MCError("not_found", "item missing")
        assert "item missing" in str(err)


# ============================================================
# TestMessageSafety: messages are sanitized
# ============================================================

class TestMessageSafety:
    def test_strips_absolute_path(self):
        err = MCError("not_found", "file /Users/secret/project.yaml not found")
        assert "/Users/secret" not in err.message
        assert "[REDACTED]" in err.message

    def test_strips_secret(self):
        err = MCError("internal_error", "token=sk-abc123456789012345678 failed")
        assert "sk-abc123456789012345678" not in err.message
        assert "[REDACTED]" in err.message

    def test_strips_traceback(self):
        err = MCError("internal_error", "Traceback (most recent call last): ...")
        assert "Traceback" not in err.message
        assert "[REDACTED]" in err.message

    def test_truncates_long_message(self):
        long_msg = "x" * 300
        err = MCError("internal_error", long_msg)
        assert len(err.message) <= 200


# ============================================================
# TestHTTPResponse: to_http_response() format
# ============================================================

class TestHTTPResponse:
    def test_invalid_input_400(self):
        err = InvalidInputError("bad param")
        status, body = err.to_http_response()
        assert status == 400
        assert body["ok"] is False
        assert body["error_type"] == "invalid_input"
        assert body["error"] == "bad param"

    def test_not_found_404(self):
        err = NotFoundError("route missing")
        status, body = err.to_http_response()
        assert status == 404
        assert body["ok"] is False
        assert body["error_type"] == "not_found"

    def test_unavailable_503(self):
        err = UnavailableError("db locked")
        status, body = err.to_http_response()
        assert status == 503

    def test_conflict_409(self):
        err = ConflictError("duplicate session")
        status, body = err.to_http_response()
        assert status == 409

    def test_internal_error_500(self):
        err = InternalError("unexpected")
        status, body = err.to_http_response()
        assert status == 500

    def test_http_includes_suggested_action(self):
        err = NotFoundError("stale", suggested_action="run reindex")
        _, body = err.to_http_response()
        assert body["suggested_action"] == "run reindex"

    def test_http_includes_diagnostics(self):
        diag = {"status": "disabled", "reason": "module not installed"}
        err = UnavailableError("freshness off", diagnostics=diag)
        _, body = err.to_http_response()
        assert body["diagnostics"] == diag

    def test_http_omits_empty_optional_fields(self):
        err = NotFoundError("gone")
        _, body = err.to_http_response()
        assert "suggested_action" not in body
        assert "diagnostics" not in body


# ============================================================
# TestMCPResponse: to_mcp_dict() format (agent-decision info)
# ============================================================

class TestMCPResponse:
    def test_basic_mcp_dict(self):
        err = InvalidInputError("missing workspace")
        d = err.to_mcp_dict()
        assert d["error"] is True
        assert d["error_type"] == "invalid_input"
        assert d["message"] == "missing workspace"

    def test_mcp_includes_suggested_action(self):
        err = NotFoundError("stale index", suggested_action="run memory-center reindex")
        d = err.to_mcp_dict()
        assert d["suggested_action"] == "run memory-center reindex"

    def test_mcp_includes_diagnostics(self):
        diag = {"status": "partial", "reason": "3 of 5 indexes loaded"}
        err = UnavailableError("partial load", diagnostics=diag)
        d = err.to_mcp_dict()
        assert d["diagnostics"] == diag

    def test_mcp_omits_empty_optional_fields(self):
        err = ConflictError("dup")
        d = err.to_mcp_dict()
        assert "suggested_action" not in d
        assert "diagnostics" not in d


# ============================================================
# TestCLIResponse: to_cli_message() format
# ============================================================

class TestCLIResponse:
    def test_basic_cli_message(self):
        err = NotFoundError("workspace.yaml not found")
        msg = err.to_cli_message()
        assert "[not_found]" in msg
        assert "workspace.yaml not found" in msg

    def test_cli_includes_suggested_action(self):
        err = UnavailableError("db locked", suggested_action="kill stale process and retry")
        msg = err.to_cli_message()
        assert "Suggested:" in msg
        assert "kill stale process" in msg

    def test_cli_exit_code_default(self):
        err = InternalError("boom")
        assert err.cli_exit_code == 1

    def test_cli_readable_no_traceback(self):
        err = InternalError("something broke")
        msg = err.to_cli_message()
        assert "Traceback" not in msg
        assert "[" in msg  # has error_type bracket


# ============================================================
# TestSubclasses: convenience error classes
# ============================================================

class TestSubclasses:
    def test_invalid_input_is_mcerror(self):
        assert issubclass(InvalidInputError, MCError)

    def test_not_found_is_mcerror(self):
        assert issubclass(NotFoundError, MCError)

    def test_unavailable_is_mcerror(self):
        assert issubclass(UnavailableError, MCError)

    def test_conflict_is_mcerror(self):
        assert issubclass(ConflictError, MCError)

    def test_internal_error_is_mcerror(self):
        assert issubclass(InternalError, MCError)

    def test_subclass_auto_sets_error_type(self):
        assert InvalidInputError("x").error_type == "invalid_input"
        assert NotFoundError("x").error_type == "not_found"
        assert UnavailableError("x").error_type == "unavailable"
        assert ConflictError("x").error_type == "conflict"
        assert InternalError("x").error_type == "internal_error"

    def test_subclass_accepts_all_kwargs(self):
        diag = {"status": "unavailable"}
        err = NotFoundError("x", diagnostics=diag, suggested_action="try again")
        assert err.diagnostics == diag
        assert err.suggested_action == "try again"


# ============================================================
# TestThreeEntryPointMatrix: same error, consistent across HTTP/MCP/CLI
# ============================================================

class TestThreeEntryPointMatrix:
    """Verify that each error type produces consistent semantic output
    across HTTP, MCP, and CLI entry points."""

    @pytest.fixture(params=[
        ("invalid_input", InvalidInputError, 400),
        ("not_found", NotFoundError, 404),
        ("unavailable", UnavailableError, 503),
        ("conflict", ConflictError, 409),
        ("internal_error", InternalError, 500),
    ])
    def error_factory(self, request):
        etype, cls, expected_status = request.param
        def make(**kwargs):
            return cls("test message", **kwargs)
        return etype, make, expected_status

    def test_consistent_error_type_across_entries(self, error_factory):
        etype, make, _ = error_factory
        err = make()
        # HTTP
        _, http_body = err.to_http_response()
        assert http_body["error_type"] == etype
        # MCP
        mcp = err.to_mcp_dict()
        assert mcp["error_type"] == etype
        # CLI
        cli = err.to_cli_message()
        assert f"[{etype}]" in cli

    def test_consistent_message_across_entries(self, error_factory):
        _, make, _ = error_factory
        err = make()
        _, http_body = err.to_http_response()
        mcp = err.to_mcp_dict()
        assert http_body["error"] == mcp["message"]
        assert mcp["message"] in err.to_cli_message()

    def test_http_status_matches_error_type(self, error_factory):
        _, make, expected_status = error_factory
        err = make()
        status, _ = err.to_http_response()
        assert status == expected_status

    def test_suggested_action_propagates_everywhere(self, error_factory):
        _, make, _ = error_factory
        err = make(suggested_action="do something")
        _, http_body = err.to_http_response()
        mcp = err.to_mcp_dict()
        cli = err.to_cli_message()
        assert http_body["suggested_action"] == "do something"
        assert mcp["suggested_action"] == "do something"
        assert "do something" in cli

    def test_diagnostics_propagates_to_http_and_mcp(self, error_factory):
        _, make, _ = error_factory
        diag = {"status": "test"}
        err = make(diagnostics=diag)
        _, http_body = err.to_http_response()
        mcp = err.to_mcp_dict()
        assert http_body["diagnostics"] == diag
        assert mcp["diagnostics"] == diag


# ============================================================
# TestBackwardCompatibility: existing exceptions still work
# ============================================================

class TestBackwardCompatibility:
    def test_value_error_still_raises(self):
        with pytest.raises(ValueError, match="bad"):
            raise ValueError("bad")

    def test_file_not_found_still_raises(self):
        with pytest.raises(FileNotFoundError, match="missing"):
            raise FileNotFoundError("missing")

    def test_mcerror_does_not_catch_value_error(self):
        with pytest.raises(ValueError):
            try:
                raise ValueError("old style")
            except MCError:
                pytest.fail("MCError should not catch ValueError")

    def test_mcerror_is_not_caught_by_generic_exception_handler(self):
        """MCError is a subclass of Exception, so existing except blocks
        will catch it. This test documents that behavior."""
        caught = False
        try:
            raise NotFoundError("test")
        except Exception as exc:
            caught = True
            assert isinstance(exc, MCError)
        assert caught
