"""Governed KnowledgeLink reverse links from Personal Assistant Wiki into a workspace.

契约（docs/KNOWLEDGE_LINK_INTEGRATION_PLAN.md）：复用现有 `kind=wiki` 协作资产，不建平行
registry；metadata 只保存引用、哈希与审计字段，绝不复制 Wiki 正文。

- `content_sha256` 唯一口径：Wiki 文件 raw 字节的全量 SHA-256（64 位 hex）。
- `knowledge_id` 派生自 Wiki 相对路径（`pawiki-<sha256(path)[:16]>`）。
- `link_status` 三态 active|stale|revoked；状态变化必须留状态历史（from/to/at/reason/actor）。
- 注册必须携带非空 `evidence_refs`；`binding_mode=shadow_only` 的会话不得创建 task-scoped 链接。
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from memory_center.core.knowledge.assets import (
    get_collaboration_asset,
    list_collaboration_assets,
    register_collaboration_asset,
)
from memory_center.core.knowledge.knowledge_events import record_knowledge_event
from memory_center.core.workspace.config import load_workspace_config

LINK_STATUSES = ("active", "stale", "revoked")
BRIDGE_SOURCE_PREFIX = "pawiki:"
_BRIDGE_TAG = "personal-wiki"
_MAX_EVIDENCE = 30
_MAX_STATUS_HISTORY = 20

_DEFAULT_DOCUMENTS = (
    "工作/开普云/索引.md",
    "工作/开普云/项目/众包平台.md",
    "技术/项目/MemoryCenter.md",
    "技术/项目/PersonalAssistantWikiMCP.md",
)


def knowledge_id_for_path(relative: str) -> str:
    """knowledge_id 派生自 Wiki 相对路径；路径重命名即新 id（计划：稳定标识）。"""
    return f"pawiki-{hashlib.sha256(_clean_relative(relative).encode('utf-8')).hexdigest()[:16]}"


def knowledge_link_hash(raw: bytes) -> str:
    """content_sha256 唯一口径：Wiki 文件 raw 字节的全量 SHA-256（64 位 hex）。"""
    return hashlib.sha256(raw).hexdigest()


def resolve_wiki_file(wiki_root: str | Path, relative: str) -> Path | None:
    """Resolve one Wiki relative path under root; None when unreachable or missing."""
    root_value = str(wiki_root).strip()
    if not root_value:
        return None
    root = Path(root_value).expanduser().resolve()
    clean = _clean_relative(relative)
    if not clean:
        return None
    path = (root / clean).resolve()
    if path != root and root not in path.parents:
        return None
    return path if path.is_file() else None


def _clean_relative(relative: str) -> str:
    return str(relative).strip().replace("\\", "/").strip("/")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _status_history_entry(previous: str, status: str, reason: str, actor: str) -> dict[str, Any]:
    return {
        "from": str(previous).strip()[:40],
        "to": str(status).strip()[:40],
        "at": _now(),
        "reason": str(reason).strip()[:200],
        "actor": str(actor).strip()[:120],
    }


def _merge_status_history(metadata: dict[str, Any], status: str, reason: str, actor: str) -> list[dict[str, Any]]:
    history = [item for item in metadata.get("status_history", []) if isinstance(item, dict)]
    previous = str(metadata.get("link_status", "") or "active")
    history.append(_status_history_entry(previous, status, reason, actor))
    return history[-_MAX_STATUS_HISTORY:]


def _knowledge_asset_id(knowledge_id: str) -> str:
    return f"asset-wiki-{str(knowledge_id).strip()}"


def _is_knowledge_link_asset(asset: dict[str, Any]) -> bool:
    return (
        asset.get("kind") == "wiki"
        and str(asset.get("source_ref", "")).startswith(BRIDGE_SOURCE_PREFIX)
    )


def _reregister_with_metadata(workspace_file: str | Path, existing: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    result = register_collaboration_asset(
        workspace_file,
        kind="wiki",
        title=str(existing.get("title", "")),
        owner=str(existing.get("owner", "")),
        source_ref=str(existing.get("source_ref", "")),
        visibility=str(existing.get("visibility", "private")),
        tags=existing.get("tags", []),
        context_excerpt=str(existing.get("context_excerpt", "")),
        metadata=metadata,
        asset_id=str(existing.get("asset_id", "")),
        actor=str(existing.get("owner", "")),
    )
    return result["asset"]


def register_knowledge_link(
    workspace_file: str | Path,
    *,
    relative_path: str,
    title: str,
    owner: str,
    wiki_root: str | Path = "",
    scope: str = "",
    task_id: str = "",
    binding_mode: str = "",
    relation_reason: str = "",
    evidence_refs: list[str] | None = None,
    content_sha256: str = "",
    actor: str = "",
) -> dict[str, Any]:
    """Register or idempotently refresh one KnowledgeLink (explicit calls only).

    - 相同 `(knowledge_id, content_sha256)` 且仍为 active：幂等命中，不产生新版本；
    - `evidence_refs` 为空拒绝（安全门禁：无证据不得晋升）；
    - `binding_mode=shadow_only` 的会话不得创建 task-scoped 链接；
    - 正文永不落盘：只登记引用、哈希与审计字段。
    """
    relative = _clean_relative(relative_path)
    if not relative:
        raise ValueError("relative_path is required for a KnowledgeLink")
    evidence = [str(item).strip()[:200] for item in (evidence_refs or []) if str(item).strip()][:_MAX_EVIDENCE]
    if not evidence:
        raise ValueError("evidence_refs must not be empty for a KnowledgeLink registration")
    clean_task = str(task_id).strip()
    if str(binding_mode).strip() == "shadow_only" and clean_task:
        raise ValueError("shadow_only sessions must not create task-scoped KnowledgeLinks")
    knowledge_id = knowledge_id_for_path(relative)
    path = resolve_wiki_file(wiki_root, relative)
    if path is not None:
        file_hash = knowledge_link_hash(path.read_bytes())
        if str(content_sha256).strip() and str(content_sha256).strip() != file_hash:
            raise ValueError("content_sha256 does not match the current Wiki file bytes")
        content_sha256 = file_hash
    content_sha256 = str(content_sha256).strip()
    if not content_sha256:
        raise ValueError("content_sha256 is required when the Wiki file is not reachable via wiki_root")

    config = load_workspace_config(workspace_file)
    asset_id = _knowledge_asset_id(knowledge_id)
    existing = get_collaboration_asset(workspace_file, asset_id)
    existing_metadata = dict((existing or {}).get("metadata", {}) or {})
    idempotent = bool(
        existing
        and str(existing_metadata.get("content_sha256", "")) == content_sha256
        and str(existing_metadata.get("link_status", "active") or "active") == "active"
        and str(existing_metadata.get("task_id", "")) == clean_task
    )
    if idempotent:
        return {
            "registered": False,
            "idempotent": True,
            "knowledge_id": knowledge_id,
            "asset": existing,
            "next_action": "相同 (knowledge_id, content_sha256) 已登记；未产生新版本。",
        }

    metadata: dict[str, Any] = {
        "knowledge_id": knowledge_id,
        "content_sha256": content_sha256,
        "workspace_id": config.workspace,
        "task_id": clean_task,
        "relation_reason": str(relation_reason).strip()[:300] or "人工确认的长期知识反向链接。",
        "evidence_refs": evidence,
        "link_status": "active",
        "wiki_root": str(Path(str(wiki_root)).expanduser()) if str(wiki_root).strip() else str(existing_metadata.get("wiki_root", "") or ""),
        "scope": str(scope).strip(),
        "bridge": "personal_assistant_wiki",
    }
    if existing:
        metadata["status_history"] = _merge_status_history(
            existing_metadata, "active", "re-registered with the current content hash", actor or owner,
        )
    else:
        metadata["status_history"] = [_status_history_entry("", "active", "initial registration", actor or owner)]
    result = register_collaboration_asset(
        workspace_file,
        kind="wiki",
        title=str(title).strip()[:200] or relative.rsplit("/", 1)[-1],
        owner=owner,
        source_ref=f"{BRIDGE_SOURCE_PREFIX}{relative}",
        visibility="private",
        tags=[_BRIDGE_TAG, scope] if str(scope).strip() else [_BRIDGE_TAG],
        context_excerpt="Personal Assistant Wiki 长期知识入口；正文保留在 Wiki，仅通过来源引用按需读取。",
        metadata=metadata,
        asset_id=asset_id,
        actor=actor or owner,
    )
    return {
        "registered": True,
        "idempotent": False,
        "knowledge_id": knowledge_id,
        "asset": result["asset"],
        "next_action": "KnowledgeLink 已登记；漂移检测与指标见 knowledge-link-drift / knowledge-link-metrics。",
    }


def sync_personal_wiki_assets(
    workspace_file: str | Path,
    *,
    wiki_root: str | Path,
    owner: str,
    scope: str = "kaipuyun",
    documents: list[str] | None = None,
    evidence_refs: list[str] | None = None,
) -> dict[str, Any]:
    """Register selected Personal Wiki entries as KnowledgeLinks; never copied bodies.

    显式刷新入口：仅重建反向链接并更新哈希到当前口径，不触发晋升（计划 Phase 3）。
    """
    evidence = [str(item).strip()[:200] for item in (evidence_refs or []) if str(item).strip()]
    if not evidence:
        evidence = ["command:wiki-assets-sync"]
    root = Path(wiki_root).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("wiki_root must be an existing directory")
    selected = documents or list(_DEFAULT_DOCUMENTS)
    assets: list[dict[str, Any]] = []
    skipped: list[str] = []
    for relative in selected[:20]:
        clean = _clean_relative(relative)
        path = resolve_wiki_file(root, clean)
        if path is None or path.suffix.lower() not in {".md", ".markdown"}:
            skipped.append(relative)
            continue
        raw = path.read_bytes()
        title = _title(raw.decode("utf-8", errors="replace"), path.stem)
        result = register_knowledge_link(
            workspace_file,
            relative_path=clean,
            title=title,
            owner=owner,
            wiki_root=root,
            scope=scope,
            relation_reason="个人 Wiki 长期知识入口；经 wiki-assets-sync 显式刷新。",
            evidence_refs=evidence,
            content_sha256=knowledge_link_hash(raw),
            actor=owner,
        )
        assets.append(result["asset"])
    return {
        "synced": True,
        "scope": scope,
        "assets": assets,
        "skipped": skipped,
        "next_action": "DSH 的知识页可展示这些 Wiki 反向链接；Wiki 正文仍留在 Personal Assistant Wiki。",
    }


def mark_knowledge_link_status(
    workspace_file: str | Path,
    knowledge_id: str,
    *,
    status: str,
    reason: str,
    actor: str,
) -> dict[str, Any]:
    """Explicitly transition one KnowledgeLink's link_status — the only `revoked` producer."""
    if status not in LINK_STATUSES:
        raise ValueError(f"status must be one of: {', '.join(LINK_STATUSES)}")
    if not str(reason).strip():
        raise ValueError("reason is required for a link status transition")
    if not str(actor).strip():
        raise ValueError("actor is required for a link status transition")
    clean_id = str(knowledge_id).strip()
    existing = get_collaboration_asset(workspace_file, _knowledge_asset_id(clean_id))
    if not existing or not _is_knowledge_link_asset(existing):
        return {"marked": False, "reason": "knowledge_link_not_found", "next_action": "用 knowledge-links 确认 knowledge_id。"}
    metadata = dict(existing.get("metadata", {}) or {})
    metadata["status_history"] = _merge_status_history(metadata, status, reason, actor)
    metadata["link_status"] = status
    asset = _reregister_with_metadata(workspace_file, existing, metadata)
    record_knowledge_event(
        workspace_file,
        event_type="link_status_changed",
        payload={"knowledge_id": clean_id, "to": status, "reason": str(reason).strip()[:200]},
        actor=actor,
    )
    return {"marked": True, "asset": asset, "next_action": "状态变化已留痕；stale/revoked 链接不会再进入候选。"}


def attach_knowledge_link_to_task(
    workspace_file: str | Path,
    knowledge_id: str,
    *,
    task_id: str,
    evidence_refs: list[str] | None = None,
    actor: str,
    reason: str = "",
) -> dict[str, Any]:
    """人工附着：把 KnowledgeLink 绑定到一个显式选择的 task（Phase 3 第一步动作）。"""
    clean_task = str(task_id).strip()
    if not clean_task:
        raise ValueError("task_id is required for a task-scoped attachment")
    added = [str(item).strip()[:200] for item in (evidence_refs or []) if str(item).strip()]
    if not added:
        raise ValueError("evidence_refs is required when attaching a link to a task")
    if not str(actor).strip():
        raise ValueError("actor is required for a manual attachment")
    clean_id = str(knowledge_id).strip()
    existing = get_collaboration_asset(workspace_file, _knowledge_asset_id(clean_id))
    if not existing or not _is_knowledge_link_asset(existing):
        return {"attached": False, "reason": "knowledge_link_not_found", "next_action": "用 knowledge-links 确认 knowledge_id。"}
    metadata = dict(existing.get("metadata", {}) or {})
    merged = list(dict.fromkeys([*[str(item) for item in metadata.get("evidence_refs", [])], *added]))[:_MAX_EVIDENCE]
    metadata["task_id"] = clean_task[:200]
    metadata["evidence_refs"] = merged
    asset = _reregister_with_metadata(workspace_file, existing, metadata)
    record_knowledge_event(
        workspace_file,
        event_type="manual_attach",
        payload={"knowledge_id": clean_id, "task_id": clean_task[:200], "evidence_refs": added, "note": str(reason).strip()[:200]},
        actor=actor,
    )
    return {"attached": True, "asset": asset, "next_action": "已附着到任务；证据引用已合并留痕。"}


def list_knowledge_links(
    workspace_file: str | Path,
    *,
    task_id: str = "",
    scope: str = "",
    status: str = "",
    limit: int = 50,
) -> dict[str, Any]:
    """Read-only KnowledgeLink listing with bounded, summary-only output."""
    if status and status not in LINK_STATUSES:
        raise ValueError(f"status must be one of: {', '.join(LINK_STATUSES)}")
    clean_task, clean_scope = str(task_id).strip(), str(scope).strip()
    assets = list_collaboration_assets(workspace_file, kind="wiki", limit=2000)
    links: list[dict[str, Any]] = []
    for asset in assets:
        if not _is_knowledge_link_asset(asset):
            continue
        metadata = dict(asset.get("metadata", {}) or {})
        if clean_task and str(metadata.get("task_id", "")) != clean_task:
            continue
        if clean_scope and str(metadata.get("scope", "")) != clean_scope:
            continue
        link_status = str(metadata.get("link_status", "active") or "active")
        if status and link_status != status:
            continue
        links.append({
            "asset_id": asset.get("asset_id", ""),
            "knowledge_id": str(metadata.get("knowledge_id", "")),
            "title": asset.get("title", ""),
            "source_ref": asset.get("source_ref", ""),
            "link_status": link_status,
            "task_id": str(metadata.get("task_id", "")),
            "scope": str(metadata.get("scope", "")),
            "content_sha256": str(metadata.get("content_sha256", "")),
            "wiki_root": str(metadata.get("wiki_root", "")),
            "evidence_refs": [str(item) for item in metadata.get("evidence_refs", [])][:_MAX_EVIDENCE],
            "updated_at": asset.get("updated_at", ""),
        })
    bounded = max(1, min(limit, 500))
    return {
        "count": len(links),
        "truncated": len(links) > bounded,
        "links": links[:bounded],
        "next_action": "读取链路只消费 active 链接；stale/revoked 仅供人工核查。",
    }


def _title(text: str, fallback: str) -> str:
    for line in text.splitlines()[:80]:
        if line.startswith("#"):
            title = line.lstrip("#").strip()
            if title:
                return title[:200]
    return fallback[:200]
