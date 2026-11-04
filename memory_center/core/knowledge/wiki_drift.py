"""Read-only drift detection and aggregate observability for KnowledgeLinks (Phase 4).

契约（docs/KNOWLEDGE_LINK_INTEGRATION_PLAN.md Phase 4）：
- 检测 hash 漂移、scope 失配和缺失 evidence；输出只读 repair action；
- 唯一写动作是把确认漂移的 active 链接标记为 stale（留状态历史）；不自动修复、不自动 revoke、不自动删除；
- `revoked` 只能由人工显式命令产生；
- 每个状态变化可回溯来源（status_history + knowledge-link-events.jsonl）。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from memory_center.core.knowledge.knowledge_events import read_knowledge_events
from memory_center.core.knowledge.wiki_bridge import (
    BRIDGE_SOURCE_PREFIX,
    LINK_STATUSES,
    knowledge_link_hash,
    list_knowledge_links,
    mark_knowledge_link_status,
    resolve_wiki_file,
)

_SOURCE_PREFIX_LEN = len(BRIDGE_SOURCE_PREFIX)


def knowledge_link_drift(
    workspace_file: str | Path,
    *,
    wiki_root: str = "",
    scope: str = "",
    actor: str = "workspace-system",
    mark_stale: bool = False,
) -> dict[str, Any]:
    """Detect KnowledgeLink drift; stale marking is the only write, everything else is advisory."""
    links = list_knowledge_links(workspace_file, limit=500)["links"]
    findings: list[dict[str, Any]] = []
    repair_actions: list[dict[str, Any]] = []
    stale_marked: list[str] = []
    for link in links:
        knowledge_id = str(link.get("knowledge_id", ""))
        relative = str(link.get("source_ref", ""))[_SOURCE_PREFIX_LEN:]
        root = str(wiki_root).strip() or str(link.get("wiki_root", "") or "")
        if not root:
            findings.append({
                "knowledge_id": knowledge_id,
                "kind": "wiki_root_unknown",
                "detail": "链接未记录 wiki_root 且未显式提供；无法核对内容哈希。",
            })
            repair_actions.append({
                "knowledge_id": knowledge_id,
                "action": "provide_wiki_root",
                "detail": "显式传入 wiki_root 后重跑 drift，或用 wiki-assets-sync 重新登记以落盘 root 路径。",
            })
            continue
        path_obj = resolve_wiki_file(root, relative)
        if path_obj is None:
            findings.append({
                "knowledge_id": knowledge_id,
                "kind": "wiki_entry_missing",
                "detail": f"Wiki 条目不存在：{relative}；是否 revoke 由人工决定。",
            })
            repair_actions.append({
                "knowledge_id": knowledge_id,
                "action": "confirm_revoke_or_restore",
                "detail": "人工确认条目是否已移动/删除；确认后用 knowledge-link-mark revoked，或恢复文件后 wiki-assets-sync。",
            })
            continue
        current_hash = knowledge_link_hash(path_obj.read_bytes())
        stored_hash = str(link.get("content_sha256", ""))
        if stored_hash and current_hash != stored_hash:
            if mark_stale and str(link.get("link_status", "active")) == "active":
                mark_knowledge_link_status(workspace_file, knowledge_id, status="stale", reason="content_sha256_drift", actor=actor)
                stale_marked.append(knowledge_id)
            findings.append({
                "knowledge_id": knowledge_id,
                "kind": "content_sha256_drift",
                "detail": "Wiki 内容哈希与链接登记值不一致。",
            })
            repair_actions.append({
                "knowledge_id": knowledge_id,
                "action": "refresh_via_wiki_assets_sync",
                "detail": "人工确认内容有效后用 wiki-assets-sync 刷新哈希；系统不自动重新晋升。",
            })
        expected_scope = str(scope).strip()
        link_scope = str(link.get("scope", ""))
        if expected_scope and link_scope and expected_scope != link_scope:
            findings.append({
                "knowledge_id": knowledge_id,
                "kind": "scope_mismatch",
                "detail": f"链接 scope={link_scope} 与当前 scope={expected_scope} 不一致。",
            })
        if str(link.get("task_id", "")) and not link.get("evidence_refs"):
            findings.append({
                "knowledge_id": knowledge_id,
                "kind": "evidence_refs_missing",
                "detail": "task-scoped 链接缺少证据引用。",
            })
            repair_actions.append({
                "knowledge_id": knowledge_id,
                "action": "attach_evidence_refs",
                "detail": "用 knowledge-link-attach 为该任务补充证据引用。",
            })
    return {
        "checked": len(links),
        "stale_marked": stale_marked,
        "findings": findings,
        "repair_actions": repair_actions,
        "read_only_except_stale_marking": True,
        "next_action": "修复动作只读列出；执行与否由人工决定，系统不做补偿式修复。",
    }


def knowledge_link_metrics(workspace_file: str | Path) -> dict[str, Any]:
    """Aggregate KnowledgeLink observability metrics (read-only, bounded)."""
    links = list_knowledge_links(workspace_file, limit=500)["links"]
    by_status = {status: 0 for status in LINK_STATUSES}
    unknown = 0
    task_scoped = 0
    evidence_covered = 0
    for link in links:
        status = str(link.get("link_status", "active"))
        if status in by_status:
            by_status[status] += 1
        else:
            unknown += 1
        if str(link.get("task_id", "")):
            task_scoped += 1
            if link.get("evidence_refs"):
                evidence_covered += 1
    events = read_knowledge_events(workspace_file, limit=1000)
    events_by_type: dict[str, int] = {}
    for event in events:
        event_type = str(event.get("event_type", ""))
        events_by_type[event_type] = events_by_type.get(event_type, 0) + 1
    total = len(links)
    stale_rate = round(by_status["stale"] / total, 4) if total else 0.0
    return {
        "total_links": total,
        "links_by_status": by_status,
        "unknown_status_count": unknown,
        "task_scoped_links": task_scoped,
        "evidence_covered_task_links": evidence_covered,
        "stale_rate": stale_rate,
        "events_total": len(events),
        "events_by_type": events_by_type,
        "next_action": "指标只读；stale 率升高时优先跑 knowledge-link-drift 定位。",
    }
