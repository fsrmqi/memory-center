from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import json as _json

from memory_center.core.exporters import (
    export_continuity_dashboard_html,
    export_focus_task_html,
    export_index_freshness_html,
    export_receipts_html,
    export_ref_html,
    export_memory_backend_html,
    export_timeline_html,
    export_usage_report_html,
    export_workbench_index_html,
    export_workspace_dashboard_html,
)
from memory_center.core.dispatch import CommandRegistry  # re-exported for compatibility
from memory_center.http.route_dispatch import (
    RouteParams,
    build_http_route_registry,
    _parse_int,
    _require_one,
    _require_workspace,
)
from memory_center.core.orchestrator import (
    group_impact,
    group_query,
    group_status,
    memory_callers,
    memory_callees,
    memory_execute_write,
    memory_eval_write_quality,
    memory_eval_regression_suite,
    memory_eval_index_freshness,
    memory_eval_tool_adoption,
    memory_eval_context_weight,
    memory_eval_parser_benchmark,
    memory_eval_walkthrough_quality,
    memory_eval_resume,
    memory_eval_handoff,
    memory_export_walkthrough_artifact,
    memory_method_walkthrough,
    memory_backend_query,
    memory_ref_batch,
    memory_ref_get,
    memory_tool_usage_report,
    memory_walkthrough_health,
    memory_plan_change,
    memory_plan_write,
    memory_query,
    memory_query_hybrid,
    memory_search_code,
    memory_symbol,
    memory_verify_checklist,
    memory_write_judge,
    workspace_end_session,
    workspace_handoff_packet,
    workspace_handoff_history,
    workspace_lookup_hint,
    workspace_model_profile,
    workspace_continuity_dashboard,
    workspace_dashboard,
    workspace_next_actions,
    workspace_recent_evidence,
    workspace_recent_sessions,
    workspace_record_case,
    workspace_record_close_feedback,
    workspace_resume_packet,
    workspace_resume_context,
    workspace_session_summary,
    workspace_sniff,
    workspace_start_session,
    workspace_suggest_case,
    workspace_status,
    workspace_sync_case_to_artifacts,
    workspace_sync_sniff_to_artifacts,
    workspace_unresolved_items,
    workspace_replay_write_chain,
    workspace_write_receipts,
    memory_discover,
)
from memory_center.core.artifacts import (
    append_change_log,
    append_task_change_log,
    archive_task_space,
    artifact_context,
    artifact_outline,
    auto_archive_task_spaces,
    compact_change_log,
    create_task_space,
    get_artifact,
    get_task_artifact,
    list_artifacts,
    list_task_spaces,
    resolve_task_space,
    touch_task_activity,
    update_task_status,
    update_artifact,
    update_task_artifact,
)
from memory_center.core.errors import normalize_exception



_VUE_DIST_DIR: Path | None = None


def _find_vue_dist() -> Path | None:
    """Find the Vue frontend dist directory."""
    global _VUE_DIST_DIR
    if _VUE_DIST_DIR is not None:
        return _VUE_DIST_DIR
    import memory_center
    pkg_dir = Path(memory_center.__file__).parent.parent
    vue_dist = pkg_dir / "web" / "dist"
    if vue_dist.exists() and (vue_dist / "index.html").exists():
        _VUE_DIST_DIR = vue_dist
        return _VUE_DIST_DIR
    vue_dist = Path.cwd() / "web" / "dist"
    if vue_dist.exists() and (vue_dist / "index.html").exists():
        _VUE_DIST_DIR = vue_dist
        return _VUE_DIST_DIR
    return None


_MIME_TYPES: dict[str, str] = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".json": "application/json; charset=utf-8",
}

def create_handler(default_workspace: str | Path | None = None) -> type[BaseHTTPRequestHandler]:
    workspace_file = str(Path(default_workspace).expanduser().resolve()) if default_workspace else None

    class MemoryCenterHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            try:
                # Serve Vue frontend SPA for /app routes
                vue_dist = _find_vue_dist()
                if vue_dist and (parsed.path == "/app" or parsed.path.startswith("/app/")):
                    rel_path = parsed.path[4:]  # strip "/app"
                    if not rel_path or rel_path == "/":
                        rel_path = "/index.html"
                    file_path = (vue_dist / rel_path.lstrip("/")).resolve()
                    # Security: ensure file is within vue_dist
                    if not str(file_path).startswith(str(vue_dist.resolve())):
                        self.send_error(403)
                        return
                    if file_path.is_file():
                        suffix = file_path.suffix.lower()
                        mime = _MIME_TYPES.get(suffix, "application/octet-stream")
                        body = file_path.read_bytes()
                        self.send_response(200)
                        self.send_header("Content-Type", mime)
                        self.send_header("Content-Length", str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                        return
                    # SPA fallback: serve index.html for client-side routing
                    index_html = vue_dist / "index.html"
                    if index_html.exists():
                        body = index_html.read_bytes()
                        self.send_response(200)
                        self.send_header("Content-Type", "text/html; charset=utf-8")
                        self.send_header("Content-Length", str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                        return
                if parsed.path == "/ui":
                    self._write_html(200, export_workbench_index_html(_require_workspace(params, workspace_file)))
                    return
                if parsed.path == "/ui/dashboard":
                    workspace = _require_workspace(params, workspace_file)
                    html_text = export_workspace_dashboard_html(workspace, intent=params.get("intent", [""])[0], limit=_parse_int(params, "limit", 10), view=params.get("view", ["compact"])[0], budget=params.get("budget", ["medium"])[0])
                    self._write_html(200, html_text)
                    return
                if parsed.path == "/ui/continuity":
                    workspace = _require_workspace(params, workspace_file)
                    html_text = export_continuity_dashboard_html(
                        workspace,
                        intent=params.get("intent", [""])[0],
                        task_id=params.get("task_id", [""])[0],
                        session_id=params.get("session_id", [""])[0],
                        limit=_parse_int(params, "limit", 10),
                        view=params.get("view", ["compact"])[0],
                        budget=params.get("budget", ["medium"])[0],
                    )
                    self._write_html(200, html_text)
                    return
                if parsed.path == "/ui/task":
                    workspace = _require_workspace(params, workspace_file)
                    html_text = export_focus_task_html(
                        workspace,
                        intent=params.get("intent", [""])[0],
                        task_id=params.get("task_id", [""])[0],
                        limit=_parse_int(params, "limit", 10),
                    )
                    self._write_html(200, html_text)
                    return
                if parsed.path == "/ui/ref":
                    workspace = _require_workspace(params, workspace_file)
                    html_text = export_ref_html(
                        workspace,
                        ref_id=_require_one(params, "ref_id"),
                    )
                    self._write_html(200, html_text)
                    return
                if parsed.path == "/ui/timeline":
                    workspace = _require_workspace(params, workspace_file)
                    html_text = export_timeline_html(
                        workspace,
                        intent=params.get("intent", [""])[0],
                        limit=_parse_int(params, "limit", 20),
                    )
                    self._write_html(200, html_text)
                    return
                if parsed.path == "/ui/receipts":
                    workspace = _require_workspace(params, workspace_file)
                    html_text = export_receipts_html(
                        workspace,
                        limit=_parse_int(params, "limit", 20),
                    )
                    self._write_html(200, html_text)
                    return
                if parsed.path == "/ui/usage":
                    workspace = _require_workspace(params, workspace_file)
                    html_text = export_usage_report_html(
                        workspace,
                        limit=_parse_int(params, "limit", 50),
                    )
                    self._write_html(200, html_text)
                    return
                if parsed.path == "/ui/backend":
                    workspace = _require_workspace(params, workspace_file)
                    html_text = export_memory_backend_html(
                        workspace,
                        limit=_parse_int(params, "limit", 20),
                    )
                    self._write_html(200, html_text)
                    return
                if parsed.path == "/ui/index-freshness":
                    workspace = _require_workspace(params, workspace_file)
                    html_text = export_index_freshness_html(workspace)
                    self._write_html(200, html_text)
                    return
                payload = _route_request(parsed.path, params, workspace_file)
                self._write_json(200, payload)
            except Exception as exc:  # pragma: no cover - exercised through adapter tests
                status, payload = _http_error_response(exc)
                self._write_json(status, payload)

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            # Read JSON body for POST requests (used for mutation routes with large content)
            body_data = {}
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                if content_length > 0:
                    raw_body = self.rfile.read(content_length)
                    body_data = _json.loads(raw_body) if raw_body else {}
            except Exception:
                body_data = {}
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

        def _write_json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _write_html(self, status: int, body_text: str) -> None:
            body = body_text.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return MemoryCenterHandler


def serve_http(default_workspace: str | Path | None = None, host: str = "127.0.0.1", port: int = 8765) -> None:
    server = ThreadingHTTPServer((host, port), create_handler(default_workspace))
    server.serve_forever()


def _http_error_response(exc: Exception) -> tuple[int, dict]:
    """Return the backward-compatible HTTP error body with unified metadata."""
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
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    serve_http(args.workspace, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
