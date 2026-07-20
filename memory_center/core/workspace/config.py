from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from memory_center.core.foundation.models import ServiceConfig, WorkspaceConfig
from memory_center.core.workspace.kinds import detect_kind_from_path


def load_workspace_config(path: str | Path) -> WorkspaceConfig:
    """Load a Memory Center workspace configuration.

    Relative ``root`` values are resolved against the directory containing
    ``workspace.yaml``. This makes examples and checked-in workspaces portable.
    """
    config_path = Path(path).expanduser().resolve()
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    raw_root = data.get("root")
    if raw_root:
        root_path = Path(str(raw_root)).expanduser()
        if not root_path.is_absolute():
            root_path = (config_path.parent / root_path).resolve()
    else:
        root_path = config_path.parent.parent.resolve()
    services = [ServiceConfig(**item) for item in data.get("services", [])]
    return WorkspaceConfig(
        workspace=data.get("workspace", config_path.parent.name),
        root=str(root_path),
        services=services,
    )


def load_workspace_data(path: str | Path) -> dict[str, Any]:
    config_path = Path(path).expanduser().resolve()
    return yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}


def write_workspace_data(path: str | Path, data: dict[str, Any]) -> Path:
    config_path = Path(path).expanduser().resolve()
    config_path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return config_path


def write_default_workspace(
    root: str | Path,
    name: str,
    *,
    dry_run: bool = False,
) -> tuple[Path, dict[str, Any]]:
    """Create ``.memory-center/workspace.yaml``.

    The workspace root is scanned for recognizable service kinds (Spring/Python/Go/Node/Rust/…) and the
    resulting list is written into the yaml. When detection finds nothing,
    a workspace with an empty ``services: []`` list is written together
    with a help comment guiding the user to add entries by hand.

    Returns the path to the workspace file and a structured report
    describing what was detected / written. The report is intended for
    CLI/MCP callers that want to show a summary to the user.

    When ``dry_run`` is True the file is **not** written; the report still
    contains the proposed ``services`` so callers can preview the result.
    """
    root_path = Path(root).expanduser().resolve()
    ctx_dir = root_path / ".memory-center"
    workspace_file = ctx_dir / "workspace.yaml"

    services = _autodetect_services(root_path)
    detection_mode = "auto"

    report: dict[str, Any] = {
        "workspace_file": str(workspace_file),
        "root": str(root_path),
        "detection_mode": detection_mode,
        "service_count": len(services),
        "services": services,
        "dry_run": dry_run,
        "written": False,
        "already_exists": workspace_file.exists(),
    }

    if dry_run:
        return workspace_file, report

    ctx_dir.mkdir(parents=True, exist_ok=True)
    if workspace_file.exists():
        # Preserve any hand-edited workspace; detection result still
        # surfaces via the report so the caller can offer a diff.
        return workspace_file, report

    data: dict[str, Any] = {
        "workspace": name,
        "root": str(root_path),
        "language": ["zh-CN", "en-US"],
        "services": services,
    }
    workspace_file.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    report["written"] = True
    return workspace_file, report


def _autodetect_services(root: Path) -> list[dict[str, Any]]:
    """Scan ``root`` for buildable child directories and emit a service
    entry for each one that matches a registered kind.

    Detection rules:
    - Each immediate subdirectory of ``root`` is inspected.
    - Hidden directories (starting with ``.``) and a small set of common
      non-source directories (``node_modules``, ``target``, ``build``,
      ``dist``, ``out``, ``.venv``) are skipped.
    - When a child directory matches a kind, an entry is generated using
      the directory name for both ``name`` and ``path``.
    - When **no** child matches but ``root`` itself looks like a single
      module (e.g. a flat Python package or a C project), a single entry
      with ``path: "."`` is emitted using the detected kind.
    - When neither holds, an empty list is returned — callers should fall
      back to writing an empty ``services:`` list with a help comment.
    """
    detected: list[dict[str, Any]] = []
    if not root.exists() or not root.is_dir():
        return detected

    skip_dirs = {
        "node_modules", "target", "build", "dist", "out", ".venv",
        "venv", "__pycache__", ".git", ".idea", ".gradle",
        ".memory-center", ".claude",
    }

    for child in sorted(root.iterdir(), key=lambda item: item.name):
        if not child.is_dir():
            continue
        if child.name.startswith(".") or child.name in skip_dirs:
            continue
        kind = detect_kind_from_path(child)
        if kind is None:
            continue
        entry: dict[str, Any] = {
            "name": child.name,
            "path": child.name,
            "type": kind,
        }
        # Shared library convention: directories whose name looks like a
        # contract module ("*-api", "*-common", "*-core") get a tag the
        # downstream contract detector understands.
        lower = child.name.lower()
        if lower.endswith("-api"):
            entry["tags"] = ["contract"]
        elif lower.endswith(("-common", "-core")):
            entry["tags"] = ["common"]
        detected.append(entry)

    if detected:
        return detected

    # Flat-project fallback: the root itself is a single module.
    root_kind = detect_kind_from_path(root)
    if root_kind is not None:
        return [{"name": root.name, "path": ".", "type": root_kind}]

    return detected


def add_workspace_service(
    workspace_file: str | Path,
    name: str,
    path: str,
    service_type: str,
    service_name: str | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    data = load_workspace_data(workspace_file)
    services = [item for item in data.get("services", []) if item.get("name") != name]
    item: dict[str, Any] = {
        "name": name,
        "path": path,
        "type": service_type,
        "service_name": service_name or name,
    }
    if tags:
        item["tags"] = tags
    services.append(item)
    data["services"] = services
    write_workspace_data(workspace_file, data)
    return {"updated": True, "service": item, "service_count": len(services), "workspace_file": str(Path(workspace_file).expanduser().resolve())}


def remove_workspace_service(workspace_file: str | Path, name_or_path: str) -> dict[str, Any]:
    data = load_workspace_data(workspace_file)
    services = data.get("services", [])
    kept = [item for item in services if item.get("name") != name_or_path and item.get("path") != name_or_path]
    removed = [item for item in services if item.get("name") == name_or_path or item.get("path") == name_or_path]
    data["services"] = kept
    write_workspace_data(workspace_file, data)
    return {
        "updated": True,
        "removed": removed,
        "service_count": len(kept),
        "workspace_file": str(Path(workspace_file).expanduser().resolve()),
    }
