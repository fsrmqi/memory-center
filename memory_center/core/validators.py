from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from .config import load_workspace_config
from .store import WorkspaceStore


def doctor(workspace_file: str | Path) -> Dict[str, Any]:
    """Validate workspace configuration and generated index health."""
    config = load_workspace_config(workspace_file)
    store = WorkspaceStore(workspace_file)
    checks: List[Dict[str, Any]] = []

    checks.append(_check("workspace_file_exists", Path(workspace_file).expanduser().exists(), str(workspace_file)))
    checks.append(_check("root_exists", config.root_path.exists(), str(config.root_path)))

    for service in config.services:
        path = config.root_path / service.path
        checks.append(_check(f"service_path:{service.name}", path.exists(), str(path)))

    for name in [
        "file-index.json",
        "java-symbol-index.json",
        "api-index.json",
        "feign-index.json",
        "mq-index.json",
        "config-index.json",
        "service-topology.json",
    ]:
        p = store.index_dir / name
        checks.append(_check(f"index:{name}", p.exists(), str(p)))

    failed = [item for item in checks if not item["ok"]]
    return {
        "workspace": config.workspace,
        "ok": not failed,
        "checks": checks,
        "hint": "Run `memory-center reindex --workspace <workspace.yaml>` after fixing failed checks." if failed else "Workspace looks ready.",
    }


def _check(name: str, ok: bool, detail: str) -> Dict[str, Any]:
    return {"name": name, "ok": bool(ok), "detail": detail}
