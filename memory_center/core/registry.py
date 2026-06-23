from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


def registry_path(home: str | Path | None = None) -> Path:
    base = Path(home).expanduser() if home else (Path.home() / ".memory-center")
    base.mkdir(parents=True, exist_ok=True)
    return base / "registry.json"


def load_registry(home: str | Path | None = None) -> Dict[str, Any]:
    path = registry_path(home)
    if not path.exists():
        return {"version": "1.0", "repos": [], "groups": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"version": "1.0", "repos": [], "groups": []}


def save_registry(data: Dict[str, Any], home: str | Path | None = None) -> Path:
    path = registry_path(home)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def register_workspace(name: str, workspace_file: str | Path, home: str | Path | None = None) -> Dict[str, Any]:
    data = load_registry(home)
    ws = Path(workspace_file).expanduser().resolve()
    now = datetime.now(timezone.utc).isoformat()
    repos = [r for r in data.get("repos", []) if r.get("name") != name and r.get("workspace_file") != str(ws)]
    repos.append({"name": name, "workspace_file": str(ws), "path": str(ws.parent.parent), "last_registered_at": now})
    data["repos"] = repos
    save_registry(data, home)
    return {"registered": True, "name": name, "workspace_file": str(ws), "registry": str(registry_path(home))}


def list_workspaces(home: str | Path | None = None) -> List[Dict[str, Any]]:
    return load_registry(home).get("repos", [])


def list_groups(home: str | Path | None = None) -> List[Dict[str, Any]]:
    return load_registry(home).get("groups", [])


def create_group(name: str, members: List[str] | None = None, home: str | Path | None = None) -> Dict[str, Any]:
    data = load_registry(home)
    groups = [g for g in data.get("groups", []) if g.get("name") != name]
    groups.append({"name": name, "members": members or [], "created_at": datetime.now(timezone.utc).isoformat()})
    data["groups"] = groups
    save_registry(data, home)
    return {"created": True, "name": name, "members": members or []}


def add_to_group(group: str, repo_name: str, home: str | Path | None = None) -> Dict[str, Any]:
    data = load_registry(home)
    groups = data.setdefault("groups", [])
    target = None
    for g in groups:
        if g.get("name") == group:
            target = g
            break
    if target is None:
        target = {"name": group, "members": [], "created_at": datetime.now(timezone.utc).isoformat()}
        groups.append(target)
    if repo_name not in target.setdefault("members", []):
        target["members"].append(repo_name)
    save_registry(data, home)
    return {"group": group, "members": target["members"]}


def resolve_group(group: str, home: str | Path | None = None) -> Dict[str, Any]:
    data = load_registry(home)
    groups = {item.get("name"): item for item in data.get("groups", [])}
    repos = {item.get("name"): item for item in data.get("repos", [])}
    target = groups.get(group)
    if target is None:
        raise FileNotFoundError(f"Group not found: {group}")
    members = []
    missing = []
    for name in target.get("members", []):
        repo = repos.get(name)
        if repo:
            members.append(repo)
        else:
            missing.append(name)
    return {"group": group, "members": members, "missing": missing}


def resolve_workspace(name_or_path: str, home: str | Path | None = None) -> Path:
    p = Path(name_or_path).expanduser()
    if p.exists():
        return p.resolve()
    for repo in list_workspaces(home):
        if repo.get("name") == name_or_path:
            return Path(repo["workspace_file"]).expanduser().resolve()
    raise FileNotFoundError(f"Workspace not found: {name_or_path}")
