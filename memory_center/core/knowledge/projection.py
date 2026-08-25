"""Bounded task-aware projections over governed collaboration assets."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .assets import collaboration_asset_status
from ..orchestrator.workspace_ops import workspace_status


def workspace_knowledge_summary(workspace_file: str | Path, *, scope: str = "kaipuyun", limit: int = 5) -> dict[str, Any]:
    status = workspace_status(workspace_file, view="compact", budget="small")
    focus = status.get("current_focus_task") or {}
    title = str(focus.get("title", "") or "")
    tokens = _tokens(title)
    assets = collaboration_asset_status(workspace_file, limit=100, max_chars=12_000).get("assets", [])
    wiki_assets = [item for item in assets if item.get("kind") == "wiki" and _in_scope(item, scope)]
    ranked = []
    for asset in wiki_assets:
        haystack = " ".join([str(asset.get("title", "")), " ".join(asset.get("tags", [])), str((asset.get("metadata") or {}).get("scope", ""))]).lower()
        matched = [token for token in tokens if token.lower() in haystack]
        score = len(matched) * 10 + (4 if scope in haystack else 0)
        reason = f"匹配当前任务关键词：{'、'.join(matched[:3])}" if matched else f"已绑定到 {scope} 范围"
        ranked.append({**asset, "relevance_score": score, "relation_reason": reason})
    ranked.sort(key=lambda item: (-int(item["relevance_score"]), str(item.get("title", ""))))
    return {
        "schema_version": 1,
        "kind": "workspace_knowledge_summary",
        "focus_task": focus,
        "scope": scope,
        "related_wiki": ranked[:limit],
        "asset_count": len(wiki_assets),
        "boundary": "仅返回受治理的 Wiki 资产元数据和来源引用；Wiki 正文仍由 Personal Assistant Wiki 管理。",
    }


def _in_scope(asset: dict[str, Any], scope: str) -> bool:
    metadata = asset.get("metadata") or {}
    return metadata.get("scope") == scope or scope in (asset.get("tags") or [])


def _tokens(value: str) -> list[str]:
    candidates = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z][A-Za-z0-9_-]{2,}", value)
    return list(dict.fromkeys(candidates))[:12]
