from __future__ import annotations

import gzip
import json
import os
import re
import shutil
from collections.abc import Callable
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4

from filelock import FileLock

from memory_center.core.foundation.text import base_tokenize
from memory_center.core.storage.workspace import WorkspaceStore, _safe_path
from memory_center.core.workspace.config import load_workspace_config

from .receipts import build_write_receipt, persist_write_receipt, query_write_receipts

DEFAULT_ARTIFACTS = {
    "context": "context.md",
    "requirement": "requirement.md",
    "design": "design.md",
    "plan": "plan.md",
    "test_plan": "test-plan.md",
    "change_log": "change-log.md",
}
CORE_MEMORY_BLOCKS = {
    "workspace_profile": "memory-blocks/workspace-profile.md",
    "team_rules": "memory-blocks/team-rules.md",
    "architecture_invariants": "memory-blocks/architecture-invariants.md",
    "active_migration_policy": "memory-blocks/active-migration-policy.md",
}
TASK_ONLY_ARTIFACTS = {
    "current_summary": "current-summary.md",
    "summary_history": "summary-history.md",
}
APPEND_ONLY_ARTIFACT_KEYS = {
    "context",
    "requirement",
    "design",
    "plan",
    "test_plan",
    "change_log",
    "current_summary",
}

TASKS_DIR = "tasks"
ARCHIVE_DIR = "archive/tasks"
# task_id 是标题 slug，同名任务重建后会复用同一个归档路径。命名冲突时旧归档
# 会被移到这个目录，而不是被删除。
ARCHIVE_SUPERSEDED_DIR = "archive/superseded/tasks"
TASK_STATUSES = {"draft", "active", "blocked", "done", "archived"}
DEFAULT_RESOLVE_SCORE_THRESHOLD = 3
TASK_ARTIFACT_EXCERPT_BYTES = 16 * 1024
TASK_ARTIFACT_HEALTH_EXCERPT_BYTES = 64 * 1024
TASK_ARTIFACT_WRITE_MAX_BYTES = 512 * 1024
TASK_ARTIFACT_COMPACT_THRESHOLD_BYTES = 2 * 1024 * 1024
TASK_ARTIFACT_COMPACT_KEEP_BYTES = 64 * 1024
TASK_EVIDENCE_INLINE_MAX_BYTES = 64 * 1024
TASK_DECISIONS_FILE = "decisions.jsonl"
ARTIFACT_WRITE_AUDIT_FILE = "artifact-write-audit.jsonl"
TASK_HEALTH_ARTIFACTS = ["current_summary", "context", "requirement", "design", "plan", "test_plan", "change_log"]


def ensure_default_artifacts(workspace_file: str | Path) -> list[dict[str, str]]:
    config = load_workspace_config(workspace_file)
    store = WorkspaceStore(workspace_file)
    created: list[dict[str, str]] = []
    for key, filename in DEFAULT_ARTIFACTS.items():
        if store.artifact_exists(filename):
            continue
        content = _default_artifact_content(config.workspace, key)
        store.write_artifact(filename, content)
        created.append({"name": key, "file": filename})
    for key, filename in CORE_MEMORY_BLOCKS.items():
        if store.artifact_exists(filename):
            continue
        content = _default_core_memory_block_content(config.workspace, key)
        store.write_artifact(filename, content)
        created.append({"name": key, "file": filename})
    return created


def list_artifacts(workspace_file: str | Path) -> dict[str, object]:
    config = load_workspace_config(workspace_file)
    store = WorkspaceStore(workspace_file)
    ensure_default_artifacts(workspace_file)
    items = []
    for key, filename in DEFAULT_ARTIFACTS.items():
        path = store.artifacts_dir / filename
        content = store.read_artifact(filename, "")
        items.append(
            {
                "name": key,
                "file": filename,
                "path": str(path),
                "exists": path.exists(),
                "bytes": len(content.encode("utf-8")),
                "preview": content.splitlines()[:3],
            }
        )
    blocks = []
    for key, filename in CORE_MEMORY_BLOCKS.items():
        path = store.artifacts_dir / filename
        content = store.read_artifact(filename, "")
        blocks.append(
            {
                "name": key,
                "file": filename,
                "path": str(path),
                "exists": path.exists(),
                "bytes": len(content.encode("utf-8")),
                "preview": content.splitlines()[:3],
            }
        )
    return {"workspace": config.workspace, "artifacts": items, "core_memory_blocks": blocks}


def get_artifact(workspace_file: str | Path, name: str) -> dict[str, object]:
    config = load_workspace_config(workspace_file)
    store = WorkspaceStore(workspace_file)
    ensure_default_artifacts(workspace_file)
    try:
        key, filename = _resolve_artifact_name(name)
    except ValueError:
        # Allow reading raw artifact files (e.g. change-log.archive.md) by exact filename.
        if not store.artifact_exists(name):
            raise
        key, filename = name, name
    content = store.read_artifact(filename, "")
    return {
        "workspace": config.workspace,
        "name": key,
        "file": filename,
        "content": content,
    }


def _write_artifact_locked(store: WorkspaceStore, name: str, content: str) -> Path:
    """写 workspace 工件；调用方必须已持有 ``store.artifact_lock_file``。

    与 ``WorkspaceStore.write_artifact`` 的区别是它不再自行加锁，避免在已持锁的
    读-改-写事务里嵌套获取同一把锁。所有 workspace 工件写入都应经由本函数或
    ``write_artifact``，二者共用 ``artifact_lock_file``。
    """
    path = _safe_path(store.artifacts_dir, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def update_artifact(workspace_file: str | Path, name: str, content: str) -> dict[str, object]:
    config = load_workspace_config(workspace_file)
    store = WorkspaceStore(workspace_file)
    ensure_default_artifacts(workspace_file)
    key, filename = _resolve_artifact_name(name)
    # 读-改-写必须整体持 artifacts.lock：只锁写回会让并发追加都基于同一份旧内容
    # 合并，后写者静默覆盖先写者，append-only 保护形同虚设。
    with FileLock(str(store.artifact_lock_file)):
        existing = store.read_artifact(filename, "")
        next_content, mode = _merge_append_only_artifact(existing, content, key)
        path = _write_artifact_locked(store, filename, next_content)
    audit = _record_artifact_write_audit(
        store,
        scope="workspace",
        artifact_name=key,
        file_name=filename,
        write_mode=mode,
        before_bytes=len(existing.encode("utf-8")),
        after_bytes=len(next_content.encode("utf-8")),
    )
    receipt = persist_write_receipt(
        store,
        build_write_receipt(
            layer="L3_workspace_profile" if key in CORE_MEMORY_BLOCKS else "L2_task_spaces",
            action="update_artifact",
            scope="workspace",
            target=key,
            target_file=filename,
            write_mode=mode,
            audit_ref=audit,
            bytes_written=len(next_content.encode("utf-8")),
        ),
    )
    return {
        "workspace": config.workspace,
        "updated": True,
        "name": key,
        "file": filename,
        "path": str(path),
        "bytes": len(next_content.encode("utf-8")),
        "write_mode": mode,
        "audit_ref": audit,
        "write_receipt": receipt,
    }


def append_change_log(workspace_file: str | Path, entry: str) -> dict[str, object]:
    config = load_workspace_config(workspace_file)
    store = WorkspaceStore(workspace_file)
    ensure_default_artifacts(workspace_file)
    filename = DEFAULT_ARTIFACTS["change_log"]
    archive_name = "change-log.archive.md"
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    content = f"\n## {stamp}\n\n{entry.strip()}\n"
    path = _safe_path(store.artifacts_dir, filename)
    archive_path = _safe_path(store.artifacts_dir, archive_name)
    # change-log 也是 workspace 工件：必须与 update_artifact 共用 artifact_lock_file，
    # 否则两条路径用两把不同的锁，追加的条目会被并发压缩/覆盖悄悄丢掉。
    with FileLock(str(store.artifact_lock_file)):
        with path.open("a", encoding="utf-8") as f:
            f.write(content)
        raw = path.read_text(encoding="utf-8")
        prefix, entries = _split_change_log_entries(raw)
        compacted = False
        archived_count = 0
        if len(entries) > 30:
            archived_entries = entries[:-30]
            kept_entries = entries[-30:]
            archive_content = archive_path.read_text(encoding="utf-8") if archive_path.exists() else ""
            archive_prefix, archive_existing = _split_change_log_entries(archive_content)
            if not archive_prefix.strip():
                archive_prefix = "# Change Log Archive / 历史归档\n"
            merged_archive = archive_prefix.rstrip() + "\n\n" + "\n\n".join(archive_existing + archived_entries).strip() + "\n"
            archive_path.write_text(merged_archive, encoding="utf-8")
            note = "\n> Older entries were archived to `change-log.archive.md` / 较早记录已归档到 `change-log.archive.md`\n"
            path.write_text(prefix.rstrip() + note + "\n" + "\n\n".join(kept_entries).strip() + "\n", encoding="utf-8")
            compacted = True
            archived_count = len(archived_entries)
    return {
        "workspace": config.workspace,
        "appended": True,
        "name": "change_log",
        "file": filename,
        "path": str(path),
        "entry": entry.strip(),
        "compaction": {"compacted": compacted, "archived": archived_count},
    }


def artifact_outline(workspace_file: str | Path, name: str) -> dict[str, object]:
    config = load_workspace_config(workspace_file)
    content = get_artifact(workspace_file, name).get("content", "")
    sections = _split_markdown_sections(content)
    return {
        "workspace": config.workspace,
        "name": _resolve_artifact_name(name)[0],
        "sections": [
            {
                "title": item["title"],
                "level": item["level"],
                "preview": item["body"].splitlines()[:3],
                "chars": len(item["body"]),
            }
            for item in sections
        ],
    }


def artifact_context(workspace_file: str | Path, intent: str, limit: int = 6) -> dict[str, object]:
    config = load_workspace_config(workspace_file)
    store = WorkspaceStore(workspace_file)
    ensure_default_artifacts(workspace_file)
    keywords = _tokenize_text(intent)
    snippets = []
    for artifact_name in list(DEFAULT_ARTIFACTS.values()) + list(CORE_MEMORY_BLOCKS.values()) + ["change-log.archive.md"]:
        if not store.artifact_exists(artifact_name):
            continue
        content = store.read_artifact(artifact_name, "")
        for section in _split_markdown_sections(content):
            score = _section_score(section, keywords)
            if score <= 0:
                continue
            snippets.append(
                {
                    "artifact": artifact_name,
                    "title": section["title"],
                    "level": section["level"],
                    "score": score,
                    "snippet": _trim_text(section["body"], 360),
                }
            )
    snippets.sort(key=lambda item: (-int(item["score"]), item["artifact"], item["title"]))
    return {
        "workspace": config.workspace,
        "intent": intent,
        "matches": snippets[:limit],
        "summary": {
            "matched_sections": len(snippets),
            "artifacts": sorted({item["artifact"] for item in snippets[:limit]}),
        },
    }


def compact_change_log(workspace_file: str | Path, keep_recent: int = 30) -> dict[str, object]:
    config = load_workspace_config(workspace_file)
    store = WorkspaceStore(workspace_file)
    ensure_default_artifacts(workspace_file)
    filename = DEFAULT_ARTIFACTS["change_log"]
    archive_name = "change-log.archive.md"
    # 压缩是跨 live + archive 两个文件的读-改-写，必须整体持 artifact_lock_file；
    # 原先它走 store.write_artifact（同一把锁但加锁两次、中间可被插入），
    # 期间 append_change_log 追加的条目会被这次重写覆盖。
    with FileLock(str(store.artifact_lock_file)):
        content = store.read_artifact(filename, "")
        prefix, entries = _split_change_log_entries(content)
        if len(entries) <= keep_recent:
            return {
                "workspace": config.workspace,
                "compacted": False,
                "kept_recent": len(entries),
                "archived": 0,
            }
        archived_entries = entries[:-keep_recent]
        kept_entries = entries[-keep_recent:]
        archive_content = store.read_artifact(archive_name, "")
        archive_prefix, archive_existing = _split_change_log_entries(archive_content)
        if not archive_prefix.strip():
            archive_prefix = "# Change Log Archive / 历史归档\n"
        merged_archive = archive_prefix.rstrip() + "\n\n" + "\n\n".join(archive_existing + archived_entries).strip() + "\n"
        _write_artifact_locked(store, archive_name, merged_archive)
        note = "\n> Older entries were archived to `change-log.archive.md` / 较早记录已归档到 `change-log.archive.md`\n"
        compacted = prefix.rstrip() + note + "\n" + "\n\n".join(kept_entries).strip() + "\n"
        _write_artifact_locked(store, filename, compacted)
    return {
        "workspace": config.workspace,
        "compacted": True,
        "kept_recent": len(kept_entries),
        "archived": len(archived_entries),
        "archive_file": archive_name,
    }


def create_task_space(
    workspace_file: str | Path,
    title: str = "",
    intent: str = "",
    owner: str = "",
    tags: list[str] | None = None,
    priority: str = "medium",
) -> dict[str, object]:
    config = load_workspace_config(workspace_file)
    store = WorkspaceStore(workspace_file)
    task_title = (title or intent or f"task-{uuid4().hex[:8]}").strip()
    slug = _slugify_task_title(task_title)
    task_dir = store.artifacts_dir / TASKS_DIR / slug
    task_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "task_id": slug,
        "title": task_title,
        "intent": intent,
        "status": "active",
        "owner": owner.strip(),
        "tags": tags or [],
        "priority": priority.strip().lower() or "medium",
        "last_activity_source": "create_task_space",
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    }
    _write_task_meta(store, task_dir, meta)
    for key, filename in _artifact_mapping(include_task_only=True).items():
        path = task_dir / filename
        if not path.exists():
            path.write_text(_default_task_artifact_content(config.workspace, task_title, key), encoding="utf-8")
    return {
        "workspace": config.workspace,
        "created": True,
        "task_id": slug,
        "title": task_title,
        "owner": meta["owner"],
        "tags": meta["tags"],
        "priority": meta["priority"],
        "path": str(task_dir),
    }


def resolve_task_space(
    workspace_file: str | Path,
    intent: str,
    title: str = "",
    create_if_missing: bool = True,
    include_archived: bool = False,
    limit_candidates: int = 3,
    related_texts: list[str] | None = None,
    score_threshold: int = DEFAULT_RESOLVE_SCORE_THRESHOLD,
) -> dict[str, object]:
    config = load_workspace_config(workspace_file)
    candidates = list_task_spaces(workspace_file, include_archived=include_archived)
    keyword_text = title.strip() or intent.strip()
    keywords = _tokenize_text(keyword_text)
    hint_keywords: list[str] = []
    for text in related_texts or []:
        hint_keywords.extend(_tokenize_text(text))
    input_signature = _build_task_signature(
        title=title,
        intent=intent,
        related_texts=related_texts or [],
    )
    scored = []
    for task in candidates["active_tasks"] + candidates.get("archived_tasks", []):
        analysis = _task_match_analysis(workspace_file, task, keywords, hint_keywords)
        score = int(analysis["score"])
        if score <= 0:
            continue
        task_signature = _task_signature_for_existing(workspace_file, task)
        overlap = _task_signature_overlap(input_signature, task_signature)
        scored.append({**task, **analysis, "task_signature": task_signature, "signature_overlap": overlap})
    scored.sort(
        key=lambda item: (
            -int(item["score"]),
            _task_status_priority(str(item.get("status", ""))),
            _sortable_dt_value(str(item.get("updated_at", ""))),
            str(item.get("task_id", "")),
        )
    )
    candidate_rows = [
        {
            "task_id": item["task_id"],
            "title": item["title"],
            "status": item.get("status", "active"),
            "owner": item.get("owner", ""),
            "tags": item.get("tags", []),
            "priority": item.get("priority", "medium"),
            "score": item["score"],
            "match_reasons": item.get("match_reasons", {}),
            "task_signature": item.get("task_signature", {}),
            "signature_overlap": item.get("signature_overlap", {}),
            "path": item["path"],
        }
        for item in scored[: max(limit_candidates, 1)]
    ]
    if scored and int(scored[0]["score"]) >= score_threshold:
        confidence, auto_write_allowed, required_action = _task_resolution_confidence(scored, score_threshold)
        ambiguous = _is_ambiguous_task_match(scored, score_threshold)
        if ambiguous:
            return {
                "workspace": config.workspace,
                "resolved": False,
                "created": False,
                "resolution_status": "ambiguous",
                "task_id": "",
                "title": "",
                "score": int(scored[0]["score"]),
                "status": "",
                "path": "",
                "task_signature": input_signature,
                "candidates": candidate_rows,
                "score_threshold": score_threshold,
                "reason": "multiple_task_spaces_have_similar_scores",
                "resolution_confidence": confidence,
                "auto_write_allowed": False,
                "required_action": "explicit_task_id",
            }
        top = scored[0]
        if not auto_write_allowed:
            # P1-B: 低置信命中只返回候选，绝不自动绑定 task space。
            return {
                "workspace": config.workspace,
                "resolved": False,
                "created": False,
                "resolution_status": "low_confidence",
                "task_id": "",
                "title": "",
                "score": int(top["score"]),
                "status": "",
                "path": "",
                "task_signature": input_signature,
                "candidates": candidate_rows,
                "score_threshold": score_threshold,
                "reason": "top_candidate_lacks_strong_evidence",
                "resolution_confidence": confidence,
                "auto_write_allowed": False,
                "required_action": required_action or "explicit_task_id",
            }
        return {
            "workspace": config.workspace,
            "resolved": True,
            "created": False,
            "resolution_status": "exact" if int(top["score"]) >= score_threshold + 3 else "likely",
            "task_id": top["task_id"],
            "title": top["title"],
            "score": top["score"],
            "status": top.get("status", "active"),
            "owner": top.get("owner", ""),
            "tags": top.get("tags", []),
            "priority": top.get("priority", "medium"),
            "path": top["path"],
            "match_reasons": top.get("match_reasons", {}),
            "task_signature": top.get("task_signature", {}),
            "input_signature": input_signature,
            "signature_overlap": top.get("signature_overlap", {}),
            "candidates": candidate_rows,
            "score_threshold": score_threshold,
            "resolution_confidence": confidence,
            "auto_write_allowed": True,
            "required_action": "",
        }
    if not create_if_missing:
        return {
            "workspace": config.workspace,
            "resolved": False,
            "created": False,
            "resolution_status": "new",
            "task_id": "",
            "title": "",
            "score": 0,
            "status": "",
            "path": "",
            "task_signature": input_signature,
            "candidates": candidate_rows,
            "score_threshold": score_threshold,
        }
    created = create_task_space(workspace_file, title=title, intent=intent)
    return {**created, "resolved": True, "resolution_status": "new", "score": 0, "task_signature": input_signature, "candidates": candidate_rows, "score_threshold": score_threshold}


def list_task_spaces(workspace_file: str | Path, include_archived: bool = False) -> dict[str, object]:
    config = load_workspace_config(workspace_file)
    store = WorkspaceStore(workspace_file)
    active = _list_task_dir_entries(store.artifacts_dir / TASKS_DIR, archived=False)
    archived = _list_task_dir_entries(store.artifacts_dir / ARCHIVE_DIR, archived=True) if include_archived else []
    return {
        "workspace": config.workspace,
        "active_tasks": active,
        "archived_tasks": archived,
    }


def task_space_health(workspace_file: str | Path, task_id: str) -> dict[str, object]:
    config = load_workspace_config(workspace_file)
    store = WorkspaceStore(workspace_file)
    task_dir, meta = _resolve_task_dir(store, task_id)
    artifacts = _task_artifact_health_snapshot(task_dir)
    receipts = query_write_receipts(str(workspace_file), task_id=str(meta.get("task_id", "")), limit=20)
    issues: list[dict[str, object]] = []
    suggestions: list[str] = []

    _add_missing_artifact_issues(artifacts, issues, suggestions)
    _add_current_summary_health(meta, artifacts, issues, suggestions)
    _add_actionability_health(meta, artifacts, receipts, issues, suggestions)
    _add_size_balance_health(artifacts, issues, suggestions)
    similar_tasks = _similar_task_candidates(workspace_file, meta, limit=5)
    if similar_tasks:
        issues.append(
            {
                "code": "similar_task_spaces",
                "severity": "warning",
                "message": "存在相似任务空间，后续自然语言匹配可能出现 ambiguous。",
                "evidence": similar_tasks,
            }
        )
        suggestions.append("合并、重命名或归档相似 task space，降低后续 resolve-task 歧义。")

    score = _task_health_score(issues)
    health = _health_label(score, issues)
    return {
        "workspace": config.workspace,
        "task_id": meta.get("task_id", task_id),
        "title": meta.get("title", ""),
        "status": meta.get("status", ""),
        "health": health,
        "score": score,
        "issues": issues,
        "repair_suggestions": _dedupe_preserve_order(suggestions),
        "artifact_summary": artifacts,
        "write_receipts": {
            "count": len(receipts.get("receipts", [])),
            "latest": receipts.get("receipts", [])[-3:],
            "summary": receipts.get("summary", {}),
        },
    }


def task_spaces_health(workspace_file: str | Path, include_archived: bool = False, limit: int = 50) -> dict[str, object]:
    config = load_workspace_config(workspace_file)
    listed = list_task_spaces(workspace_file, include_archived=include_archived)
    tasks = [*listed.get("active_tasks", []), *listed.get("archived_tasks", [])]
    results = [task_space_health(workspace_file, str(task.get("task_id", ""))) for task in tasks[: max(limit, 0)]]
    health_counts: dict[str, int] = {}
    for item in results:
        label = str(item.get("health", "unknown"))
        health_counts[label] = health_counts.get(label, 0) + 1
    results.sort(key=lambda item: (int(item.get("score", 0)), str(item.get("task_id", ""))))
    return {
        "workspace": config.workspace,
        "include_archived": include_archived,
        "checked": len(results),
        "total_tasks": len(tasks),
        "health_counts": health_counts,
        "tasks": results,
        "top_issues": _summarize_task_health_issues(results),
    }


def task_space_repair_plan(workspace_file: str | Path, task_id: str) -> dict[str, object]:
    health = task_space_health(workspace_file, task_id)
    plan: list[dict[str, object]] = []
    for issue in health.get("issues", []) if isinstance(health.get("issues", []), list) else []:
        plan.extend(_repair_actions_for_issue(issue, health))
    plan = _dedupe_repair_plan(plan)
    safe_to_auto_apply = bool(plan) and all(bool(item.get("safe_to_auto_apply")) for item in plan)
    return {
        "workspace": health.get("workspace", ""),
        "task_id": health.get("task_id", task_id),
        "title": health.get("title", ""),
        "health": health.get("health", ""),
        "score": health.get("score", 0),
        "safe_to_auto_apply": safe_to_auto_apply,
        "apply_supported": False,
        "reason": "repair_plan_is_read_only",
        "repair_plan": plan,
        "issue_count": len(health.get("issues", []) if isinstance(health.get("issues", []), list) else []),
        "source_health": {
            "issues": health.get("issues", []),
            "repair_suggestions": health.get("repair_suggestions", []),
        },
    }


def task_space_repair_execute(
    workspace_file: str | Path,
    task_id: str,
    *,
    apply: bool = False,
    intent: str = "",
    sync_sniff: Callable[[str | Path, str, str], dict[str, object]] | None = None,
) -> dict[str, object]:
    plan = task_space_repair_plan(workspace_file, task_id)
    steps = plan.get("repair_plan", []) if isinstance(plan.get("repair_plan", []), list) else []
    executions = [_build_repair_execution_step(workspace_file, str(plan.get("task_id", task_id)), step, intent=intent) for step in steps]
    if not apply:
        return {
            "workspace": plan.get("workspace", ""),
            "task_id": plan.get("task_id", task_id),
            "dry_run": True,
            "applied": False,
            "intent_required": any(bool(item.get("requires_intent")) for item in executions),
            "supported_count": sum(1 for item in executions if item.get("supported")),
            "skipped_count": sum(1 for item in executions if not item.get("supported")),
            "execution_plan": executions,
            "source_repair_plan": plan,
        }
    results = []
    for item in executions:
        if not item.get("supported"):
            results.append({**item, "applied": False, "status": "skipped"})
            continue
        if item.get("requires_intent") and not intent.strip():
            results.append({**item, "applied": False, "status": "blocked", "reason": "intent_required"})
            continue
        results.append(_apply_repair_execution_step(workspace_file, str(plan.get("task_id", task_id)), item, intent=intent, sync_sniff=sync_sniff))
    after_health = task_space_health(workspace_file, str(plan.get("task_id", task_id)))
    return {
        "workspace": plan.get("workspace", ""),
        "task_id": plan.get("task_id", task_id),
        "dry_run": False,
        "applied": any(bool(item.get("applied")) for item in results),
        "executed_count": sum(1 for item in results if item.get("applied")),
        "blocked_count": sum(1 for item in results if item.get("status") == "blocked"),
        "skipped_count": sum(1 for item in results if item.get("status") == "skipped"),
        "results": results,
        "remaining_health": {
            "health": after_health.get("health", ""),
            "score": after_health.get("score", 0),
            "issue_count": len(after_health.get("issues", []) if isinstance(after_health.get("issues", []), list) else []),
            "top_issues": [
                {"code": issue.get("code", ""), "severity": issue.get("severity", "")}
                for issue in (after_health.get("issues", []) if isinstance(after_health.get("issues", []), list) else [])[:5]
            ],
        },
    }


def update_task_status(workspace_file: str | Path, task_id: str, status: str, source: str = "update_task_status") -> dict[str, object]:
    config = load_workspace_config(workspace_file)
    store = WorkspaceStore(workspace_file)
    normalized = status.strip().lower()
    if normalized not in TASK_STATUSES:
        raise ValueError(f"unknown task status: {status}")
    if normalized == "archived":
        return archive_task_space(workspace_file, task_id, reason="status=archived")
    task_dir, meta = _resolve_task_dir(store, task_id)
    before_meta = dict(meta)
    meta["status"] = normalized
    meta["archived"] = False
    _touch_task_meta(store, task_dir, meta, source=source)
    audit = _record_artifact_write_audit(
        store,
        scope="task_space",
        artifact_name="task_status",
        file_name="meta.json",
        write_mode="replace",
        before_bytes=len(json.dumps(before_meta, ensure_ascii=False).encode("utf-8")),
        after_bytes=len(json.dumps(meta, ensure_ascii=False).encode("utf-8")),
        task_id=meta["task_id"],
        source=source,
    )
    receipt = persist_write_receipt(
        store,
        build_write_receipt(
            layer="L2_task_spaces",
            action=source,
            scope="task_space",
            target="task_status",
            target_file="meta.json",
            write_mode="replace",
            audit_ref=audit,
            task_id=meta["task_id"],
            bytes_written=len(json.dumps(meta, ensure_ascii=False).encode("utf-8")),
        ),
    )
    return {
        "workspace": config.workspace,
        "updated": True,
        "task_id": meta["task_id"],
        "title": meta["title"],
        "status": normalized,
        "path": str(task_dir),
        "write_receipt": receipt,
    }


def get_task_artifact(
    workspace_file: str | Path,
    task_id: str,
    name: str,
    *,
    max_bytes: int | None = None,
) -> dict[str, object]:
    config = load_workspace_config(workspace_file)
    store = WorkspaceStore(workspace_file)
    task_dir, meta = _resolve_task_dir(store, task_id)
    key, filename = _resolve_artifact_name(name, include_task_only=True)
    path = task_dir / filename
    total_bytes = path.stat().st_size if path.exists() else 0
    truncated = bool(max_bytes is not None and total_bytes > max_bytes)
    if not path.exists():
        content = ""
    elif truncated:
        with path.open("rb") as handle:
            content = handle.read(max(0, max_bytes or 0)).decode("utf-8", errors="replace")
    else:
        content = path.read_text(encoding="utf-8")
    return {
        "workspace": config.workspace,
        "task_id": meta["task_id"],
        "title": meta["title"],
        "name": key,
        "file": filename,
        "content": content,
        "total_bytes": total_bytes,
        "truncated": truncated,
        "archived": bool(meta.get("archived", False)),
    }


def update_task_artifact(workspace_file: str | Path, task_id: str, name: str, content: str, source: str = "update_task_artifact") -> dict[str, object]:
    config = load_workspace_config(workspace_file)
    store = WorkspaceStore(workspace_file)
    task_dir, meta = _resolve_task_dir(store, task_id)
    key, filename = _resolve_artifact_name(name, include_task_only=True)
    path = task_dir / filename
    evidence = None
    if len(content.encode("utf-8")) > TASK_EVIDENCE_INLINE_MAX_BYTES:
        evidence = write_task_evidence_chunk(workspace_file, task_id, content, source=source)
        content = (
            "## Evidence Reference / 证据引用\n\n"
            f"Large evidence was stored by content hash: `{evidence['ref']}`. "
            "Use task evidence retrieval when full detail is needed.\n"
        )
    # 尺寸判断、读取、合并、写回必须整体持 store.lock_file：原先只有写回加锁，
    # 两个并发 append 会各自基于同一份旧内容合并，后写者覆盖先写者，且双方都返回 updated=True。
    with FileLock(str(store.lock_file)):
        existing_bytes = path.stat().st_size if path.exists() else 0
        if existing_bytes > TASK_ARTIFACT_WRITE_MAX_BYTES:
            return {
                "workspace": config.workspace,
                "updated": False,
                "reason": "artifact_too_large_for_merge",
                "task_id": meta["task_id"],
                "title": meta["title"],
                "name": key,
                "file": filename,
                "path": str(path),
                "existing_bytes": existing_bytes,
                "max_merge_bytes": TASK_ARTIFACT_WRITE_MAX_BYTES,
                "recommended_action": "archive_or_split_artifact_then_retry; keep a concise current_summary",
            }
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        next_content, mode = _merge_append_only_artifact(existing, content, key)
        path.write_text(next_content, encoding="utf-8")
    _touch_task_meta(store, task_dir, meta, source=source)
    audit = _record_artifact_write_audit(
        store,
        scope="task_space",
        artifact_name=key,
        file_name=filename,
        write_mode=mode,
        before_bytes=len(existing.encode("utf-8")),
        after_bytes=len(next_content.encode("utf-8")),
        task_id=meta["task_id"],
        source=source,
    )
    receipt = persist_write_receipt(
        store,
        build_write_receipt(
            layer="L2_task_spaces",
            action=source,
            scope="task_space",
            target=key,
            target_file=filename,
            task_id=meta["task_id"],
            write_mode=mode,
            audit_ref=audit,
            bytes_written=len(next_content.encode("utf-8")),
        ),
    )
    return {
        "workspace": config.workspace,
        "updated": True,
        "task_id": meta["task_id"],
        "title": meta["title"],
        "name": key,
        "file": filename,
        "path": str(path),
        "write_mode": mode,
        "audit_ref": audit,
        "write_receipt": receipt,
        "evidence": evidence,
    }


def write_task_evidence_chunk(
    workspace_file: str | Path,
    task_id: str,
    content: str,
    *,
    source: str = "evidence",
) -> dict[str, object]:
    """Store immutable task evidence by content hash and return a stable ref."""
    store = WorkspaceStore(workspace_file)
    task_dir, meta = _resolve_task_dir(store, task_id)
    payload = content.encode("utf-8")
    digest = sha256(payload).hexdigest()
    relative = f"evidence/{digest}.md"
    path = task_dir / relative
    with FileLock(str(store.lock_file)):
        existed = path.exists()
        if not existed:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
    return {
        "task_id": meta["task_id"],
        "ref": f"evidence:{digest}",
        "hash": digest,
        "file": relative,
        "path": str(path),
        "bytes": len(payload),
        "source": source,
        "deduplicated": existed,
    }


def get_task_evidence_chunk(workspace_file: str | Path, task_id: str, ref: str, *, max_bytes: int = TASK_ARTIFACT_EXCERPT_BYTES) -> dict[str, object]:
    """Read a bounded evidence excerpt; callers can request a larger bound explicitly."""
    store = WorkspaceStore(workspace_file)
    task_dir, meta = _resolve_task_dir(store, task_id)
    digest = ref.removeprefix("evidence:").strip()
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("Invalid evidence reference")
    path = task_dir / "evidence" / f"{digest}.md"
    total_bytes = path.stat().st_size if path.exists() else 0
    if not path.exists():
        return {"task_id": meta["task_id"], "ref": f"evidence:{digest}", "found": False, "content": ""}
    with path.open("rb") as handle:
        content = handle.read(max(0, max_bytes)).decode("utf-8", errors="replace")
    return {"task_id": meta["task_id"], "ref": f"evidence:{digest}", "found": True, "content": content, "total_bytes": total_bytes, "truncated": total_bytes > max_bytes}


def record_task_decision(
    workspace_file: str | Path,
    task_id: str,
    topic: str,
    decision: str,
    rationale: str,
    *,
    evidence_refs: list[str] | None = None,
    status: str = "accepted",
) -> dict[str, object]:
    """Persist a task-scoped ADR linked to immutable evidence where available."""
    store = WorkspaceStore(workspace_file)
    task_dir, meta = _resolve_task_dir(store, task_id)
    entry = {
        "decision_id": f"dec-{uuid4().hex[:12]}",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "topic": topic.strip(),
        "decision": decision.strip(),
        "rationale": rationale.strip(),
        "evidence_refs": [ref for ref in (evidence_refs or []) if ref.startswith("evidence:")][:20],
        "status": status if status in {"proposed", "accepted", "superseded"} else "accepted",
    }
    path = task_dir / TASK_DECISIONS_FILE
    with FileLock(str(store.lock_file)):
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    _touch_task_meta(store, task_dir, meta, source="record_task_decision")
    return {"task_id": meta["task_id"], "recorded": True, **entry}


def list_task_decisions(workspace_file: str | Path, task_id: str, limit: int = 30) -> dict[str, object]:
    store = WorkspaceStore(workspace_file)
    task_dir, meta = _resolve_task_dir(store, task_id)
    path = task_dir / TASK_DECISIONS_FILE
    rows: list[dict[str, Any]] = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines()[-max(1, limit):]:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return {"task_id": meta["task_id"], "decisions": rows, "total": len(rows)}


_EVIDENCE_REFERENCE_SUFFIXES = {".md", ".jsonl", ".json"}


def task_evidence_gc(workspace_file: str | Path, task_id: str, *, apply: bool = False) -> dict[str, object]:
    """Report or remove unreferenced evidence chunks; deletion is opt-in.

    引用扫描覆盖 ``.md`` 与 ``.jsonl``/``.json``：``record_task_decision`` 会把
    ``evidence_refs`` 写进 ``decisions.jsonl``，只扫 markdown 会把仅被决策引用的
    证据误判为无引用并在 ``apply=True`` 时删除。
    """
    store = WorkspaceStore(workspace_file)
    task_dir, meta = _resolve_task_dir(store, task_id)
    evidence_dir = task_dir / "evidence"
    references: set[str] = set()
    for source in task_dir.rglob("*"):
        if not source.is_file() or source.suffix not in _EVIDENCE_REFERENCE_SUFFIXES:
            continue
        try:
            references.update(re.findall(r"evidence:([0-9a-f]{64})", source.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError):
            continue
    candidates = [path for path in evidence_dir.glob("*.md") if path.stem not in references] if evidence_dir.exists() else []
    if apply:
        with FileLock(str(store.lock_file)):
            for path in candidates:
                path.unlink(missing_ok=True)
    return {"task_id": meta["task_id"], "apply": apply, "referenced": len(references), "candidates": [path.name for path in candidates], "removed": len(candidates) if apply else 0}


def update_task_current_summary_snapshot(
    workspace_file: str | Path,
    task_id: str,
    content: str,
    source: str = "update_task_current_summary_snapshot",
) -> dict[str, object]:
    """Replace current-summary.md while preserving the previous snapshot in summary-history.md."""
    config = load_workspace_config(workspace_file)
    store = WorkspaceStore(workspace_file)
    task_dir, meta = _resolve_task_dir(store, task_id)
    filename = TASK_ONLY_ARTIFACTS["current_summary"]
    history_filename = TASK_ONLY_ARTIFACTS["summary_history"]
    path = task_dir / filename
    history_path = task_dir / history_filename
    existing_bytes = path.stat().st_size if path.exists() else 0
    history_skipped = existing_bytes > TASK_ARTIFACT_WRITE_MAX_BYTES
    existing = "" if history_skipped or not path.exists() else path.read_text(encoding="utf-8")
    next_content = content.strip() + "\n" if content.strip() else ""
    stamp = datetime.now(timezone.utc).isoformat()
    with FileLock(str(store.lock_file)):
        if existing.strip():
            history_bytes = history_path.stat().st_size if history_path.exists() else 0
            previous_history = (
                "# Summary History / 摘要历史\n"
                if history_bytes > TASK_ARTIFACT_WRITE_MAX_BYTES
                else (history_path.read_text(encoding="utf-8") if history_path.exists() else "# Summary History / 摘要历史\n")
            )
            history_entry = f"\n## {stamp} / {source}\n\n{existing.strip()}\n"
            history_path.write_text(previous_history.rstrip() + "\n" + history_entry, encoding="utf-8")
        path.write_text(next_content, encoding="utf-8")
    _touch_task_meta(store, task_dir, meta, source=source)
    audit = _record_artifact_write_audit(
        store,
        scope="task_space",
        artifact_name="current_summary",
        file_name=filename,
        write_mode="replace_snapshot",
        before_bytes=existing_bytes,
        after_bytes=len(next_content.encode("utf-8")),
        task_id=meta["task_id"],
        source=source,
    )
    receipt = persist_write_receipt(
        store,
        build_write_receipt(
            layer="L2_task_spaces",
            action=source,
            scope="task_space",
            target="current_summary",
            target_file=filename,
            task_id=meta["task_id"],
            write_mode="replace_snapshot",
            audit_ref=audit,
            bytes_written=len(next_content.encode("utf-8")),
        ),
    )
    return {
        "workspace": config.workspace,
        "updated": True,
        "task_id": meta["task_id"],
        "title": meta["title"],
        "name": "current_summary",
        "file": filename,
        "path": str(path),
        "history_file": history_filename,
        "write_mode": "replace_snapshot",
        "history_skipped": history_skipped,
        "audit_ref": audit,
        "write_receipt": receipt,
    }


def append_task_change_log(workspace_file: str | Path, task_id: str, entry: str, keep_recent: int = 30, source: str = "append_task_change_log") -> dict[str, object]:
    config = load_workspace_config(workspace_file)
    store = WorkspaceStore(workspace_file)
    task_dir, meta = _resolve_task_dir(store, task_id)
    filename = DEFAULT_ARTIFACTS["change_log"]
    path = task_dir / filename
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    content = f"\n## {stamp}\n\n{entry.strip()}\n"
    with FileLock(str(store.lock_file)):
        with path.open("a", encoding="utf-8") as f:
            f.write(content)
    _touch_task_meta(store, task_dir, meta, source=source)
    compact = compact_task_change_log(workspace_file, task_id, keep_recent=keep_recent)
    return {
        "workspace": config.workspace,
        "appended": True,
        "task_id": meta["task_id"],
        "entry": entry.strip(),
        "compaction": compact,
    }


def compact_task_change_log(workspace_file: str | Path, task_id: str, keep_recent: int = 30) -> dict[str, object]:
    config = load_workspace_config(workspace_file)
    store = WorkspaceStore(workspace_file)
    task_dir, meta = _resolve_task_dir(store, task_id)
    path = task_dir / DEFAULT_ARTIFACTS["change_log"]
    archive_path = task_dir / "change-log.archive.md"
    existing_bytes = path.stat().st_size if path.exists() else 0
    if existing_bytes > TASK_ARTIFACT_WRITE_MAX_BYTES:
        return {
            "workspace": config.workspace,
            "task_id": meta["task_id"],
            "compacted": False,
            "skipped": "artifact_too_large_for_compaction",
            "existing_bytes": existing_bytes,
            "max_compaction_bytes": TASK_ARTIFACT_WRITE_MAX_BYTES,
        }
    content = path.read_text(encoding="utf-8") if path.exists() else ""
    prefix, entries = _split_change_log_entries(content)
    if len(entries) <= keep_recent:
        return {"workspace": config.workspace, "task_id": meta["task_id"], "compacted": False, "kept_recent": len(entries), "archived": 0}
    archived_entries = entries[:-keep_recent]
    kept_entries = entries[-keep_recent:]
    archive_content = archive_path.read_text(encoding="utf-8") if archive_path.exists() else "# Change Log Archive / 历史归档\n"
    archive_prefix, archive_existing = _split_change_log_entries(archive_content)
    merged_archive = archive_prefix.rstrip() + "\n\n" + "\n\n".join(archive_existing + archived_entries).strip() + "\n"
    with FileLock(str(store.lock_file)):
        archive_path.write_text(merged_archive, encoding="utf-8")
        note = "\n> Older task entries were archived to `change-log.archive.md` / 较早任务记录已归档到 `change-log.archive.md`\n"
        path.write_text(prefix.rstrip() + note + "\n" + "\n\n".join(kept_entries).strip() + "\n", encoding="utf-8")
    _touch_task_meta(store, task_dir, meta)
    return {"workspace": config.workspace, "task_id": meta["task_id"], "compacted": True, "kept_recent": len(kept_entries), "archived": len(archived_entries)}


def _preserve_conflicting_archive(store: WorkspaceStore, target: Path) -> Path:
    """把已存在的同名归档整体移到 superseded 备份目录，绝不删除已有归档内容。

    ``task_id`` 是标题 slug，同名任务重建后归档路径会再次指向 ``<slug>``；此前
    这里直接 ``rmtree`` 掉了旧归档，等于静默销毁历史任务空间。旧归档现在整体
    移到 ``archive/superseded/tasks/<slug>-<stamp>[-N]``，并在 meta 里标注原因。
    """
    meta = _read_task_meta(target)
    stamp = re.sub(r"[^0-9A-Za-z]+", "", str(meta.get("archived_at") or meta.get("created_at") or ""))[:15] or "legacy"
    backup_root = _safe_path(store.artifacts_dir, ARCHIVE_SUPERSEDED_DIR)
    backup_root.mkdir(parents=True, exist_ok=True)
    backup = backup_root / f"{target.name}-{stamp}"
    index = 2
    while backup.exists():
        backup = backup_root / f"{target.name}-{stamp}-{index}"
        index += 1
    shutil.move(str(target), str(backup))
    backup_meta = dict(meta)
    backup_meta["superseded_at"] = datetime.now(timezone.utc).isoformat()
    backup_meta["superseded_reason"] = "archive_slug_collision"
    _write_task_meta_unlocked(backup, backup_meta)
    return backup


def archive_task_space(workspace_file: str | Path, task_id: str, reason: str = "") -> dict[str, object]:
    config = load_workspace_config(workspace_file)
    store = WorkspaceStore(workspace_file)
    task_dir, meta = _resolve_task_dir(store, task_id)
    archive_root = store.artifacts_dir / ARCHIVE_DIR
    archive_root.mkdir(parents=True, exist_ok=True)
    target = archive_root / task_dir.name
    preserved: list[dict[str, str]] = []
    with FileLock(str(store.lock_file)):
        if target.exists():
            # 同名归档已存在：保留旧归档（移到 superseded/），再把当前任务放到
            # canonical 路径。直接 shutil.move 到已存在目录会把源目录嵌套进去，
            # 所以必须先移走旧归档。
            preserved.append({"task_id": task_dir.name, "path": str(_preserve_conflicting_archive(store, target))})
        shutil.move(str(task_dir), str(target))
        meta["status"] = "archived"
        meta["archived"] = True
        meta["archived_at"] = datetime.now().isoformat()
        if reason:
            meta["archive_reason"] = reason
        _write_task_meta_unlocked(target, meta)
    return {
        "workspace": config.workspace,
        "archived": True,
        "task_id": meta["task_id"],
        "title": meta["title"],
        "path": str(target),
        # 仅在同名归档冲突时非空：被保留的旧归档位置，便于人工追溯。
        "preserved_archives": preserved,
    }


def auto_archive_task_spaces(workspace_file: str | Path, retention_days: int = 30) -> dict[str, object]:
    config = load_workspace_config(workspace_file)
    store = WorkspaceStore(workspace_file)
    now = datetime.now(timezone.utc)
    archived_items = []
    for item in _list_task_dir_entries(store.artifacts_dir / TASKS_DIR, archived=False):
        updated_at = _parse_dt(item.get("updated_at", "")) or _parse_dt(item.get("created_at", ""))
        if not updated_at:
            continue
        age_days = (now - updated_at).days
        if age_days < retention_days:
            continue
        archived_items.append(archive_task_space(workspace_file, item["task_id"], reason=f"retention_days={retention_days}"))
    return {
        "workspace": config.workspace,
        "retention_days": retention_days,
        "archived_count": len(archived_items),
        "archived_tasks": archived_items,
    }


def compact_task_artifacts(workspace_file: str | Path, task_id: str, *, threshold_bytes: int = TASK_ARTIFACT_COMPACT_THRESHOLD_BYTES, keep_bytes: int = TASK_ARTIFACT_COMPACT_KEEP_BYTES) -> dict[str, object]:
    """Gzip oversized task artifacts and retain a bounded live tail for agents."""
    store = WorkspaceStore(workspace_file)
    task_dir, meta = _resolve_task_dir(store, task_id)
    archive_dir = task_dir / "archives"
    compacted: list[dict[str, object]] = []
    for key, filename in _artifact_mapping(include_task_only=True).items():
        path = task_dir / filename
        if not path.exists() or path.stat().st_size <= threshold_bytes:
            continue
        before_bytes = path.stat().st_size
        archive_dir.mkdir(parents=True, exist_ok=True)
        archive = archive_dir / f"{filename}.{int(path.stat().st_mtime)}.gz"
        with path.open("rb") as source, gzip.open(archive, "wb", compresslevel=6) as target:
            shutil.copyfileobj(source, target, length=1024 * 1024)
        with path.open("rb") as source:
            source.seek(max(0, path.stat().st_size - keep_bytes))
            tail = source.read().decode("utf-8", errors="replace")
        compact = (
            f"# {key} / 已压缩任务工件\n\n"
            f"> 原文件 `{filename}` 过大，已压缩归档到 `archives/{archive.name}`；保留以下最近 {keep_bytes} 字节供 Agent 恢复上下文。\n\n"
            f"{tail.lstrip()}"
        )
        temp = path.with_name(f".{path.name}.compact")
        temp.write_text(compact, encoding="utf-8")
        os.replace(temp, path)
        compacted.append({"name": key, "file": filename, "before_bytes": before_bytes, "archive_bytes": archive.stat().st_size, "archive": str(archive.relative_to(task_dir)), "after_bytes": path.stat().st_size})
    _touch_task_meta(store, task_dir, meta, source="compact_task_artifacts")
    return {"task_id": meta["task_id"], "compacted": compacted, "threshold_bytes": threshold_bytes, "keep_bytes": keep_bytes}


def _resolve_artifact_name(name: str, include_task_only: bool = False) -> tuple[str, str]:
    normalized = name.strip().lower().replace("-", "_")
    mapping = _artifact_mapping(include_task_only=include_task_only)
    if normalized in mapping:
        return normalized, mapping[normalized]
    for key, filename in mapping.items():
        if normalized == filename.lower().replace("-", "_").replace(".md", ""):
            return key, filename
        if normalized == filename.lower():
            return key, filename
    raise ValueError(f"unknown artifact: {name}")


def _artifact_mapping(include_task_only: bool = False) -> dict[str, str]:
    if include_task_only:
        return {**DEFAULT_ARTIFACTS, **TASK_ONLY_ARTIFACTS}
    return {**DEFAULT_ARTIFACTS, **CORE_MEMORY_BLOCKS}


def _merge_append_only_artifact(existing: str, incoming: str, artifact_key: str) -> tuple[str, str]:
    if artifact_key not in APPEND_ONLY_ARTIFACT_KEYS:
        return incoming, "replace"
    if not existing.strip():
        return incoming, "initial_write"
    if incoming.startswith(existing):
        return incoming, "append_full_document"
    addition = incoming.strip()
    if not addition:
        return existing, "noop"
    if f"\n{addition}\n" in f"\n{existing}\n":
        return existing, "deduplicated_noop"
    separator = "\n\n" if existing.strip() and not existing.endswith("\n\n") else ""
    return existing.rstrip() + separator + addition + ("\n" if not addition.endswith("\n") else ""), "append_guarded"


def _record_artifact_write_audit(
    store: WorkspaceStore,
    scope: str,
    artifact_name: str,
    file_name: str,
    write_mode: str,
    before_bytes: int,
    after_bytes: int,
    task_id: str = "",
    source: str = "",
) -> str:
    item = {
        "scope": scope,
        "artifact_name": artifact_name,
        "file_name": file_name,
        "task_id": task_id,
        "source": source,
        "write_mode": write_mode,
        "before_bytes": before_bytes,
        "after_bytes": after_bytes,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    store.append_jsonl(ARTIFACT_WRITE_AUDIT_FILE, item)
    created_at = item.get("created_at", "")
    return f"memory/{ARTIFACT_WRITE_AUDIT_FILE}#{created_at}" if created_at else f"memory/{ARTIFACT_WRITE_AUDIT_FILE}"


def _default_artifact_content(workspace_name: str, artifact_name: str) -> str:
    title_map = {
        "context": "Context / 背景与上下文",
        "requirement": "Requirement / 需求与约束",
        "design": "Design / 设计方案",
        "plan": "Plan / 开发计划",
        "test_plan": "Test Plan / 测试策略",
        "change_log": "Change Log / 变更记录",
        "current_summary": "Current Summary / 当前最短上下文",
        "summary_history": "Summary History / 摘要历史",
    }
    title = title_map[artifact_name]
    return (
        f"# {title}\n\n"
        f"- Workspace: {workspace_name}\n"
        f"- Last updated: TBD\n\n"
        f"## Notes\n\n"
        f"- Fill this artifact collaboratively.\n"
        f"- 由多个 Agent/开发者共享维护。\n"
    )


def _default_task_artifact_content(workspace_name: str, task_title: str, artifact_name: str) -> str:
    content = _default_artifact_content(workspace_name, artifact_name)
    return content + f"\n## Task\n\n- Title: {task_title}\n"


def _default_core_memory_block_content(workspace_name: str, block_name: str) -> str:
    title_map = {
        "workspace_profile": "Workspace Profile / 工作区画像",
        "team_rules": "Team Rules / 团队规则块",
        "architecture_invariants": "Architecture Invariants / 架构不变量",
        "active_migration_policy": "Active Migration Policy / 当前迁移策略",
    }
    content_map = {
        "workspace_profile": [
            "- Fill the dominant business domains and critical systems in this workspace.",
            "- 补充这个 workspace 的核心业务域、关键系统与主要风险风格。",
        ],
        "team_rules": [
            "- Keep stable cross-task rules here instead of burying them in one case.",
            "- 把跨任务稳定生效的团队规则沉淀在这里。",
        ],
        "architecture_invariants": [
            "- Record truths that should remain valid across refactors and migrations.",
            "- 记录跨重构、跨迁移都应保持成立的架构事实。",
        ],
        "active_migration_policy": [
            "- Record temporary but currently active compatibility / migration policy.",
            "- 记录当前仍在生效的兼容期、迁移期、灰度期策略。",
        ],
    }
    body = "\n".join(content_map.get(block_name, ["- Fill this memory block collaboratively."]))
    return (
        f"# {title_map.get(block_name, block_name)}\n\n"
        f"- Workspace: {workspace_name}\n"
        "- Memory layer: L3_workspace_profile\n"
        "- Last updated: TBD\n\n"
        "## Notes\n\n"
        "- Core memory blocks should stay stable and reusable.\n"
        "- 核心记忆块适合沉淀稳定、长期有效、跨任务可复用的信息。\n\n"
        "## Content\n\n"
        f"{body}\n"
    )


def _task_artifact_health_snapshot(task_dir: Path) -> dict[str, object]:
    summary: dict[str, object] = {}
    mapping = _artifact_mapping(include_task_only=True)
    for name in TASK_HEALTH_ARTIFACTS:
        filename = mapping.get(name, "")
        path = task_dir / filename
        total_bytes = path.stat().st_size if path.exists() else 0
        truncated = total_bytes > TASK_ARTIFACT_HEALTH_EXCERPT_BYTES
        if not path.exists():
            content = ""
        elif truncated:
            with path.open("rb") as handle:
                content = handle.read(TASK_ARTIFACT_HEALTH_EXCERPT_BYTES).decode("utf-8", errors="replace")
        else:
            content = path.read_text(encoding="utf-8")
        body = _artifact_body_without_boilerplate(content)
        summary[name] = {
            "file": filename,
            "exists": path.exists(),
            "chars": len(content),
            "bytes": total_bytes,
            "truncated": truncated,
            "body_chars": len(body),
            "placeholder": _is_placeholder_artifact(content),
            "section_count": len(_split_markdown_sections(content)),
            "preview": content.splitlines()[:3],
        }
    return summary


def _add_missing_artifact_issues(artifacts: dict[str, object], issues: list[dict[str, object]], suggestions: list[str]) -> None:
    required = ["current_summary", "context", "plan"]
    for name in required:
        info = artifacts.get(name, {}) if isinstance(artifacts.get(name), dict) else {}
        if not info.get("exists"):
            issues.append(
                {
                    "code": f"missing_{name}",
                    "severity": "error",
                    "message": f"{name} 文件缺失，恢复链路会丢失关键上下文。",
                }
            )
            suggestions.append(f"运行 sync-sniff-artifacts 或 update-task 补齐 {name}。")
            continue
        if bool(info.get("truncated")):
            issues.append(
                {
                    "code": f"oversized_{name}",
                    "severity": "warning",
                    "message": f"{name} 体积过大，自动任务匹配和同步将只读取摘要并跳过原文件合并。",
                    "evidence": {"bytes": int(info.get("bytes", 0)), "excerpt_bytes": TASK_ARTIFACT_HEALTH_EXCERPT_BYTES},
                }
            )
            suggestions.append(f"拆分或归档 {name}，将可恢复摘要保留在 current_summary。")
        if bool(info.get("placeholder")) or int(info.get("body_chars", 0)) <= 20:
            issues.append(
                {
                    "code": f"empty_{name}",
                    "severity": "warning",
                    "message": f"{name} 仍接近初始化占位，信息量不足。",
                }
            )
            suggestions.append(f"补写 {name}，优先保留目标、证据、下一步。")


def _add_current_summary_health(
    meta: dict[str, object],
    artifacts: dict[str, object],
    issues: list[dict[str, object]],
    suggestions: list[str],
) -> None:
    info = artifacts.get("current_summary", {}) if isinstance(artifacts.get("current_summary"), dict) else {}
    chars = int(info.get("chars", 0))
    if chars > 2500:
        issues.append(
            {
                "code": "oversized_current_summary",
                "severity": "warning",
                "message": "current_summary 过长，不适合作为接手时的最短上下文。",
                "evidence": {"chars": chars, "limit": 2500},
            }
        )
        suggestions.append("用 sync-sniff-artifacts 或快照更新把 current_summary 压缩到目标、已做、下一步、风险。")
    stale_days = _days_since_iso(str(meta.get("updated_at", "") or ""))
    if stale_days is not None and stale_days >= 14 and str(meta.get("status", "")) not in {"done", "archived"}:
        issues.append(
            {
                "code": "stale_task_space",
                "severity": "warning",
                "message": f"任务空间已 {stale_days} 天未更新，恢复前需要确认上下文是否仍有效。",
                "evidence": {"updated_at": meta.get("updated_at", ""), "stale_days": stale_days},
            }
        )
        suggestions.append("恢复前先运行 resume-packet，再根据当前意图刷新 current_summary。")


def _add_actionability_health(
    meta: dict[str, object],
    artifacts: dict[str, object],
    receipts: dict[str, object],
    issues: list[dict[str, object]],
    suggestions: list[str],
) -> None:
    summary = artifacts.get("current_summary", {}) if isinstance(artifacts.get("current_summary"), dict) else {}
    plan = artifacts.get("plan", {}) if isinstance(artifacts.get("plan"), dict) else {}
    text = "\n".join(
        [
            " ".join(str(item) for item in summary.get("preview", [])) if isinstance(summary.get("preview", []), list) else "",
            " ".join(str(item) for item in plan.get("preview", [])) if isinstance(plan.get("preview", []), list) else "",
        ]
    ).lower()
    action_terms = ["next", "todo", "action", "verify", "验证", "下一步", "待办", "检查", "修复", "确认"]
    if not any(term in text for term in action_terms) and int(plan.get("body_chars", 0)) < 160:
        issues.append(
            {
                "code": "weak_next_actions",
                "severity": "warning",
                "message": "任务空间缺少明确下一步，接手者需要重新推断工作方向。",
            }
        )
        suggestions.append("在 plan 或 current_summary 中补充 1-3 条 next actions。")
    if str(meta.get("status", "")) == "blocked" and "blocked" not in text and "阻塞" not in text:
        issues.append(
            {
                "code": "blocked_without_reason",
                "severity": "error",
                "message": "任务状态为 blocked，但当前摘要/计划没有说明阻塞原因。",
            }
        )
        suggestions.append("补充 blocked 原因、等待对象和解除阻塞后的第一步。")
    if not receipts.get("receipts"):
        issues.append(
            {
                "code": "missing_write_receipts",
                "severity": "warning",
                "message": "该任务没有写入凭证，难以回放最近是谁更新了哪些工件。",
            }
        )
        suggestions.append("后续通过 sync-sniff-artifacts、sync-case-artifacts 或 update-task 写入，保留 write receipt。")


def _add_size_balance_health(artifacts: dict[str, object], issues: list[dict[str, object]], suggestions: list[str]) -> None:
    for name in ["context", "plan", "design", "change_log"]:
        info = artifacts.get(name, {}) if isinstance(artifacts.get(name), dict) else {}
        chars = int(info.get("chars", 0))
        if chars > 12000:
            issues.append(
                {
                    "code": f"oversized_{name}",
                    "severity": "warning",
                    "message": f"{name} 体量偏大，恢复时可能引入噪音。",
                    "evidence": {"chars": chars, "limit": 12000},
                }
            )
            suggestions.append(f"压缩或归档 {name} 中的旧章节，只保留当前任务仍需要的证据。")


def _similar_task_candidates(workspace_file: str | Path, meta: dict[str, object], limit: int = 5) -> list[dict[str, object]]:
    task_id = str(meta.get("task_id", "") or "")
    current_signature = _task_signature_for_existing(workspace_file, meta)
    listed = list_task_spaces(workspace_file, include_archived=False)
    matches: list[dict[str, object]] = []
    for task in listed.get("active_tasks", []):
        if str(task.get("task_id", "")) == task_id:
            continue
        signature = _task_signature_for_existing(workspace_file, task)
        overlap = _task_signature_overlap(current_signature, signature)
        score = int(overlap.get("score", 0))
        if score < 4:
            continue
        matches.append(
            {
                "task_id": task.get("task_id", ""),
                "title": task.get("title", ""),
                "status": task.get("status", ""),
                "overlap": overlap,
            }
        )
    matches.sort(key=lambda item: (-int((item.get("overlap", {}) or {}).get("score", 0)), str(item.get("task_id", ""))))
    return matches[:limit]


def _task_health_score(issues: list[dict[str, object]]) -> int:
    penalty = 0
    for issue in issues:
        severity = str(issue.get("severity", "warning"))
        if severity == "error":
            penalty += 25
        elif severity == "warning":
            penalty += 10
        else:
            penalty += 4
    return max(0, 100 - penalty)


def _health_label(score: int, issues: list[dict[str, object]]) -> str:
    if any(str(issue.get("severity", "")) == "error" for issue in issues) or score < 60:
        return "bad"
    if score < 85 or issues:
        return "warning"
    return "good"


def _summarize_task_health_issues(results: list[dict[str, object]]) -> list[dict[str, object]]:
    counts: dict[str, dict[str, object]] = {}
    for result in results:
        for issue in result.get("issues", []) if isinstance(result.get("issues", []), list) else []:
            code = str(issue.get("code", "unknown"))
            entry = counts.setdefault(code, {"code": code, "count": 0, "severity": issue.get("severity", "warning")})
            entry["count"] = int(entry.get("count", 0)) + 1
    rows = list(counts.values())
    rows.sort(key=lambda item: (-int(item.get("count", 0)), str(item.get("code", ""))))
    return rows[:10]


def _repair_actions_for_issue(issue: dict[str, object], health: dict[str, object]) -> list[dict[str, object]]:
    code = str(issue.get("code", ""))
    task_id = str(health.get("task_id", ""))
    workspace = str(health.get("workspace", ""))
    title = str(health.get("title", ""))
    if code == "missing_write_receipts":
        return [
            _repair_action(
                issue,
                action="use_receipted_write_command",
                target="write_receipts",
                command="memory-center sync-sniff-artifacts | memory-center sync-case-artifacts | memory-center artifact update-task",
                requires_content=True,
                safe=False,
                preview="后续写入请走带 write receipt 的命令；历史缺失凭证不自动补造。",
                notes=["不建议伪造历史 write receipt。"],
            )
        ]
    if code.startswith("missing_") or code.startswith("empty_"):
        artifact = code.removeprefix("missing_").removeprefix("empty_")
        if artifact == "current_summary":
            return [
                _repair_action(
                    issue,
                    action="sync_sniff_artifacts",
                    target="current_summary",
                    command="memory-center sync-sniff-artifacts",
                    requires_intent=True,
                    safe=False,
                    preview=_current_summary_repair_preview(title),
                    notes=["需要提供当前任务意图，避免把过期上下文写入 current_summary。"],
                )
            ]
        return [
            _repair_action(
                issue,
                action="update_task_artifact",
                target=artifact,
                command="memory-center artifact update-task",
                requires_content=True,
                safe=False,
                preview=_artifact_repair_preview(artifact, title),
                notes=[f"目标 task_id: {task_id}", "先人工确认内容，再执行写入。"],
            )
        ]
    if code == "oversized_current_summary":
        return [
            _repair_action(
                issue,
                action="update_current_summary_snapshot",
                target="current_summary",
                command="memory-center sync-sniff-artifacts",
                requires_intent=True,
                safe=False,
                preview=_current_summary_repair_preview(title),
                notes=["保留目标、已完成、下一步、风险，不复制完整历史。"],
            )
        ]
    if code == "stale_task_space":
        return [
            _repair_action(
                issue,
                action="resume_then_sync",
                target="current_summary",
                command="memory-center resume-packet && memory-center sync-sniff-artifacts",
                requires_intent=True,
                safe=False,
                preview="先读取 resume-packet，确认当前任务仍有效，再刷新 current_summary。",
                notes=["如果任务已结束，改用 archive-task。"],
            )
        ]
    if code == "weak_next_actions":
        return [
            _repair_action(
                issue,
                action="update_task_artifact",
                target="plan",
                command="memory-center artifact update-task",
                requires_content=True,
                safe=False,
                preview="## Next Actions / 下一步\n\n- 确认当前目标和验收口径。\n- 补齐影响分析或验证项。\n- 执行最小回归并记录结果。",
                notes=["把下一步写成 1-3 条可执行动作。"],
            )
        ]
    if code == "blocked_without_reason":
        return [
            _repair_action(
                issue,
                action="update_task_artifact",
                target="current_summary",
                command="memory-center artifact update-task",
                requires_content=True,
                safe=False,
                preview="## Blocked / 阻塞\n\n- Reason: \n- Waiting on: \n- First action after unblock: ",
                notes=["blocked 任务必须写清楚阻塞原因和解除后的第一步。"],
            )
        ]
    if code.startswith("oversized_"):
        artifact = code.removeprefix("oversized_")
        return [
            _repair_action(
                issue,
                action="compact_task_artifact",
                target=artifact,
                command="memory-center artifact update-task",
                requires_content=True,
                safe=False,
                preview=_compact_artifact_preview(artifact),
                notes=["当前只生成压缩计划，不自动删除原文。"],
            )
        ]
    if code == "similar_task_spaces":
        evidence = issue.get("evidence", [])
        return [
            _repair_action(
                issue,
                action="disambiguate_task_spaces",
                target="task_space",
                command="memory-center artifact update-task-status | memory-center artifact archive-task",
                requires_content=False,
                safe=False,
                preview="为相似任务补充更具体标题/计划，或归档已经结束的重复任务。",
                notes=[f"相似候选: {', '.join(str(item.get('task_id', '')) for item in evidence[:3])}" if isinstance(evidence, list) else ""],
            )
        ]
    return [
        _repair_action(
            issue,
            action="manual_review",
            target="task_space",
            command="memory-center artifact health-task",
            requires_content=False,
            safe=False,
            preview="人工复核该健康问题，并选择合适的 task artifact 更新方式。",
            notes=[f"workspace: {workspace}"],
        )
    ]


def _repair_action(
    issue: dict[str, object],
    *,
    action: str,
    target: str,
    command: str,
    preview: str,
    requires_intent: bool = False,
    requires_content: bool = False,
    safe: bool = False,
    notes: list[str] | None = None,
) -> dict[str, object]:
    return {
        "issue_code": issue.get("code", ""),
        "severity": issue.get("severity", "warning"),
        "action": action,
        "target": target,
        "command": command,
        "requires_intent": requires_intent,
        "requires_content": requires_content,
        "safe_to_auto_apply": safe,
        "preview": preview,
        "notes": [item for item in notes or [] if item],
    }


def _dedupe_repair_plan(plan: list[dict[str, object]]) -> list[dict[str, object]]:
    seen: set[tuple[str, str, str]] = set()
    result: list[dict[str, object]] = []
    for item in plan:
        key = (str(item.get("issue_code", "")), str(item.get("action", "")), str(item.get("target", "")))
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _build_repair_execution_step(workspace_file: str | Path, task_id: str, step: dict[str, object], intent: str = "") -> dict[str, object]:
    action = str(step.get("action", ""))
    target = str(step.get("target", ""))
    issue_code = str(step.get("issue_code", ""))
    supported = False
    execution_action = "manual_review"
    requires_intent = bool(step.get("requires_intent"))
    if action in {"sync_sniff_artifacts", "update_current_summary_snapshot", "resume_then_sync"} and target == "current_summary":
        supported = True
        execution_action = "sync_sniff_artifacts"
        requires_intent = True
    elif action == "update_task_artifact" and target in {"context", "plan"}:
        supported = True
        execution_action = "append_repair_template"
    return {
        "issue_code": issue_code,
        "source_action": action,
        "action": execution_action,
        "target": target,
        "supported": supported,
        "requires_intent": requires_intent,
        "requires_content": bool(step.get("requires_content")),
        "status": "ready" if supported and (not requires_intent or intent.strip()) else ("blocked" if supported else "skipped"),
        "reason": "" if supported else "manual_or_high_risk_repair",
        "preview": step.get("preview", ""),
        "command": _repair_execution_command(workspace_file, task_id, execution_action, target),
    }


def _repair_execution_command(workspace_file: str | Path, task_id: str, action: str, target: str) -> str:
    if action == "sync_sniff_artifacts":
        return f"memory-center sync-sniff-artifacts --workspace {workspace_file} --task-id {task_id} --intent <intent>"
    if action == "append_repair_template":
        return f"memory-center artifact repair-task --workspace {workspace_file} --task-id {task_id} --apply"
    return "manual review"


def _apply_repair_execution_step(workspace_file: str | Path, task_id: str, item: dict[str, object], intent: str = "", sync_sniff: Callable[[str | Path, str, str], dict[str, object]] | None = None) -> dict[str, object]:
    action = str(item.get("action", ""))
    target = str(item.get("target", ""))
    try:
        if action == "sync_sniff_artifacts":
            if sync_sniff is None:
                return {**item, "applied": False, "status": "blocked", "reason": "sync_sniff_callback_required"}
            result = sync_sniff(workspace_file, intent, task_id)
            return {**item, "applied": bool(result.get("synced")), "status": "applied" if result.get("synced") else "failed", "result": result}
        if action == "append_repair_template" and target in {"context", "plan"}:
            content = _repair_apply_template(target, str(item.get("issue_code", "")))
            result = update_task_artifact(workspace_file, task_id, target, content, source="repair_task")
            return {**item, "applied": True, "status": "applied", "result": result}
    except Exception as exc:
        return {**item, "applied": False, "status": "failed", "error": str(exc)}
    return {**item, "applied": False, "status": "skipped", "reason": "unsupported_repair_action"}


def _repair_apply_template(target: str, issue_code: str) -> str:
    if target == "plan":
        return (
            "## Next Actions / 下一步\n\n"
            "- 确认当前目标和验收口径。\n"
            "- 补齐影响分析或验证项。\n"
            "- 执行最小回归并记录结果。\n"
            f"\n> Added by repair_task for `{issue_code}`.\n"
        )
    if target == "context":
        return (
            "## Repair Context / 修复上下文\n\n"
            "- 当前任务空间缺少可接手上下文。\n"
            "- 请补充目标、关键证据、影响范围和下一步。\n"
            f"\n> Added by repair_task for `{issue_code}`.\n"
        )
    return ""


def _current_summary_repair_preview(title: str) -> str:
    return (
        "# Current Summary / 当前最短上下文\n\n"
        f"**Task**: {title}\n"
        "**Goal**: \n"
        "**Done**: \n"
        "**Next Actions**:\n"
        "- \n"
        "**Risks / Open Questions**:\n"
        "- \n"
    )


def _artifact_repair_preview(artifact: str, title: str) -> str:
    heading = artifact.replace("_", " ").title()
    return f"# {heading}\n\nTask: {title}\n\n## Current Facts\n\n- \n\n## Next Actions\n\n- \n"


def _compact_artifact_preview(artifact: str) -> str:
    heading = artifact.replace("_", " ").title()
    return f"# {heading}\n\n## Active Context\n\n- \n\n## Archived / Superseded Notes\n\n- Move old details to a history section or external archive.\n"


def _artifact_body_without_boilerplate(content: str) -> str:
    lines = []
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        if stripped.startswith("- Workspace:") or stripped.startswith("- Task:") or stripped.startswith("- Memory layer:") or stripped.startswith("- Last updated:"):
            continue
        if "Fill this" in stripped or "请协作补充" in stripped:
            continue
        lines.append(stripped)
    return "\n".join(lines)


def _is_placeholder_artifact(content: str) -> bool:
    body = _artifact_body_without_boilerplate(content)
    if not body.strip():
        return True
    markers = ["Fill this", "collaboratively", "请协作补充", "TBD"]
    return len(body) < 80 and any(marker in content for marker in markers)


def _days_since_iso(value: str) -> int | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0, int((datetime.now(timezone.utc) - dt).total_seconds() // 86400))
    except Exception:
        return None


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _slugify_task_title(title: str) -> str:
    parts = _tokenize_text(title)
    if not parts:
        return f"task-{uuid4().hex[:8]}"
    return "-".join(parts[:8])


def _task_meta_path(task_dir: Path) -> Path:
    return task_dir / "meta.json"


def _write_task_meta(store: WorkspaceStore, task_dir: Path, meta: dict[str, object]) -> None:
    meta = dict(meta)
    meta.setdefault("updated_at", datetime.now().isoformat())
    with FileLock(str(store.lock_file)):
        _write_task_meta_unlocked(task_dir, meta)


def _write_task_meta_unlocked(task_dir: Path, meta: dict[str, object]) -> None:
    meta = dict(meta)
    meta.setdefault("updated_at", datetime.now().isoformat())
    _task_meta_path(task_dir).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_task_meta(task_dir: Path) -> dict[str, object]:
    path = _task_meta_path(task_dir)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _touch_task_meta(store: WorkspaceStore, task_dir: Path, meta: dict[str, object], source: str = "") -> None:
    meta = dict(meta)
    meta["updated_at"] = datetime.now().isoformat()
    if source:
        meta["last_activity_source"] = source
    _write_task_meta(store, task_dir, meta)


def touch_task_activity(workspace_file: str | Path, task_id: str, source: str) -> dict[str, object]:
    config = load_workspace_config(workspace_file)
    store = WorkspaceStore(workspace_file)
    task_dir, meta = _resolve_task_dir(store, task_id)
    meta["last_activity_source"] = source
    _touch_task_meta(store, task_dir, meta)
    return {
        "workspace": config.workspace,
        "task_id": meta["task_id"],
        "last_activity_source": source,
        "updated_at": meta["updated_at"],
    }


def _list_task_dir_entries(root: Path, archived: bool) -> list[dict[str, object]]:
    if not root.exists():
        return []
    rows = []
    for item in sorted(root.iterdir()):
        if not item.is_dir():
            continue
        meta = _read_task_meta(item)
        if not meta:
            continue
        rows.append(
            {
                "task_id": meta.get("task_id", item.name),
                "title": meta.get("title", item.name),
                "intent": meta.get("intent", ""),
                "status": meta.get("status", "active"),
                "owner": meta.get("owner", ""),
                "tags": meta.get("tags", []),
                "priority": meta.get("priority", "medium"),
                "last_activity_source": meta.get("last_activity_source", ""),
                "created_at": meta.get("created_at", ""),
                "updated_at": meta.get("updated_at", ""),
                "archived": archived or bool(meta.get("archived", False)),
                "path": str(item),
            }
        )
    return rows


def _task_status_priority(status: str) -> int:
    order = {
        "active": 0,
        "blocked": 1,
        "draft": 2,
        "done": 3,
        "archived": 4,
    }
    return order.get(status.strip().lower(), 9)


def _sortable_dt_value(value: str) -> float:
    dt = _parse_dt(value)
    if not dt:
        return float("inf")
    return -dt.timestamp()


def _resolve_task_dir(store: WorkspaceStore, task_id: str) -> tuple[Path, dict[str, object]]:
    from memory_center.core.storage.workspace import _safe_path

    slug = task_id.strip()
    active = _safe_path(store.artifacts_dir, f"{TASKS_DIR}/{slug}")
    if active.exists():
        meta = _read_task_meta(active)
        return active, meta
    archived = _safe_path(store.artifacts_dir, f"{ARCHIVE_DIR}/{slug}")
    if archived.exists():
        meta = _read_task_meta(archived)
        meta["archived"] = True
        return archived, meta
    raise ValueError(f"unknown task space: {task_id}")


def _task_match_analysis(
    workspace_file: str | Path,
    task: dict[str, object],
    keywords: list[str],
    hint_keywords: list[str] | None = None,
) -> dict[str, object]:
    keywords = keywords or []
    hint_keywords = hint_keywords or []
    try:
        workspace_name = str(load_workspace_config(workspace_file).workspace or "").strip().lower()
    except Exception:
        workspace_name = ""
    title_text = str(task.get("title", "")).lower()
    intent_text = str(task.get("intent", "")).lower()
    tags = [str(tag).lower() for tag in task.get("tags", []) if isinstance(task.get("tags"), list)] if isinstance(task.get("tags"), list) else []
    haystack_parts = [
        str(task.get("title", "")),
        str(task.get("intent", "")),
        str(task.get("status", "")),
        str(task.get("owner", "")),
        " ".join(task.get("tags", []) if isinstance(task.get("tags"), list) else []),
        str(task.get("priority", "")),
    ]
    artifact_hits: list[str] = []
    artifact_text_by_name: dict[str, str] = {}
    try:
        # 注意：这里必须用 artifact key（context / requirement / ...）而非文件名——
        # ``get_task_artifact`` 的名字解析不接受 "current-summary.md" 这样的文件名，
        # 传入会在第一个条目就抛 ValueError，导致所有 artifact 内容静默丢失。
        # current_summary 刻意不参与匹配（P0 自写自匹配修复）：它在每次 close 时被
        # 当次 intent 覆盖，若作为匹配源会形成"上次误写入 → 本次更易命中"的自强化
        # 轮替（真实工作区曾把 69 种不同 intent 轮替写进同一个 task space）。
        for artifact_name in ["context", "requirement", "design", "plan", "test_plan"]:
            artifact = get_task_artifact(
                workspace_file,
                str(task.get("task_id", "")),
                artifact_name,
                max_bytes=TASK_ARTIFACT_EXCERPT_BYTES,
            )
            trimmed = _trim_text(str(artifact.get("content", "")), 800)
            haystack_parts.append(trimmed)
            artifact_text = trimmed.lower()
            artifact_text_by_name[artifact_name] = artifact_text
            if any(token in artifact_text for token in keywords + hint_keywords):
                artifact_hits.append(artifact_name)
    except Exception:
        pass
    haystack = " ".join(haystack_parts).lower()

    # P1-B: classify evidence sources. tag/title/intent exact hits and
    # signature overlap are strong; generic token containment is fuzzy and
    # must not by itself justify an automatic write into a task space.
    # CJK 连续串不分词（base_tokenize 保留整串），所以长 CJK token 同时用
    # 字符多重集比较判断"同词不同序"的精确命中。
    strong_sources: dict[str, list[str]] = {"tag_exact": [], "title_exact": [], "intent_exact": []}
    fuzzy_tokens: list[str] = []

    # 通用词、纯数字、拼音式碎片的贡献有上限：它们区分度低，不足以锚定任务。
    _WEAK_TOKENS = {"v1", "v2", "v3", "test", "demo", "task", "优化", "清理", "修复", "更新", "支持", "问题", "处理"}
    # P0 补充：框架/中间件/基础设施通名。任何 Spring 任务都可能出现，
    # 曾让单个 intent_exact(2)+status(2)+priority(1) 稳过阈值。
    _WEAK_TOKENS.update({"feign", "kafka", "rocketmq", "redis", "elasticsearch", "mysql", "mongo", "mongodb",
                         "controller", "service", "dto", "api", "http", "rest", "gateway", "spring", "boot",
                         "java", "config", "consumer", "producer", "topic", "queue", "token", "login"})
    # P0 补充：workspace 自身名字（含前缀关系，如 workspace=ucap-all 时 "ucap"）
    # 是每个 intent 都会出现的通名，曾以 intent_exact 身份稳定贡献强证据，
    # 是低分误绑定的帮凶。
    if len(workspace_name) >= 2:
        _WEAK_TOKENS.add(workspace_name)

    def _is_weak(token: str) -> bool:
        if token in _WEAK_TOKENS or token.isdigit() or len(token) <= 2:
            return True
        # workspace 名的前缀方向也算通名：ucap / ucap-all 互为前缀。
        if workspace_name and (workspace_name.startswith(token) or token.startswith(workspace_name)):
            return True
        # workspace 名内部片段（ucap-all 的 'ucap'/'all'）及服务前缀族
        # （ucap-cloud-* 的 'cloud'）：同一 workspace 的任意 intent 都可能出现。
        if workspace_name:
            for part in workspace_name.split("-"):
                if len(part) >= 3 and (part.startswith(token) or token.startswith(part)):
                    return True
        return False

    for token in keywords + hint_keywords:
        normalized = token.strip().lower()
        if not normalized or len(normalized) < 2:
            continue
        weak = _is_weak(normalized)
        if normalized in tags or _cjk_anagram_in(normalized, tags):
            # 弱 token（通用动词/纯数字/通名）即使出现在 tag 里也不构成强证据。
            if not weak:
                strong_sources["tag_exact"].append(token)
            else:
                fuzzy_tokens.append(token)
        elif normalized in title_text or _cjk_anagram_in(normalized, [title_text]) or _cjk_subword_in(normalized, title_text):
            if not weak:
                strong_sources["title_exact"].append(token)
            else:
                fuzzy_tokens.append(token)
        elif (intent_text and normalized in intent_text) or _cjk_anagram_in(normalized, [intent_text]) or _cjk_subword_in(normalized, intent_text):
            if not weak:
                strong_sources["intent_exact"].append(token)
            else:
                fuzzy_tokens.append(token)
        elif any(
            _cjk_subword_in(normalized, artifact_text_by_name.get(name, ""))
            for name in ["context", "requirement", "design", "plan", "test_plan"]
        ):
            # CJK 长意图与 plan/context 正文有实质 bigram 重叠时算作签名重叠证据。
            # current_summary 已从匹配源排除（P0 自写自匹配修复），其余工件是
            # 相对稳定的任务定义文档，其正文命中可作强证据。
            strong_sources.setdefault("signature_overlap", []).append(token)
        elif token in haystack:
            fuzzy_tokens.append(token)
    matched_keywords = [token for token in keywords if token in haystack]
    matched_hint_keywords = [token for token in hint_keywords if token in haystack]

    weak_fuzzy = [token for token in fuzzy_tokens if _is_weak(token)]
    capped_fuzzy = [token for token in fuzzy_tokens if not _is_weak(token)][:4]

    strong_score = (
        3 * len([t for t in strong_sources["tag_exact"] if not _is_weak(t)])
        + 3 * len([t for t in strong_sources["title_exact"] if not _is_weak(t)])
        + 2 * len([t for t in strong_sources["intent_exact"] if not _is_weak(t)])
        + 1 * len([t for t in strong_sources.get("signature_overlap", []) if not _is_weak(t)])
    )
    strong_evidence = strong_score > 0
    # P0 二次收紧：单一 intent_exact 命中（2 分）不足以支撑状态/优先级加分。
    # intent 里 'cloud'/'分析' 一类词在长 meta.intent 中极易蹭到，加成后
    # runner-up 常以 5 分贴脸 top1 触发 ambiguous。要求 tag/title 级（3 分档）
    # 或 ≥2 个 intent_exact 才给加分。
    anchoring_evidence = bool(
        strong_sources["tag_exact"] or strong_sources["title_exact"]
        or len([t for t in strong_sources["intent_exact"] if not _is_weak(t)]) >= 2
    )
    score = strong_score + len(capped_fuzzy)
    # P0：状态/优先级加分只在已有强证据时生效。active 白送 2 分曾让仅凭正文
    # 模糊命中的大任务稳过阈值（自强化轮替的另一根因）。
    status_boost = 0
    if anchoring_evidence:
        if str(task.get("status", "")) == "active":
            status_boost = 2
        elif str(task.get("status", "")) == "draft":
            status_boost = 1
    score += status_boost
    priority_boost = 0
    if anchoring_evidence and str(task.get("priority", "")) == "high":
        priority_boost = 1
    score += priority_boost
    return {
        "score": score,
        "match_reasons": {
            "matched_keywords": matched_keywords[:8],
            "matched_hint_keywords": matched_hint_keywords[:8],
            "artifact_hits": artifact_hits[:6],
            "status_boost": status_boost,
            "priority_boost": priority_boost,
            "tag_exact": strong_sources["tag_exact"][:8],
            "title_exact": strong_sources["title_exact"][:8],
            "intent_exact": strong_sources["intent_exact"][:8],
            "fuzzy_token": fuzzy_tokens[:8],
            "weak_token_capped": weak_fuzzy[:8],
            "signature_overlap": strong_sources.get("signature_overlap", [])[:8],
            "strong_evidence": strong_evidence,
        },
    }


def _cjk_anagram_in(token: str, texts: list[str] | tuple[str, ...]) -> bool:
    """True when some text is a CJK anagram of the token (same characters).

    中文没有空格分词：`重构订单服务` 与标题 `订单服务重构` 是同一词的不同
    叙述顺序，字符多重集一致即视为精确命中；对拉丁 token 恒为 False。
    """
    if len(token) < 2 or not all("\u4e00" <= ch <= "\u9fff" for ch in token):
        return False
    sorted_token = sorted(token)
    for text in texts:
        candidate = str(text or "").strip().lower()
        if not candidate:
            continue
        for word in candidate.split():
            if len(word) == len(token) and sorted(word) == sorted_token:
                return True
    return False


def _cjk_subword_in(token: str, text: str) -> bool:
    """CJK containment when token boundaries differ from the stored text.

    `继续处理链路分析` 与标题 `链路分析任务` 共享连续子串 `链路分析`，但整串
    substring 检查会漏掉。要求 token 与某个 CJK 词存在长度 >= 4 的连续公共
    子串（3 字如 `全链路` 属通用高歧义词，真实工作区会跨任务误命中，见
    ucap 验证：`的全链路观测问题` 误中 `错敏复查全链路`）；对拉丁 token 恒为 False。
    """
    if len(token) < 4 or not all("\u4e00" <= ch <= "\u9fff" for ch in token):
        return False
    text = (text or "").strip().lower()
    if not text:
        return False
    for word in text.split():
        if not all("\u4e00" <= ch <= "\u9fff" for ch in word) or len(word) < 4:
            continue
        # 长词最多要求 4 字连续公共子串，避免对 10+ 字标题要求覆盖一半。
        required = max(4, min(4, len(word) // 2))
        best = 0
        for i in range(len(token)):
            for j in range(len(word)):
                k = 0
                while i + k < len(token) and j + k < len(word) and token[i + k] == word[j + k]:
                    k += 1
                best = max(best, k)
        if best >= required and best >= 4:
            return True
    return False


def _task_signature_for_existing(workspace_file: str | Path, task: dict[str, object]) -> dict[str, object]:
    related_texts: list[str] = []
    try:
        for artifact_name in ["current_summary", "context", "requirement", "design", "plan", "test_plan"]:
            artifact = get_task_artifact(
                workspace_file,
                str(task.get("task_id", "")),
                artifact_name,
                max_bytes=TASK_ARTIFACT_EXCERPT_BYTES,
            )
            related_texts.append(_artifact_body_without_boilerplate(str(artifact.get("content", ""))))
    except Exception:
        pass
    return _build_task_signature(
        title=str(task.get("title", "")),
        intent=str(task.get("intent", "")),
        related_texts=related_texts,
        tags=task.get("tags", []) if isinstance(task.get("tags"), list) else [],
    )


def _build_task_signature(
    title: str = "",
    intent: str = "",
    related_texts: list[str] | None = None,
    tags: list[str] | None = None,
) -> dict[str, object]:
    text = "\n".join([title, intent, *(related_texts or []), " ".join(tags or [])])
    tokens = _tokenize_text(text)
    token_counts: dict[str, int] = {}
    for token in tokens:
        if len(token) < 2:
            continue
        token_counts[token] = token_counts.get(token, 0) + 1
    ranked_tokens = sorted(token_counts, key=lambda item: (-token_counts[item], item))[:20]
    service_refs = sorted({token for token in ranked_tokens if token.endswith("service") or token.endswith("服务")})[:10]
    file_refs = sorted(set(re.findall(r"[\w./-]+\.(?:java|py|ts|js|vue|yaml|yml|md)", text, flags=re.IGNORECASE)))[:10]
    risk_terms = sorted({token for token in ranked_tokens if token in {"feign", "mq", "kafka", "rocketmq", "dto", "config", "nacos", "migration", "兼容", "迁移", "配置", "消息", "验证"}})
    return {
        "tokens": ranked_tokens,
        "service_refs": service_refs,
        "file_refs": file_refs,
        "risk_terms": risk_terms,
    }


def _task_signature_overlap(left: dict[str, object], right: dict[str, object]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key in ("tokens", "service_refs", "file_refs", "risk_terms"):
        left_set = set(left.get(key, []) if isinstance(left.get(key, []), list) else [])
        right_set = set(right.get(key, []) if isinstance(right.get(key, []), list) else [])
        result[key] = sorted(left_set & right_set)[:10]
    result["score"] = sum(len(result.get(key, [])) for key in ("tokens", "service_refs", "file_refs", "risk_terms"))
    return result


def _is_ambiguous_task_match(scored: list[dict[str, object]], score_threshold: int) -> bool:
    """P1-B: conservative ambiguity — 完全同分、margin 不足、低置信都算歧义。

    旧逻辑只把"完全同分"当歧义，导致低分相近候选被自动选中。现在：
    - top1 与 top2 都过阈值但差值 < 最小绝对 margin（2）→ ambiguous；
    - top1/top2 比值低于 1.25（top2 分数接近 top1）→ ambiguous；
    - top1 缺少 tag/title/intent 强证据 → ambiguous。
    """
    if not scored:
        return False
    first = int(scored[0].get("score", 0))
    first_reasons = scored[0].get("match_reasons", {}) if isinstance(scored[0].get("match_reasons"), dict) else {}
    if first < score_threshold:
        return False
    if not first_reasons.get("strong_evidence"):
        return True
    if len(scored) < 2:
        return False
    second = int(scored[1].get("score", 0))
    if second < score_threshold:
        return False
    if first == second:
        first_overlap = int((scored[0].get("signature_overlap", {}) or {}).get("score", 0))
        second_overlap = int((scored[1].get("signature_overlap", {}) or {}).get("score", 0))
        return abs(first_overlap - second_overlap) <= 1
    if first - second < _TASK_MATCH_MIN_MARGIN:
        return True
    if second > 0 and first / second < _TASK_MATCH_MIN_RATIO:
        return True
    return False


_TASK_MATCH_MIN_MARGIN = 2
_TASK_MATCH_MIN_RATIO = 1.25
_TASK_HIGH_CONFIDENCE_MIN_SCORE = 5


def _task_resolution_confidence(scored: list[dict[str, object]], score_threshold: int) -> tuple[str, bool, str]:
    """Return (resolution_confidence, auto_write_allowed, required_action).

    P1-B: high = top1 有强证据（tag/title/intent exact）且分数明显高于阈值与
    top2；medium = 有强证据但 margin 不足；low = 无强证据或 top1 未达阈值。
    ``auto_write_allowed=false`` 时调用方必须停止写入并返回候选。
    """
    if not scored:
        return "low", False, "explicit_task_id"
    first = int(scored[0].get("score", 0))
    first_reasons = scored[0].get("match_reasons", {}) if isinstance(scored[0].get("match_reasons"), dict) else {}
    strong = bool(first_reasons.get("strong_evidence"))
    second = int(scored[1].get("score", 0)) if len(scored) > 1 else 0
    margin = first - second
    if first >= score_threshold and strong and margin >= _TASK_MATCH_MIN_MARGIN:
        return "high", True, ""
    if first >= score_threshold and strong:
        return "medium", True, ""
    if first >= score_threshold:
        return "low", False, "explicit_task_id"
    return "low", False, "explicit_task_id"


def _parse_dt(value: str):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _split_markdown_sections(content: str) -> list[dict[str, object]]:
    if not content.strip():
        return []
    lines = content.splitlines()
    sections: list[dict[str, object]] = []
    current_title = "Document"
    current_level = 1
    current_body: list[str] = []
    for line in lines:
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            if current_body or current_title:
                sections.append({"title": current_title, "level": current_level, "body": "\n".join(current_body).strip()})
            current_level = len(m.group(1))
            current_title = m.group(2).strip()
            current_body = []
        else:
            current_body.append(line)
    sections.append({"title": current_title, "level": current_level, "body": "\n".join(current_body).strip()})
    return [item for item in sections if item["title"] or item["body"]]


def _split_change_log_entries(content: str) -> tuple[str, list[str]]:
    sections = _split_markdown_sections(content)
    if not sections:
        return "# Change Log / 变更记录\n", []
    prefix_lines = [f"# {sections[0]['title']}"]
    if sections[0]["body"]:
        prefix_lines.append("")
        prefix_lines.append(str(sections[0]["body"]))
    entries = []
    for section in sections[1:]:
        heading = "#" * int(section["level"])
        body = f"{heading} {section['title']}\n\n{section['body']}".strip()
        entries.append(body)
    return "\n".join(prefix_lines).strip() + "\n", entries


def _tokenize_text(text: str) -> list[str]:
    return base_tokenize(text)


def _section_score(section: dict[str, object], keywords: list[str]) -> int:
    haystack = f"{section['title']} {section['body']}".lower()
    return sum(1 for token in keywords if token in haystack)


def _trim_text(text: str, limit: int) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."


# --- H-02: Traceability Graph ---
# Links requirements → tasks → changes → verification for full traceability.

TRACEABILITY_FILE = "traceability-graph.json"


def build_traceability_graph(workspace_file: str | Path) -> dict[str, Any]:
    """Build a traceability graph linking requirements, tasks, changes, and verification.

    Returns a graph with nodes (requirements, tasks, changes, verification)
    and edges (requires, implements, verifies).
    """
    config = load_workspace_config(workspace_file)
    store = WorkspaceStore(workspace_file)
    tasks = list_task_spaces(workspace_file, include_archived=True)

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    # Add requirement nodes from artifacts
    for key, filename in DEFAULT_ARTIFACTS.items():
        content = store.read_artifact(filename, "")
        if content.strip():
            node_id = f"req:{key}"
            nodes.append({"id": node_id, "type": "requirement", "name": key, "file": filename})

    # Add task nodes and link to requirements
    all_tasks = (tasks.get("active_tasks") or []) + (tasks.get("archived_tasks") or [])
    for task in all_tasks:
        task_id = task.get("task_id", "")
        if not task_id:
            continue
        nodes.append({"id": f"task:{task_id}", "type": "task", "name": task.get("title", ""), "status": task.get("status", "")})

        # Link task to requirement artifacts
        for artifact_key in ["requirement", "design", "plan", "test_plan"]:
            content = get_task_artifact(
                workspace_file,
                task_id,
                artifact_key,
                max_bytes=TASK_ARTIFACT_EXCERPT_BYTES,
            ).get("content", "")
            if content.strip():
                edges.append({
                    "source": f"task:{task_id}",
                    "target": f"req:{artifact_key}",
                    "type": "references",
                })

    # Add change log entries as change nodes
    change_log = store.read_artifact("change_log", "")
    if change_log.strip():
        nodes.append({"id": "change:change_log", "type": "change", "name": "change_log"})

    # Add verification nodes from verification loop data
    try:
        from ..verification.loop import VERIFICATION_LOG_FILE
        loop_entries = store.read_jsonl_via_backend(VERIFICATION_LOG_FILE, limit=100)
        for entry in loop_entries:
            loop_id = entry.get("loop_id", "")
            if loop_id:
                nodes.append({"id": f"verify:{loop_id}", "type": "verification", "status": entry.get("status", "")})
                task_id = entry.get("task_id", "")
                if task_id:
                    edges.append({"source": f"verify:{loop_id}", "target": f"task:{task_id}", "type": "verifies"})
    except Exception:
        pass

    # Find unlinked tasks (no requirement reference)
    linked_tasks = {e["source"] for e in edges if e["type"] == "references"}
    unlinked_tasks = [n["id"] for n in nodes if n["type"] == "task" and n["id"] not in linked_tasks]

    # Find uncovered requirements (no task references them)
    linked_reqs = {e["target"] for e in edges if e["type"] == "references"}
    uncovered_reqs = [n["id"] for n in nodes if n["type"] == "requirement" and n["id"] not in linked_reqs]

    graph = {
        "workspace": config.workspace,
        "nodes": nodes,
        "edges": edges,
        "diagnostics": {
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "unlinked_tasks": unlinked_tasks,
            "uncovered_requirements": uncovered_reqs,
        },
    }

    # Persist for future reference
    try:
        store.write_json(TRACEABILITY_FILE, graph)
    except Exception:
        pass

    return graph
