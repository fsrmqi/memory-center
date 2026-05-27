from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re
from typing import Dict, List
from uuid import uuid4

from filelock import FileLock

from .config import load_workspace_config
from .store import WorkspaceStore
from .text_utils import base_tokenize
from .write_receipts import WRITE_RECEIPTS_FILE, build_write_receipt, persist_write_receipt

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
TASK_STATUSES = {"draft", "active", "blocked", "done", "archived"}
DEFAULT_RESOLVE_SCORE_THRESHOLD = 3
ARTIFACT_WRITE_AUDIT_FILE = "artifact-write-audit.jsonl"


def ensure_default_artifacts(workspace_file: str | Path) -> List[Dict[str, str]]:
    config = load_workspace_config(workspace_file)
    store = WorkspaceStore(workspace_file)
    created: List[Dict[str, str]] = []
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


def list_artifacts(workspace_file: str | Path) -> Dict[str, object]:
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


def get_artifact(workspace_file: str | Path, name: str) -> Dict[str, object]:
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


def update_artifact(workspace_file: str | Path, name: str, content: str) -> Dict[str, object]:
    config = load_workspace_config(workspace_file)
    store = WorkspaceStore(workspace_file)
    ensure_default_artifacts(workspace_file)
    key, filename = _resolve_artifact_name(name)
    existing = store.read_artifact(filename, "")
    next_content, mode = _merge_append_only_artifact(existing, content, key)
    path = store.write_artifact(filename, next_content)
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


def append_change_log(workspace_file: str | Path, entry: str) -> Dict[str, object]:
    config = load_workspace_config(workspace_file)
    store = WorkspaceStore(workspace_file)
    ensure_default_artifacts(workspace_file)
    filename = DEFAULT_ARTIFACTS["change_log"]
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    content = f"\n## {stamp}\n\n{entry.strip()}\n"
    path = store.append_artifact(filename, content)
    compact = compact_change_log(workspace_file, keep_recent=30)
    return {
        "workspace": config.workspace,
        "appended": True,
        "name": "change_log",
        "file": filename,
        "path": str(path),
        "entry": entry.strip(),
        "compaction": compact,
    }


def artifact_outline(workspace_file: str | Path, name: str) -> Dict[str, object]:
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


def artifact_context(workspace_file: str | Path, intent: str, limit: int = 6) -> Dict[str, object]:
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


def compact_change_log(workspace_file: str | Path, keep_recent: int = 30) -> Dict[str, object]:
    config = load_workspace_config(workspace_file)
    store = WorkspaceStore(workspace_file)
    ensure_default_artifacts(workspace_file)
    filename = DEFAULT_ARTIFACTS["change_log"]
    archive_name = "change-log.archive.md"
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
    store.write_artifact(archive_name, merged_archive)
    note = "\n> Older entries were archived to `change-log.archive.md` / 较早记录已归档到 `change-log.archive.md`\n"
    compacted = prefix.rstrip() + note + "\n" + "\n\n".join(kept_entries).strip() + "\n"
    store.write_artifact(filename, compacted)
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
    tags: List[str] | None = None,
    priority: str = "medium",
) -> Dict[str, object]:
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
    related_texts: List[str] | None = None,
    score_threshold: int = DEFAULT_RESOLVE_SCORE_THRESHOLD,
) -> Dict[str, object]:
    config = load_workspace_config(workspace_file)
    candidates = list_task_spaces(workspace_file, include_archived=include_archived)
    keyword_text = title.strip() or intent.strip()
    keywords = _tokenize_text(keyword_text)
    hint_keywords: List[str] = []
    for text in related_texts or []:
        hint_keywords.extend(_tokenize_text(text))
    scored = []
    for task in candidates["active_tasks"] + candidates.get("archived_tasks", []):
        analysis = _task_match_analysis(workspace_file, task, keywords, hint_keywords)
        score = int(analysis["score"])
        if score <= 0:
            continue
        scored.append({**task, **analysis})
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
            "path": item["path"],
        }
        for item in scored[: max(limit_candidates, 1)]
    ]
    if scored and int(scored[0]["score"]) >= score_threshold:
        top = scored[0]
        return {
            "workspace": config.workspace,
            "resolved": True,
            "created": False,
            "task_id": top["task_id"],
            "title": top["title"],
            "score": top["score"],
            "status": top.get("status", "active"),
            "owner": top.get("owner", ""),
            "tags": top.get("tags", []),
            "priority": top.get("priority", "medium"),
            "path": top["path"],
            "match_reasons": top.get("match_reasons", {}),
            "candidates": candidate_rows,
            "score_threshold": score_threshold,
        }
    if not create_if_missing:
        return {
            "workspace": config.workspace,
            "resolved": False,
            "created": False,
            "task_id": "",
            "title": "",
            "score": 0,
            "status": "",
            "path": "",
            "candidates": candidate_rows,
            "score_threshold": score_threshold,
        }
    created = create_task_space(workspace_file, title=title, intent=intent)
    return {**created, "resolved": True, "score": 0, "candidates": candidate_rows, "score_threshold": score_threshold}


def list_task_spaces(workspace_file: str | Path, include_archived: bool = False) -> Dict[str, object]:
    config = load_workspace_config(workspace_file)
    store = WorkspaceStore(workspace_file)
    active = _list_task_dir_entries(store.artifacts_dir / TASKS_DIR, archived=False)
    archived = _list_task_dir_entries(store.artifacts_dir / ARCHIVE_DIR, archived=True) if include_archived else []
    return {
        "workspace": config.workspace,
        "active_tasks": active,
        "archived_tasks": archived,
    }


def update_task_status(workspace_file: str | Path, task_id: str, status: str, source: str = "update_task_status") -> Dict[str, object]:
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


def get_task_artifact(workspace_file: str | Path, task_id: str, name: str) -> Dict[str, object]:
    config = load_workspace_config(workspace_file)
    store = WorkspaceStore(workspace_file)
    task_dir, meta = _resolve_task_dir(store, task_id)
    key, filename = _resolve_artifact_name(name, include_task_only=True)
    path = task_dir / filename
    return {
        "workspace": config.workspace,
        "task_id": meta["task_id"],
        "title": meta["title"],
        "name": key,
        "file": filename,
        "content": path.read_text(encoding="utf-8") if path.exists() else "",
        "archived": bool(meta.get("archived", False)),
    }


def update_task_artifact(workspace_file: str | Path, task_id: str, name: str, content: str, source: str = "update_task_artifact") -> Dict[str, object]:
    config = load_workspace_config(workspace_file)
    store = WorkspaceStore(workspace_file)
    task_dir, meta = _resolve_task_dir(store, task_id)
    key, filename = _resolve_artifact_name(name, include_task_only=True)
    path = task_dir / filename
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    next_content, mode = _merge_append_only_artifact(existing, content, key)
    with FileLock(str(store.lock_file)):
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
    }


def append_task_change_log(workspace_file: str | Path, task_id: str, entry: str, keep_recent: int = 30, source: str = "append_task_change_log") -> Dict[str, object]:
    config = load_workspace_config(workspace_file)
    store = WorkspaceStore(workspace_file)
    task_dir, meta = _resolve_task_dir(store, task_id)
    filename = DEFAULT_ARTIFACTS["change_log"]
    path = task_dir / filename
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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


def compact_task_change_log(workspace_file: str | Path, task_id: str, keep_recent: int = 30) -> Dict[str, object]:
    config = load_workspace_config(workspace_file)
    store = WorkspaceStore(workspace_file)
    task_dir, meta = _resolve_task_dir(store, task_id)
    path = task_dir / DEFAULT_ARTIFACTS["change_log"]
    archive_path = task_dir / "change-log.archive.md"
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


def archive_task_space(workspace_file: str | Path, task_id: str, reason: str = "") -> Dict[str, object]:
    config = load_workspace_config(workspace_file)
    store = WorkspaceStore(workspace_file)
    task_dir, meta = _resolve_task_dir(store, task_id)
    archive_root = store.artifacts_dir / ARCHIVE_DIR
    archive_root.mkdir(parents=True, exist_ok=True)
    target = archive_root / task_dir.name
    with FileLock(str(store.lock_file)):
        if target.exists():
            for child in target.iterdir():
                if child.is_file():
                    child.unlink()
        task_dir.rename(target)
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
    }


def auto_archive_task_spaces(workspace_file: str | Path, retention_days: int = 30) -> Dict[str, object]:
    config = load_workspace_config(workspace_file)
    store = WorkspaceStore(workspace_file)
    now = datetime.now()
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


def _artifact_mapping(include_task_only: bool = False) -> Dict[str, str]:
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


def _slugify_task_title(title: str) -> str:
    parts = _tokenize_text(title)
    if not parts:
        return f"task-{uuid4().hex[:8]}"
    return "-".join(parts[:8])


def _task_meta_path(task_dir: Path) -> Path:
    return task_dir / "meta.json"


def _write_task_meta(store: WorkspaceStore, task_dir: Path, meta: Dict[str, object]) -> None:
    meta = dict(meta)
    meta.setdefault("updated_at", datetime.now().isoformat())
    with FileLock(str(store.lock_file)):
        _write_task_meta_unlocked(task_dir, meta)


def _write_task_meta_unlocked(task_dir: Path, meta: Dict[str, object]) -> None:
    meta = dict(meta)
    meta.setdefault("updated_at", datetime.now().isoformat())
    _task_meta_path(task_dir).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_task_meta(task_dir: Path) -> Dict[str, object]:
    path = _task_meta_path(task_dir)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _touch_task_meta(store: WorkspaceStore, task_dir: Path, meta: Dict[str, object], source: str = "") -> None:
    meta = dict(meta)
    meta["updated_at"] = datetime.now().isoformat()
    if source:
        meta["last_activity_source"] = source
    _write_task_meta(store, task_dir, meta)


def touch_task_activity(workspace_file: str | Path, task_id: str, source: str) -> Dict[str, object]:
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


def _list_task_dir_entries(root: Path, archived: bool) -> List[Dict[str, object]]:
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


def _resolve_task_dir(store: WorkspaceStore, task_id: str) -> tuple[Path, Dict[str, object]]:
    from .store import _safe_path

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
    task: Dict[str, object],
    keywords: List[str],
    hint_keywords: List[str] | None = None,
) -> Dict[str, object]:
    keywords = keywords or []
    hint_keywords = hint_keywords or []
    haystack_parts = [
        str(task.get("title", "")),
        str(task.get("intent", "")),
        str(task.get("status", "")),
        str(task.get("owner", "")),
        " ".join(task.get("tags", []) if isinstance(task.get("tags", []), list) else []),
        str(task.get("priority", "")),
    ]
    artifact_hits: List[str] = []
    try:
        for artifact_name in ["current-summary.md", "context.md", "requirement.md", "design.md", "plan.md", "test-plan.md"]:
            artifact = get_task_artifact(workspace_file, str(task.get("task_id", "")), artifact_name)
            trimmed = _trim_text(str(artifact.get("content", "")), 800)
            haystack_parts.append(trimmed)
            artifact_text = trimmed.lower()
            if any(token in artifact_text for token in keywords + hint_keywords):
                artifact_hits.append(artifact_name)
    except Exception:
        pass
    haystack = " ".join(haystack_parts).lower()
    matched_keywords = [token for token in keywords if token in haystack]
    matched_hint_keywords = [token for token in hint_keywords if token in haystack]
    score = len(matched_keywords) + len(matched_hint_keywords)
    status_boost = 0
    if str(task.get("status", "")) == "active":
        status_boost = 2
    elif str(task.get("status", "")) == "draft":
        status_boost = 1
    score += status_boost
    priority_boost = 0
    if str(task.get("priority", "")) == "high":
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
        },
    }


def _parse_dt(value: str):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def _split_markdown_sections(content: str) -> List[Dict[str, object]]:
    if not content.strip():
        return []
    lines = content.splitlines()
    sections: List[Dict[str, object]] = []
    current_title = "Document"
    current_level = 1
    current_body: List[str] = []
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


def _split_change_log_entries(content: str) -> tuple[str, List[str]]:
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


def _tokenize_text(text: str) -> List[str]:
    return base_tokenize(text)


def _section_score(section: Dict[str, object], keywords: List[str]) -> int:
    haystack = f"{section['title']} {section['body']}".lower()
    return sum(1 for token in keywords if token in haystack)


def _trim_text(text: str, limit: int) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."
