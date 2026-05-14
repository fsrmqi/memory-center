from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from memory_center.core.orchestrator import (
    group_impact,
    group_query,
    group_status,
    memory_callers,
    memory_callees,
    memory_plan_change,
    memory_query,
    memory_search_code,
    memory_symbol,
    memory_verify_checklist,
    workspace_recent_sessions,
    workspace_resume_context,
    workspace_session_summary,
    workspace_suggest_case,
    workspace_status,
)
from memory_center.core.artifacts import append_change_log, get_artifact, list_artifacts, update_artifact


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
    if path == "/workspace/artifacts":
        workspace = _require_workspace(params, default_workspace)
        return list_artifacts(workspace)
    if path == "/workspace/artifact":
        workspace = _require_workspace(params, default_workspace)
        name = _require_one(params, "name")
        return get_artifact(workspace, name)
    if path == "/workspace/artifact/update":
        workspace = _require_workspace(params, default_workspace)
        name = _require_one(params, "name")
        content = _require_one(params, "content")
        return update_artifact(workspace, name, content)
    if path == "/workspace/change-log/append":
        workspace = _require_workspace(params, default_workspace)
        entry = _require_one(params, "entry")
        return append_change_log(workspace, entry)
    if path == "/workspace/query":
        workspace = _require_workspace(params, default_workspace)
        query = _require_one(params, "text")
        limit = int(params.get("limit", ["20"])[0])
        return memory_query(workspace, query, limit=limit)
    if path == "/workspace/search-code":
        workspace = _require_workspace(params, default_workspace)
        query = _require_one(params, "text")
        scope = params.get("scope", [""])[0]
        limit = int(params.get("limit", ["20"])[0])
        return memory_search_code(workspace, query, scope=scope, limit=limit)
    if path == "/workspace/symbol":
        workspace = _require_workspace(params, default_workspace)
        name = _require_one(params, "name")
        limit = int(params.get("limit", ["10"])[0])
        return memory_symbol(workspace, name, limit=limit)
    if path == "/workspace/callers":
        workspace = _require_workspace(params, default_workspace)
        symbol = _require_one(params, "symbol")
        depth = int(params.get("depth", ["2"])[0])
        limit = int(params.get("limit", ["80"])[0])
        return memory_callers(workspace, symbol, depth=depth, limit=limit)
    if path == "/workspace/callees":
        workspace = _require_workspace(params, default_workspace)
        symbol = _require_one(params, "symbol")
        depth = int(params.get("depth", ["2"])[0])
        limit = int(params.get("limit", ["80"])[0])
        return memory_callees(workspace, symbol, depth=depth, limit=limit)
    if path == "/workspace/plan-change":
        workspace = _require_workspace(params, default_workspace)
        target = _require_one(params, "target")
        direction = params.get("direction", ["upstream"])[0]
        max_depth = int(params.get("max_depth", ["3"])[0])
        return memory_plan_change(workspace, target, direction=direction, max_depth=max_depth)
    if path == "/workspace/verify-checklist":
        workspace = _require_workspace(params, default_workspace)
        target = _require_one(params, "target")
        return memory_verify_checklist(workspace, target)
    if path == "/workspace/sessions/recent":
        workspace = _require_workspace(params, default_workspace)
        limit = int(params.get("limit", ["10"])[0])
        return workspace_recent_sessions(workspace, limit=limit)
    if path == "/workspace/session/summary":
        workspace = _require_workspace(params, default_workspace)
        session_id = _require_one(params, "session_id")
        return workspace_session_summary(workspace, session_id)
    if path == "/workspace/resume-context":
        workspace = _require_workspace(params, default_workspace)
        query = _require_one(params, "text")
        limit = int(params.get("limit", ["5"])[0])
        return workspace_resume_context(workspace, query, limit=limit)
    if path == "/workspace/suggest-case":
        workspace = _require_workspace(params, default_workspace)
        session_id = _require_one(params, "session_id")
        return workspace_suggest_case(workspace, session_id)
    if path == "/group/status":
        return group_status(_require_one(params, "group"))
    if path == "/group/query":
        group = _require_one(params, "group")
        query = _require_one(params, "text")
        limit = int(params.get("limit", ["20"])[0])
        return group_query(group, query, limit=limit)
    if path == "/group/impact":
        group = _require_one(params, "group")
        target = _require_one(params, "target")
        direction = params.get("direction", ["upstream"])[0]
        max_depth = int(params.get("max_depth", ["3"])[0])
        return group_impact(group, target, direction=direction, max_depth=max_depth)
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
