"""AML adapter HTTP server — Add/Search surface for the leaderboard.

Separate from the main ``serve-http`` bridge on purpose: this surface is
meant to be publicly reachable by the evaluation platform, so it always
requires an API key (``--aml-key`` or ``AML_KEY`` env) and refuses loopback
misconfiguration silently-explicitly (bind anywhere, but never without a
key). Only two routes exist; no workspace routes, no UI, no file access.
"""
from __future__ import annotations

import argparse
import hmac
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from memory_center.http.aml_adapter import (
    AmlContractError,
    aml_add,
    aml_search,
    check_aml_key,
    read_aml_payload,
)


def create_aml_handler(default_workspace: str, aml_key: str) -> type[BaseHTTPRequestHandler]:
    class AmlHandler(BaseHTTPRequestHandler):
        def _write_json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _authorized(self) -> bool:
            supplied = self.headers.get("X-AML-Key", "") or self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
            if check_aml_key(supplied, aml_key):
                return True
            self._write_json(401, {"error": "unauthorized", "detail": "X-AML-Key header required"})
            return False

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if not self._authorized():
                return
            try:
                payload = read_aml_payload(self)
                if parsed.path == "/aml/add":
                    self._write_json(200, aml_add(default_workspace, payload))
                elif parsed.path == "/aml/search":
                    self._write_json(200, aml_search(default_workspace, payload))
                else:
                    self._write_json(404, {"error": "not_found", "detail": "only /aml/add and /aml/search exist"})
            except AmlContractError as exc:
                self._write_json(400, {"error": exc.code, "detail": exc.detail})
            except Exception as exc:  # pragma: no cover - defensive
                self._write_json(500, {"error": "internal_error", "detail": str(exc)[:160]})

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if not self._authorized():
                return
            if parsed.path == "/aml/health":
                self._write_json(200, {"ok": True, "surface": "aml", "schema_version": 1})
                return
            self._write_json(404, {"error": "not_found", "detail": "only /aml/add, /aml/search, /aml/health"})

        def log_message(self, format: str, *args) -> None:  # noqa: N802,A002
            return

    return AmlHandler


def serve_aml(workspace_file: str, host: str = "0.0.0.0", port: int = 8790, aml_key: str = "") -> None:
    if not aml_key:
        raise ValueError("AML surface requires --aml-key / AML_KEY (public endpoint)")
    server = ThreadingHTTPServer((host, port), create_aml_handler(workspace_file, aml_key))
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Memory Center AML Add/Search surface")
    parser.add_argument("--workspace", required=True, help="Path to .memory-center/workspace.yaml")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8790)
    parser.add_argument("--aml-key", default="", help="Required; or set AML_KEY env")
    args = parser.parse_args()
    import os

    aml_key = args.aml_key or os.environ.get("AML_KEY", "")
    print({"aml": "starting", "host": args.host, "port": args.port, "auth": bool(aml_key)})
    serve_aml(args.workspace, host=args.host, port=args.port, aml_key=aml_key)


if __name__ == "__main__":
    main()
