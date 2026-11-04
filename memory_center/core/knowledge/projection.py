"""Bounded task-aware projections over governed collaboration assets."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from memory_center.core.profiles import Profile, profile_for_workspace, resolve_profile

from .assets import collaboration_asset_status

_SCOPE_NOT_CONFIGURED_HINT = "未配置知识 scope：请在 workspace profile 设置 default_scope，或显式传入 scope 后重试。"
_BOUNDARY = "仅返回受治理的 Wiki 资产元数据和来源引用；Wiki 正文仍由 Personal Assistant Wiki 管理。"


def _resolve_scope(
    workspace_file: str | Path,
    scope: str | None,
    profile: Profile | str | Path | None,
) -> str | None:
    """Resolve the effective knowledge scope.

    Priority: explicit ``scope`` argument, then the explicit ``profile``
    argument, then the workspace's own ``profile:`` declaration, then
    ``MEMORY_CENTER_PROFILE``, then the neutral default profile.
    """
    explicit_scope = str(scope).strip() if scope is not None else ""
    if explicit_scope:
        return explicit_scope
    prof = resolve_profile(profile) if profile is not None else profile_for_workspace(workspace_file)
    default_scope = (prof.default_scope or "").strip()
    return default_scope or None


def workspace_knowledge_summary(
    workspace_file: str | Path,
    *,
    scope: str | None = None,
    limit: int = 5,
    task_id: str = "",
    profile: Profile | str | Path | None = None,
) -> dict[str, Any]:
    """Wiki 资产投影只按显式 ``task_id``（或其任务标题）检索（P0-2 Session-first）。

    不再回退 ``current_focus_task``：工作区排序候选不得决定知识页的检索锚点。

    ``scope`` 未显式传入时取 profile 的 ``default_scope``；两者都没有时返回结构化
    ``not_configured`` 状态而不是抛错，保证空 profile 下功能中性降级。
    """
    from ..tasks.artifacts import get_task_artifact

    resolved_scope = _resolve_scope(workspace_file, scope, profile)
    if not resolved_scope:
        return {
            "schema_version": 1,
            "kind": "workspace_knowledge_summary",
            "focus": {"kind": "none", "task_id": "", "shadow_id": "", "binding_mode": "none", "binding_reason_code": "not_configured", "is_current_session_bound": False},
            "focus_task": None,
            "task_id": "",
            "anchor_state": "unbound",
            "anchor_hint": _SCOPE_NOT_CONFIGURED_HINT,
            "scope": None,
            "scope_state": "not_configured",
            "binding_reason_code": "not_configured",
            "related_wiki": [],
            "asset_count": 0,
            "boundary": _BOUNDARY,
        }

    anchor_title = ""
    anchor_task_id = str(task_id or "").strip()
    if anchor_task_id:
        try:
            anchor_title = str(get_task_artifact(workspace_file, anchor_task_id, "context").get("title", "") or "")
        except Exception:
            anchor_title = ""
        if not anchor_title:
            # task_id 无法解析到任务空间：视为无锚点。
            anchor_task_id = ""
    if not anchor_title:
        # 无锚点时直接空状态，不借用任何工作区候选。
        assets_all = collaboration_asset_status(workspace_file, limit=100, max_chars=12_000).get("assets", [])
        wiki_assets = [item for item in assets_all if item.get("kind") == "wiki" and _in_scope(item, resolved_scope)]
        return {
            "schema_version": 1,
            "kind": "workspace_knowledge_summary",
            "focus": {"kind": "none", "task_id": "", "shadow_id": "", "binding_mode": "none", "binding_reason_code": "no_session_context", "is_current_session_bound": False},
            "focus_task": None,
            "task_id": "",
            "anchor_state": "unbound",
            "anchor_hint": "知识页检索需要当前绑定的任务；请先在任务页选择任务，或从可恢复任务中显式继续。",
            "scope": resolved_scope,
            "related_wiki": [],
            "asset_count": len(wiki_assets),
            "boundary": _BOUNDARY,
        }
    tokens = _tokens(anchor_title)
    assets = collaboration_asset_status(workspace_file, limit=100, max_chars=12_000).get("assets", [])
    wiki_assets = [item for item in assets if item.get("kind") == "wiki" and _in_scope(item, resolved_scope)]
    ranked = []
    for asset in wiki_assets:
        haystack = " ".join([str(asset.get("title", "")), " ".join(asset.get("tags", [])), str((asset.get("metadata") or {}).get("scope", ""))]).lower()
        matched = [token for token in tokens if token.lower() in haystack]
        score = len(matched) * 10 + (4 if resolved_scope in haystack else 0)
        reason = f"匹配当前任务关键词：{'、'.join(matched[:3])}" if matched else f"已绑定到 {resolved_scope} 范围"
        ranked.append({**asset, "relevance_score": score, "relation_reason": reason})
    ranked.sort(key=lambda item: (-int(item["relevance_score"]), str(item.get("title", ""))))
    return {
        "schema_version": 1,
        "kind": "workspace_knowledge_summary",
        "focus": {"kind": "task", "task_id": anchor_task_id, "shadow_id": "", "binding_mode": "explicit", "binding_reason_code": "explicit_task_id", "is_current_session_bound": True},
        "focus_task": {"task_id": anchor_task_id, "title": anchor_title},
        "task_id": anchor_task_id,
        "anchor_state": "bound",
        "scope": resolved_scope,
        "related_wiki": ranked[:limit],
        "asset_count": len(wiki_assets),
        "boundary": _BOUNDARY,
    }


def _in_scope(asset: dict[str, Any], scope: str | None) -> bool:
    if not scope:
        # 空/NULL scope 不得误命中 metadata 缺失的资产。
        return False
    metadata = asset.get("metadata") or {}
    return metadata.get("scope") == scope or scope in (asset.get("tags") or [])


def _tokens(value: str) -> list[str]:
    candidates = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z][A-Za-z0-9_-]{2,}", value)
    return list(dict.fromkeys(candidates))[:12]
