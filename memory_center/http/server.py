from __future__ import annotations

import argparse
import hmac
import json
import json as _json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from memory_center.core.foundation.dispatch import CommandRegistry as CommandRegistry  # re-exported for compatibility
from memory_center.core.foundation.errors import normalize_exception
from memory_center.http.route_dispatch import (
    RouteParams,
    _parse_int,
    _require_one,
    _require_workspace,
    build_http_route_registry,
    http_route_spec,
    is_mutating_http_route,
)

_MAX_POST_BODY_BYTES = 1_048_576


def create_handler(
    default_workspace: str | Path | None = None, *, access_token: str = ""
) -> type[BaseHTTPRequestHandler]:
    workspace_file = str(Path(default_workspace).expanduser().resolve()) if default_workspace else None
    required_token = str(access_token)

    class MemoryCenterHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            if not self._authorized():
                return
            if is_mutating_http_route(parsed.path, params):
                self._write_json(
                    405,
                    {"error": "method_not_allowed", "detail": "workspace mutations require POST", "allowed": ["POST"]},
                )
                return
            try:
                payload = _route_request(parsed.path, params, workspace_file)
                self._write_json(200, payload)
            except Exception as exc:  # pragma: no cover - exercised through adapter tests
                status, payload = _http_error_response(exc)
                self._write_json(status, payload)

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            if not self._authorized():
                return
            if "POST" not in http_route_spec(parsed.path, params).methods:
                self._write_json(
                    405,
                    {"error": "method_not_allowed", "detail": "read-only route requires GET", "allowed": ["GET"]},
                )
                return
            # Read JSON body for POST requests (used for mutation routes with large content)
            body_data = {}
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                if content_length < 0:
                    raise ValueError("invalid Content-Length")
                if content_length > _MAX_POST_BODY_BYTES:
                    self._write_json(413, {"error": "request_too_large", "max_bytes": _MAX_POST_BODY_BYTES})
                    return
                if content_length:
                    raw_body = self.rfile.read(content_length)
                    body_data = _json.loads(raw_body) if raw_body else {}
                    if not isinstance(body_data, dict):
                        raise ValueError("JSON body must be an object")
            except (TypeError, ValueError, _json.JSONDecodeError) as exc:
                self._write_json(400, {"error": "invalid_request_body", "detail": str(exc)[:160]})
                return
            try:
                # Merge body data into params; body values override query-string
                merged_params = dict(params)  # shallow copy of query-string params
                for key, value in body_data.items():
                    if isinstance(value, list):
                        merged_params[key] = [str(v) for v in value]
                    else:
                        merged_params[key] = [str(value)]
                payload = _route_request(parsed.path, merged_params, workspace_file)
                self._write_json(200, payload)
            except Exception as exc:  # pragma: no cover - exercised through adapter tests
                status, payload = _http_error_response(exc)
                self._write_json(status, payload)

        def log_message(self, format: str, *args) -> None:  # noqa: A003
            return

        def _authorized(self) -> bool:
            if not required_token:
                return True
            supplied = self.headers.get("Authorization", "")
            expected = f"Bearer {required_token}"
            if hmac.compare_digest(supplied, expected):
                return True
            self._write_json(401, {"error": "unauthorized", "detail": "Bearer access token required"})
            return False

        def _write_json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return MemoryCenterHandler


def serve_http(
    default_workspace: str | Path | None = None, host: str = "127.0.0.1", port: int = 8765, access_token: str = ""
) -> None:
    validate_http_binding(host, access_token)
    server = ThreadingHTTPServer((host, port), create_handler(default_workspace, access_token=access_token))
    server.serve_forever()


def _is_loopback_host(host: str) -> bool:
    return str(host).strip().lower() in {"127.0.0.1", "::1", "localhost"}


def validate_http_binding(host: str, access_token: str = "") -> None:
    if not _is_loopback_host(host) and not access_token:
        raise ValueError("non-loopback HTTP binding requires an access token")


def _http_error_response(exc: Exception) -> tuple[int, dict]:
    """Return the unified structured HTTP error body."""
    return normalize_exception(exc).to_http_response()


def _route_request(path: str, params: dict, default_workspace: str | None) -> dict:
    """Dispatch an HTTP path to the corresponding orchestrator/artifact call.

    The actual route table lives in ``memory_center.http.route_dispatch`` so the
    HTTP server stays small.  Only ``/health`` and the unknown-route error stay
    here; everything else flows through ``CommandRegistry``.
    """
    if path == "/health":
        return {"ok": True, "default_workspace": default_workspace}
    registry = build_http_route_registry(params, default_workspace)
    if not registry.has(path):
        raise FileNotFoundError(f"Unknown route: {path}")
    return registry.dispatch(path, RouteParams(params, default_workspace))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", help="Default workspace.yaml for workspace routes")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--access-token", default=os.environ.get("MEMORY_CENTER_HTTP_TOKEN", ""))
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    serve_http(args.workspace, host=args.host, port=args.port, access_token=args.access_token)


if __name__ == "__main__":
    main()
