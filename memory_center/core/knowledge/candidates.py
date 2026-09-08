"""Anchored, bounded Wiki knowledge candidates (Phase 2 read path).

契约（docs/KNOWLEDGE_LINK_INTEGRATION_PLAN.md Read path）：
- 输入必须含任务锚点；无锚点的 Wiki 搜索不得进入 Agent 上下文（fail closed 到空列表）；
- 最多返回 3 条 `{knowledge_id,title,summary,relevance_reason,content_sha256,freshness}`；
- 0 分/缺分数/无路径条目不返回；`link_status=stale|revoked` 的已登记链接一律排除；
- 传输层固定为 `personal-assistant-wiki-bridge brief` 子进程且可注入；不可用时诚实返回空。
"""
from __future__ import annotations

import json
import math
import subprocess
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from memory_center.core.knowledge.knowledge_events import record_knowledge_event
from memory_center.core.knowledge.wiki_bridge import (
    BRIDGE_SOURCE_PREFIX,
    knowledge_id_for_path,
    knowledge_link_hash,
    list_knowledge_links,
    resolve_wiki_file,
)

MAX_CANDIDATES = 3
_BRIDGE_COMMAND = "personal-assistant-wiki-bridge"
_BRIEF_TIMEOUT_SECONDS = 15
_SUMMARY_CHARS = 280
_FETCH_MULTIPLIER = 4


def bridge_brief_transport(wiki_root: str | Path) -> Callable[..., dict[str, Any] | None]:
    """Default transport: the governed `personal-assistant-wiki-bridge brief` subprocess."""
    root = str(Path(wiki_root).expanduser())

    def transport(*, task: str, scope: str, limit: int) -> dict[str, Any] | None:
        try:
            completed = subprocess.run(
                [
                    _BRIDGE_COMMAND, "--knowledge-root", root, "brief",
                    "--task", task, "--scope", scope, "--limit", str(limit),
                ],
                capture_output=True,
                text=True,
                timeout=_BRIEF_TIMEOUT_SECONDS,
                check=True,
            )
            value = json.loads(completed.stdout)
            return value if isinstance(value, dict) else None
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
            return None

    return transport


def wiki_knowledge_candidates(
    workspace_file: str | Path,
    *,
    task: str,
    wiki_root: str | Path,
    scope: str = "",
    task_id: str = "",
    limit: int = MAX_CANDIDATES,
    min_score: float = 0.0,
    transport: Callable[..., dict[str, Any] | None] | None = None,
) -> dict[str, Any]:
    """Return at most 3 anchored Wiki candidates; every failure mode fails closed to empty."""
    clean_task = str(task).strip()
    if not clean_task:
        return {
            "ready": False,
            "reason": "anchor_missing",
            "candidates": [],
            "next_action": "无任务锚点的 Wiki 搜索不进入 Agent 上下文；请提供具体任务描述。",
        }
    bounded_limit = max(1, min(int(limit), MAX_CANDIDATES))
    brief = (transport or bridge_brief_transport(wiki_root))(task=clean_task, scope=str(scope).strip(), limit=bounded_limit * _FETCH_MULTIPLIER)
    if not isinstance(brief, dict):
        return {
            "ready": False,
            "reason": "wiki_transport_unavailable",
            "candidates": [],
            "next_action": "bridge brief 不可用；诚实返回空候选，不伪造知识。",
        }

    context = brief.get("context") if isinstance(brief.get("context"), dict) else {}
    flat: list[tuple[str, dict[str, Any]]] = []
    for group, hits in context.items():
        if not isinstance(hits, list):
            continue
        for hit in hits:
            if isinstance(hit, dict):
                flat.append((str(group), hit))

    excluded = {"low_score_or_unscored": 0, "stale_or_revoked": 0, "unhashable": 0}
    links_by_source = {str(link.get("source_ref", "")): link for link in list_knowledge_links(workspace_file, limit=500)["links"]}
    scored: list[dict[str, Any]] = []
    for group, hit in flat:
        path = str(hit.get("path", "")).strip()
        raw_score = hit.get("score")
        # Wiki bridge uses SQLite FTS5 BM25: smaller negative values rank first.
        score = -raw_score if isinstance(raw_score, (int, float)) and not isinstance(raw_score, bool) else 0.0
        if not path or not math.isfinite(score) or score <= max(0.0, min_score):
            excluded["low_score_or_unscored"] += 1
            continue
        link = links_by_source.get(f"{BRIDGE_SOURCE_PREFIX}{path}")
        link_status = str((link or {}).get("link_status", "active") or "active")
        if link_status in {"stale", "revoked"}:
            excluded["stale_or_revoked"] += 1
            continue
        content_sha256 = str((link or {}).get("content_sha256", "") or "")
        path_obj = resolve_wiki_file(wiki_root, path)
        freshness = ""
        if path_obj is not None:
            current_hash = knowledge_link_hash(path_obj.read_bytes())
            if content_sha256 and current_hash != content_sha256:
                excluded["stale_or_revoked"] += 1
                continue
            content_sha256 = current_hash
            freshness = datetime.fromtimestamp(path_obj.stat().st_mtime, tz=timezone.utc).isoformat()
        else:
            excluded["unhashable"] += 1
            continue
        if len(content_sha256) != 64:
            excluded["unhashable"] += 1
            continue
        reason = f"任务关键词命中（{group} 分组，score={score}）"
        if link:
            bound = str(link.get("task_id", "")) or "workspace-scoped"
            reason += f"；已登记链接（{link_status}，{bound}）"
        scored.append({
            "knowledge_id": str((link or {}).get("knowledge_id", "")) or knowledge_id_for_path(path),
            "attachable": bool(link),
            "title": str(hit.get("title", "")).strip()[:200] or path.rsplit("/", 1)[-1],
            "summary": str(hit.get("snippet", "")).strip()[:_SUMMARY_CHARS],
            "relevance_reason": reason,
            "content_sha256": content_sha256,
            "freshness": freshness,
            "_score": score,
        })

    scored.sort(key=lambda item: item["_score"], reverse=True)
    candidates = [{key: value for key, value in item.items() if key != "_score"} for item in scored[:bounded_limit]]
    record_knowledge_event(
        workspace_file,
        event_type="candidate_exposure",
        payload={
            "task": clean_task[:200],
            "scope": str(scope).strip()[:80],
            "task_id": str(task_id).strip()[:200],
            "count": len(candidates),
            "knowledge_ids": [candidate["knowledge_id"] for candidate in candidates],
        },
    )
    return {
        "ready": True,
        "anchor": {"task": clean_task[:200], "scope": str(scope).strip()[:80], "task_id": str(task_id).strip()[:200]},
        "candidates": candidates,
        "excluded": excluded,
        "next_action": "最多 3 条候选；正文由 Wiki 在用户显式打开时读取，不得把摘要当作已验证事实。"
        if candidates
        else "无直接证据：返回空列表。",
    }
