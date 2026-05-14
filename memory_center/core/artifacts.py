from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Dict, List

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
    return {
        "workspace": config.workspace,
        "appended": True,
        "name": "change_log",
        "file": filename,
        "path": str(path),
        "entry": entry.strip(),
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
