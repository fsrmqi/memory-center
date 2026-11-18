"""查询结果与会话状态的边界适配：去重降权与交付记录集中在此处。"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def apply_served_file_downweight(
    result: dict[str, Any], workspace_file: str | Path, session_id: str,
) -> dict[str, Any]:
    """按会话已服务文件保守降权；任何失败返回未应用状态。"""
    payload = dict(result)
    applied = False
    if session_id.strip():
        try:
            from memory_center.core.storage.served_ledger import paths_refer_to_same_file, served_files

            served = served_files(workspace_file, session_id)
            results = payload.get("results", [])
            if served and isinstance(results, list):
                for item in results:
                    node = item.get("node", {}) if isinstance(item, dict) and isinstance(item.get("node"), dict) else {}
                    node_path = str(node.get("file_path", "") or node.get("path", "") or "")
                    if node_path and any(paths_refer_to_same_file(node_path, seen_path) for seen_path in served):
                        item["score"] = item.get("score", 0) * 0.5
                        item["_served_before"] = True
                        applied = True
                if applied:
                    results.sort(key=lambda item: item.get("score", 0), reverse=True)
        except Exception:
            applied = False
    payload["served_dedup"] = {"applied": applied, "session_id": str(session_id or "")}
    return payload


def record_lookup_delivery(workspace_file: str | Path, session_id: str, payload: dict[str, Any], *, tier: str = "") -> None:
    """记录已交付文件；仅 bookkeeping，失败不影响查询结果。"""
    if not session_id.strip():
        return
    try:
        from memory_center.core.storage.served_ledger import extract_file_paths_from_payload, record_served_files

        record_served_files(workspace_file, session_id, extract_file_paths_from_payload(payload), tier=tier)
    except Exception:
        return


__all__ = ["apply_served_file_downweight", "record_lookup_delivery"]
