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
    memory_execute_write,
    memory_eval_write_quality,
    memory_eval_resume,
    memory_eval_handoff,
    memory_tool_usage_report,
    memory_plan_change,
    memory_plan_write,
    memory_query,
    memory_search_code,
    memory_symbol,
    memory_verify_checklist,
    memory_write_judge,
    workspace_handoff_packet,
    workspace_handoff_history,
    workspace_lookup_hint,
    workspace_model_profile,
    workspace_continuity_dashboard,
    workspace_dashboard,
    workspace_next_actions,
    workspace_recent_evidence,
    workspace_recent_sessions,
    workspace_resume_packet,
    workspace_resume_context,
    workspace_session_summary,
    workspace_suggest_case,
    workspace_status,
    workspace_sync_case_to_artifacts,
    workspace_sync_sniff_to_artifacts,
    workspace_unresolved_items,
    workspace_replay_write_chain,
    workspace_write_receipts,
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
    if path == "/workspace/artifact/outline":
        workspace = _require_workspace(params, default_workspace)
        name = _require_one(params, "name")
        return artifact_outline(workspace, name)
    if path == "/workspace/artifact/context":
        workspace = _require_workspace(params, default_workspace)
        intent = _require_one(params, "intent")
        limit = _parse_int(params, "limit", 6)
        return artifact_context(workspace, intent, limit=limit)
    if path == "/workspace/artifact/update":
        workspace = _require_workspace(params, default_workspace)
        name = _require_one(params, "name")
        content = _require_one(params, "content")
        return update_artifact(workspace, name, content)
    if path == "/workspace/change-log/append":
        workspace = _require_workspace(params, default_workspace)
        entry = _require_one(params, "entry")
        return append_change_log(workspace, entry)
    if path == "/workspace/change-log/compact":
        workspace = _require_workspace(params, default_workspace)
        keep_recent = _parse_int(params, "keep_recent", 30)
        return compact_change_log(workspace, keep_recent=keep_recent)
    if path == "/workspace/task-spaces":
        workspace = _require_workspace(params, default_workspace)
        include_archived = params.get("include_archived", ["false"])[0].lower() == "true"
        return list_task_spaces(workspace, include_archived=include_archived)
    if path == "/workspace/task-space/resolve":
        workspace = _require_workspace(params, default_workspace)
        intent = _require_one(params, "intent")
        title = params.get("title", [""])[0]
        create_if_missing = params.get("create_if_missing", ["true"])[0].lower() == "true"
        include_archived = params.get("include_archived", ["false"])[0].lower() == "true"
        limit_candidates = _parse_int(params, "limit_candidates", 3)
        score_threshold = _parse_int(params, "score_threshold", 3)
        return resolve_task_space(workspace, intent=intent, title=title, create_if_missing=create_if_missing, include_archived=include_archived, limit_candidates=limit_candidates, score_threshold=score_threshold)
    if path == "/workspace/task-space/create":
        workspace = _require_workspace(params, default_workspace)
        title = params.get("title", [""])[0]
        intent = params.get("intent", [""])[0]
        owner = params.get("owner", [""])[0]
        tags = [item for item in params.get("tag", []) if item]
        priority = params.get("priority", ["medium"])[0]
        return create_task_space(workspace, title=title, intent=intent, owner=owner, tags=tags, priority=priority)
    if path == "/workspace/task-artifact":
        workspace = _require_workspace(params, default_workspace)
        task_id = _require_one(params, "task_id")
        name = _require_one(params, "name")
        return get_task_artifact(workspace, task_id, name)
    if path == "/workspace/task-artifact/update":
        workspace = _require_workspace(params, default_workspace)
        task_id = _require_one(params, "task_id")
        name = _require_one(params, "name")
        content = _require_one(params, "content")
        return update_task_artifact(workspace, task_id, name, content)
    if path == "/workspace/task-change-log/append":
        workspace = _require_workspace(params, default_workspace)
        task_id = _require_one(params, "task_id")
        entry = _require_one(params, "entry")
        keep_recent = _parse_int(params, "keep_recent", 30)
        return append_task_change_log(workspace, task_id, entry, keep_recent=keep_recent)
    if path == "/workspace/task-space/archive":
        workspace = _require_workspace(params, default_workspace)
        task_id = _require_one(params, "task_id")
        reason = params.get("reason", [""])[0]
        return archive_task_space(workspace, task_id, reason=reason)
    if path == "/workspace/task-space/status":
        workspace = _require_workspace(params, default_workspace)
        task_id = _require_one(params, "task_id")
        status = _require_one(params, "status")
        return update_task_status(workspace, task_id, status)
    if path == "/workspace/task-space/touch-activity":
        workspace = _require_workspace(params, default_workspace)
        task_id = _require_one(params, "task_id")
        source = _require_one(params, "source")
        return touch_task_activity(workspace, task_id, source)
    if path == "/workspace/task-spaces/auto-archive":
        workspace = _require_workspace(params, default_workspace)
        retention_days = _parse_int(params, "retention_days", 30)
        return auto_archive_task_spaces(workspace, retention_days=retention_days)
    if path == "/workspace/artifacts/sync-sniff":
        workspace = _require_workspace(params, default_workspace)
        intent = _require_one(params, "intent")
        limit = _parse_int(params, "limit", 12)
        task_id = params.get("task_id", [""])[0]
        title = params.get("title", [""])[0]
        auto_sync_mode = params.get("auto_sync_mode", ["balanced"])[0]
        return workspace_sync_sniff_to_artifacts(
            workspace,
            intent,
            limit=limit,
            task_id=task_id,
            title=title,
            auto_sync_mode=auto_sync_mode,
        )
    if path == "/workspace/artifacts/sync-case":
        workspace = _require_workspace(params, default_workspace)
        session_id = _require_one(params, "session_id")
        task_id = params.get("task_id", [""])[0]
        title = params.get("title", [""])[0]
        auto_sync_mode = params.get("auto_sync_mode", ["balanced"])[0]
        return workspace_sync_case_to_artifacts(
            workspace,
            session_id,
            task_id=task_id,
            title=title,
            auto_sync_mode=auto_sync_mode,
        )
    if path == "/workspace/query":
        workspace = _require_workspace(params, default_workspace)
        query = _require_one(params, "text")
        limit = _parse_int(params, "limit", 20)
        return memory_query(workspace, query, limit=limit)
    if path == "/workspace/search-code":
        workspace = _require_workspace(params, default_workspace)
        query = _require_one(params, "text")
        scope = params.get("scope", [""])[0]
        limit = _parse_int(params, "limit", 20)
        return memory_search_code(workspace, query, scope=scope, limit=limit)
    if path == "/workspace/lookup-hint":
        workspace = _require_workspace(params, default_workspace)
        query = _require_one(params, "query")
        intent = params.get("intent", [""])[0]
        limit = _parse_int(params, "limit", 8)
        return workspace_lookup_hint(workspace, query=query, intent=intent, limit=limit)
    if path == "/workspace/symbol":
        workspace = _require_workspace(params, default_workspace)
        name = _require_one(params, "name")
        limit = _parse_int(params, "limit", 10)
        return memory_symbol(workspace, name, limit=limit)
    if path == "/workspace/callers":
        workspace = _require_workspace(params, default_workspace)
        symbol = _require_one(params, "symbol")
        depth = _parse_int(params, "depth", 2)
        limit = _parse_int(params, "limit", 80, max_val=500)
        return memory_callers(workspace, symbol, depth=depth, limit=limit)
    if path == "/workspace/callees":
        workspace = _require_workspace(params, default_workspace)
        symbol = _require_one(params, "symbol")
        depth = _parse_int(params, "depth", 2)
        limit = _parse_int(params, "limit", 80, max_val=500)
        return memory_callees(workspace, symbol, depth=depth, limit=limit)
    if path == "/workspace/plan-change":
        workspace = _require_workspace(params, default_workspace)
        target = _require_one(params, "target")
        direction = params.get("direction", ["upstream"])[0]
        max_depth = _parse_int(params, "max_depth", 3)
        return memory_plan_change(workspace, target, direction=direction, max_depth=max_depth)
    if path == "/workspace/memory-write-judge":
        workspace = _require_workspace(params, default_workspace)
        text = _require_one(params, "text")
        source = params.get("source", ["note"])[0]
        intent = params.get("intent", [""])[0]
        prefer_layer = params.get("prefer_layer", [""])[0]
        return memory_write_judge(workspace, text=text, source=source, intent=intent, prefer_layer=prefer_layer, projects=params.get("project", []) or None, files=params.get("file", []) or None)
    if path == "/workspace/memory-plan-write":
        workspace = _require_workspace(params, default_workspace)
        text = _require_one(params, "text")
        source = params.get("source", ["note"])[0]
        intent = params.get("intent", [""])[0]
        session_id = params.get("session_id", [""])[0]
        task_id = params.get("task_id", [""])[0]
        title = params.get("title", [""])[0]
        prefer_layer = params.get("prefer_layer", [""])[0]
        return memory_plan_write(workspace, text=text, source=source, intent=intent, session_id=session_id, task_id=task_id, title=title, prefer_layer=prefer_layer, projects=params.get("project", []) or None, files=params.get("file", []) or None)
    if path == "/workspace/memory-execute-write":
        workspace = _require_workspace(params, default_workspace)
        text = _require_one(params, "text")
        source = params.get("source", ["note"])[0]
        intent = params.get("intent", [""])[0]
        session_id = params.get("session_id", [""])[0]
        task_id = params.get("task_id", [""])[0]
        title = params.get("title", [""])[0]
        prefer_layer = params.get("prefer_layer", [""])[0]
        return memory_execute_write(workspace, text=text, source=source, intent=intent, session_id=session_id, task_id=task_id, title=title, prefer_layer=prefer_layer, projects=params.get("project", []) or None, files=params.get("file", []) or None)
    if path == "/workspace/write-receipts":
        workspace = _require_workspace(params, default_workspace)
        return workspace_write_receipts(
            workspace,
            layer=params.get("layer", [""])[0],
            action=params.get("action", [""])[0],
            scope=params.get("scope", [""])[0],
            task_id=params.get("task_id", [""])[0],
            session_id=params.get("session_id", [""])[0],
            limit=_parse_int(params, "limit", 50),
        )
    if path == "/workspace/replay-write-chain":
        workspace = _require_workspace(params, default_workspace)
        return workspace_replay_write_chain(
            workspace,
            task_id=params.get("task_id", [""])[0],
            session_id=params.get("session_id", [""])[0],
            limit=_parse_int(params, "limit", 100),
        )
    if path == "/workspace/eval-write-quality":
        workspace = _require_workspace(params, default_workspace)
        return memory_eval_write_quality(
            workspace,
            task_id=params.get("task_id", [""])[0],
            session_id=params.get("session_id", [""])[0],
            intent=params.get("intent", [""])[0],
            limit=_parse_int(params, "limit", 100),
        )
    if path == "/workspace/eval-resume":
        workspace = _require_workspace(params, default_workspace)
        return memory_eval_resume(
            workspace,
            task_id=params.get("task_id", [""])[0],
            session_id=params.get("session_id", [""])[0],
            intent=params.get("intent", [""])[0],
            limit=_parse_int(params, "limit", 20),
        )
    if path == "/workspace/eval-handoff":
        workspace = _require_workspace(params, default_workspace)
        return memory_eval_handoff(
            workspace,
            target_model=_require_one(params, "target_model"),
            task_id=params.get("task_id", [""])[0],
            session_id=params.get("session_id", [""])[0],
            intent=params.get("intent", [""])[0],
            limit=_parse_int(params, "limit", 20),
        )
    if path == "/workspace/tool-usage-report":
        workspace = _require_workspace(params, default_workspace)
        return memory_tool_usage_report(
            workspace,
            limit=_parse_int(params, "limit", 200),
        )
    if path == "/workspace/verify-checklist":
        workspace = _require_workspace(params, default_workspace)
        target = _require_one(params, "target")
        return memory_verify_checklist(workspace, target)
    if path == "/workspace/sessions/recent":
        workspace = _require_workspace(params, default_workspace)
        limit = _parse_int(params, "limit", 10)
        return workspace_recent_sessions(workspace, limit=limit)
    if path == "/workspace/session/summary":
        workspace = _require_workspace(params, default_workspace)
        session_id = _require_one(params, "session_id")
        return workspace_session_summary(workspace, session_id)
    if path == "/workspace/recent-evidence":
        workspace = _require_workspace(params, default_workspace)
        return workspace_recent_evidence(
            workspace,
            task_id=params.get("task_id", [""])[0],
            session_id=params.get("session_id", [""])[0],
            limit=_parse_int(params, "limit", 10),
        )
    if path == "/workspace/unresolved-items":
        workspace = _require_workspace(params, default_workspace)
        return workspace_unresolved_items(
            workspace,
            task_id=params.get("task_id", [""])[0],
            session_id=params.get("session_id", [""])[0],
            intent=params.get("intent", [""])[0],
            limit=_parse_int(params, "limit", 10),
        )
    if path == "/workspace/next-actions":
        workspace = _require_workspace(params, default_workspace)
        return workspace_next_actions(
            workspace,
            task_id=params.get("task_id", [""])[0],
            session_id=params.get("session_id", [""])[0],
            intent=params.get("intent", [""])[0],
            limit=_parse_int(params, "limit", 8),
        )
    if path == "/workspace/resume-packet":
        workspace = _require_workspace(params, default_workspace)
        return workspace_resume_packet(
            workspace,
            task_id=params.get("task_id", [""])[0],
            session_id=params.get("session_id", [""])[0],
            intent=params.get("intent", [""])[0],
            limit=_parse_int(params, "limit", 10),
        )
    if path == "/workspace/model-profile":
        return workspace_model_profile(_require_one(params, "model_name"))
    if path == "/workspace/handoff-packet":
        workspace = _require_workspace(params, default_workspace)
        return workspace_handoff_packet(
            workspace,
            target_model=_require_one(params, "target_model"),
            task_id=params.get("task_id", [""])[0],
            session_id=params.get("session_id", [""])[0],
            intent=params.get("intent", [""])[0],
            limit=_parse_int(params, "limit", 10),
        )
    if path == "/workspace/handoff-history":
        workspace = _require_workspace(params, default_workspace)
        return workspace_handoff_history(
            workspace,
            target_model=params.get("target_model", [""])[0],
            task_id=params.get("task_id", [""])[0],
            session_id=params.get("session_id", [""])[0],
            limit=_parse_int(params, "limit", 50),
        )
    if path == "/workspace/continuity-dashboard":
        workspace = _require_workspace(params, default_workspace)
        return workspace_continuity_dashboard(
            workspace,
            intent=params.get("intent", [""])[0],
            task_id=params.get("task_id", [""])[0],
            session_id=params.get("session_id", [""])[0],
            limit=_parse_int(params, "limit", 10),
        )
    if path == "/workspace/dashboard":
        workspace = _require_workspace(params, default_workspace)
        return workspace_dashboard(
            workspace,
            intent=params.get("intent", [""])[0],
            limit=_parse_int(params, "limit", 10),
        )
    if path == "/workspace/resume-context":
        workspace = _require_workspace(params, default_workspace)
        query = _require_one(params, "text")
        limit = _parse_int(params, "limit", 5)
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
        limit = _parse_int(params, "limit", 20)
        return group_query(group, query, limit=limit)
    if path == "/group/impact":
        group = _require_one(params, "group")
        target = _require_one(params, "target")
        direction = params.get("direction", ["upstream"])[0]
        max_depth = _parse_int(params, "max_depth", 3)
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


def _parse_int(params: dict, key: str, default: int, min_val: int = 1, max_val: int = 10000) -> int:
    raw = params.get(key, [str(default)])[0]
    try:
        value = int(raw)
    except (ValueError, TypeError):
        raise ValueError(f"{key} must be an integer, got: {raw!r}")
    return max(min_val, min(value, max_val))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", help="Default workspace.yaml for workspace routes")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    serve_http(args.workspace, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
