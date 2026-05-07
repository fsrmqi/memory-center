from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from memory_center.core.orchestrator import group_query, group_status, memory_query, workspace_status


def create_handler(default_workspace: str | Path | None = None) -> type[BaseHTTPRequestHandler]:
    workspace_file = str(Path(default_workspace).expanduser().resolve()) if default_workspace else None

    class MemoryCenterHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            try:
                payload = _route_request(parsed.path, params, workspace_file)
                self._write_json(200, payload)
            except FileNotFoundError as exc:
                self._write_json(404, {"ok": False, "error": str(exc)})
            except ValueError as exc:
                self._write_json(400, {"ok": False, "error": str(exc)})
            except Exception as exc:  # pragma: no cover
                self._write_json(500, {"ok": False, "error": str(exc)})

        def log_message(self, format: str, *args) -> None:  # noqa: A003
            return

        def _write_json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return MemoryCenterHandler


def serve_http(default_workspace: str | Path | None = None, host: str = "127.0.0.1", port: int = 8765) -> None:
    server = ThreadingHTTPServer((host, port), create_handler(default_workspace))
    server.serve_forever()


def _route_request(path: str, params: dict, default_workspace: str | None) -> dict:
    if path == "/health":
        return {"ok": True, "default_workspace": default_workspace}
    if path == "/workspace/status":
        workspace = _require_workspace(params, default_workspace)
        return workspace_status(workspace)
    if path == "/workspace/query":
        workspace = _require_workspace(params, default_workspace)
        query = _require_one(params, "text")
        limit = int(params.get("limit", ["20"])[0])
        return memory_query(workspace, query, limit=limit)
    if path == "/group/status":
        return group_status(_require_one(params, "group"))
    if path == "/group/query":
        group = _require_one(params, "group")
        query = _require_one(params, "text")
        limit = int(params.get("limit", ["20"])[0])
        return group_query(group, query, limit=limit)
    raise FileNotFoundError(f"Unknown route: {path}")


def _require_workspace(params: dict, default_workspace: str | None) -> str:
    value = params.get("workspace", [default_workspace])[0]
    if not value:
        raise ValueError("workspace query param is required when no default workspace is configured")
    return value


def _require_one(params: dict, key: str) -> str:
    value = params.get(key, [""])[0].strip()
    if not value:
        raise ValueError(f"{key} query param is required")
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", help="Default workspace.yaml for workspace routes")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    serve_http(args.workspace, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
