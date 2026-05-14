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

DEFAULT_ARTIFACTS = {
    "context": "context.md",
    "requirement": "requirement.md",
    "design": "design.md",
    "plan": "plan.md",
    "test_plan": "test-plan.md",
    "change_log": "change-log.md",
}

TASKS_DIR = "tasks"
ARCHIVE_DIR = "archive/tasks"


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
    return {"workspace": config.workspace, "artifacts": items}


def get_artifact(workspace_file: str | Path, name: str) -> Dict[str, object]:
    config = load_workspace_config(workspace_file)
    store = WorkspaceStore(workspace_file)
    ensure_default_artifacts(workspace_file)
    key, filename = _resolve_artifact_name(name)
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
    path = store.write_artifact(filename, content)
    return {
        "workspace": config.workspace,
        "updated": True,
        "name": key,
        "file": filename,
        "path": str(path),
        "bytes": len(content.encode("utf-8")),
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
    for artifact_name in list(DEFAULT_ARTIFACTS.values()) + ["change-log.archive.md"]:
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


def create_task_space(workspace_file: str | Path, title: str = "", intent: str = "") -> Dict[str, object]:
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
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    }
    _write_task_meta(store, task_dir, meta)
    for key, filename in DEFAULT_ARTIFACTS.items():
        path = task_dir / filename
        if not path.exists():
            path.write_text(_default_task_artifact_content(config.workspace, task_title, key), encoding="utf-8")
    return {
        "workspace": config.workspace,
        "created": True,
        "task_id": slug,
        "title": task_title,
        "path": str(task_dir),
    }


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


def get_task_artifact(workspace_file: str | Path, task_id: str, name: str) -> Dict[str, object]:
    config = load_workspace_config(workspace_file)
    store = WorkspaceStore(workspace_file)
    task_dir, meta = _resolve_task_dir(store, task_id)
    key, filename = _resolve_artifact_name(name)
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


def update_task_artifact(workspace_file: str | Path, task_id: str, name: str, content: str) -> Dict[str, object]:
    config = load_workspace_config(workspace_file)
    store = WorkspaceStore(workspace_file)
    task_dir, meta = _resolve_task_dir(store, task_id)
    key, filename = _resolve_artifact_name(name)
    path = task_dir / filename
    with FileLock(str(store.lock_file)):
        path.write_text(content, encoding="utf-8")
    _touch_task_meta(store, task_dir, meta)
    return {
        "workspace": config.workspace,
        "updated": True,
        "task_id": meta["task_id"],
        "title": meta["title"],
        "name": key,
        "file": filename,
        "path": str(path),
    }


def append_task_change_log(workspace_file: str | Path, task_id: str, entry: str, keep_recent: int = 30) -> Dict[str, object]:
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
    _touch_task_meta(store, task_dir, meta)
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
    _write_task_meta(store, target, meta)
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


def _resolve_artifact_name(name: str) -> tuple[str, str]:
    normalized = name.strip().lower().replace("-", "_")
    if normalized in DEFAULT_ARTIFACTS:
        return normalized, DEFAULT_ARTIFACTS[normalized]
    for key, filename in DEFAULT_ARTIFACTS.items():
        if normalized == filename.lower().replace("-", "_").replace(".md", ""):
            return key, filename
        if normalized == filename.lower():
            return key, filename
    raise ValueError(f"unknown artifact: {name}")


def _default_artifact_content(workspace_name: str, artifact_name: str) -> str:
    title_map = {
        "context": "Context / 背景与上下文",
        "requirement": "Requirement / 需求与约束",
        "design": "Design / 设计方案",
        "plan": "Plan / 开发计划",
        "test_plan": "Test Plan / 测试策略",
        "change_log": "Change Log / 变更记录",
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
        _task_meta_path(task_dir).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_task_meta(task_dir: Path) -> Dict[str, object]:
    path = _task_meta_path(task_dir)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _touch_task_meta(store: WorkspaceStore, task_dir: Path, meta: Dict[str, object]) -> None:
    meta = dict(meta)
    meta["updated_at"] = datetime.now().isoformat()
    _write_task_meta(store, task_dir, meta)


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
                "created_at": meta.get("created_at", ""),
                "updated_at": meta.get("updated_at", ""),
                "archived": archived or bool(meta.get("archived", False)),
                "path": str(item),
            }
        )
    return rows


def _resolve_task_dir(store: WorkspaceStore, task_id: str) -> tuple[Path, Dict[str, object]]:
    slug = task_id.strip()
    active = store.artifacts_dir / TASKS_DIR / slug
    if active.exists():
        meta = _read_task_meta(active)
        return active, meta
    archived = store.artifacts_dir / ARCHIVE_DIR / slug
    if archived.exists():
        meta = _read_task_meta(archived)
        meta["archived"] = True
        return archived, meta
    raise ValueError(f"unknown task space: {task_id}")


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
    raw = "".join(ch.lower() if ch.isalnum() or "\u4e00" <= ch <= "\u9fff" else " " for ch in text)
    return sorted({item for item in raw.split() if len(item) >= 2})


def _section_score(section: Dict[str, object], keywords: List[str]) -> int:
    haystack = f"{section['title']} {section['body']}".lower()
    return sum(1 for token in keywords if token in haystack)


def _trim_text(text: str, limit: int) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."
