"""Read-only inventory and drift audit for host Skills, plugins, and MCP metadata."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from memory_center.core.storage.workspace import WorkspaceStore

SNAPSHOT_FILE = "external-capabilities-snapshot.json"
_MAX_ENTRIES = 500


def audit_external_capabilities(workspace_file: str | Path) -> dict[str, Any]:
    """Inspect known host locations without loading or executing capability bodies."""
    workspace = Path(workspace_file).resolve().parent.parent
    entries = _discover(workspace)
    store = WorkspaceStore(workspace_file)
    previous = store.read_json(SNAPSHOT_FILE, {}) or {}
    previous_entries = {item["capability_id"]: item for item in previous.get("entries", []) if isinstance(item, dict)}
    current_entries = {item["capability_id"]: item for item in entries}
    added = sorted(set(current_entries) - set(previous_entries))
    removed = sorted(set(previous_entries) - set(current_entries))
    changed = sorted(key for key in set(current_entries) & set(previous_entries) if current_entries[key].get("content_hash") != previous_entries[key].get("content_hash"))
    return {
        "schema_version": 1,
        "mode": "read_only",
        "entries": entries,
        "summary": {"total": len(entries), "skills": sum(item["kind"] == "skill" for item in entries), "plugins": sum(item["kind"] == "plugin" for item in entries), "mcp_configs": sum(item["kind"] == "mcp_config" for item in entries)},
        "drift": {"baseline_available": bool(previous_entries), "added": added, "removed": removed, "changed": changed},
        "next_action": "运行 external-capability-snapshot 保存当前清单，后续审计将报告漂移。" if not previous_entries else "检查漂移项；安装、启用、归档或删除必须单独明确授权。",
    }


def snapshot_external_capabilities(workspace_file: str | Path) -> dict[str, Any]:
    """Explicitly persist a metadata-only baseline for later drift comparison."""
    audit = audit_external_capabilities(workspace_file)
    WorkspaceStore(workspace_file).write_json(SNAPSHOT_FILE, {"schema_version": 1, "entries": audit["entries"]})
    return {"snapshotted": True, "summary": audit["summary"], "next_action": "后续运行 external-capability-audit 查看版本、安装态和哈希漂移。"}


def _discover(workspace: Path) -> list[dict[str, Any]]:
    home = Path.home()
    roots = [
        ("codex", "global", home / ".codex" / "skills"),
        ("claude_code", "global", home / ".claude" / "skills"),
        ("codex", "project", workspace / ".codex" / "skills"),
        ("claude_code", "project", workspace / ".claude" / "skills"),
    ]
    entries: list[dict[str, Any]] = []
    for host, scope, root in roots:
        if not root.is_dir():
            continue
        for skill_file in sorted(root.glob("*/SKILL.md"))[:_MAX_ENTRIES - len(entries)]:
            entries.append(_entry("skill", host, scope, skill_file.parent.name, skill_file, "skill_folder"))
    for host, root in (("codex", home / ".codex" / "plugins"), ("claude_code", home / ".claude" / "plugins")):
        if root.is_dir():
            for plugin in sorted(path for path in root.iterdir() if path.is_dir())[:_MAX_ENTRIES - len(entries)]:
                entries.append(_entry("plugin", host, "global", plugin.name, plugin, "managed_directory"))
    for host, config in (("codex", home / ".codex" / "config.toml"), ("claude_code", home / ".claude.json")):
        if config.is_file() and len(entries) < _MAX_ENTRIES:
            entries.append(_entry("mcp_config", host, "global", config.name, config, "host_config"))
    return sorted(entries, key=lambda item: (item["kind"], item["host"], item["scope"], item["name"]))


def _entry(kind: str, host: str, scope: str, name: str, path: Path, install_mode: str) -> dict[str, Any]:
    stat = path.stat()
    content_hash = ""
    token_estimate = 0
    if path.is_file():
        raw = path.read_bytes()
        content_hash = hashlib.sha256(raw).hexdigest()
        token_estimate = max(1, len(raw.decode("utf-8", errors="ignore")) // 4) if kind == "skill" else 0
    return {"capability_id": f"{host}:{scope}:{kind}:{name}", "kind": kind, "host": host, "scope": scope, "name": name, "install_mode": install_mode, "source_evidence": "filesystem_observed", "content_hash": content_hash, "token_estimate": token_estimate, "modified_at": int(stat.st_mtime), "path_hint": _path_hint(path)}


def _path_hint(path: Path) -> str:
    home = str(Path.home())
    text = str(path)
    return "~" + text[len(home):] if text.startswith(home) else "workspace-relative"
