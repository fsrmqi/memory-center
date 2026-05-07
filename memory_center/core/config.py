from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import yaml

from .models import ServiceConfig, WorkspaceConfig


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


def write_default_workspace(root: str | Path, name: str) -> Path:
    """Create ``.memory-center/workspace.yaml`` with a Spring Cloud oriented template."""
    root_path = Path(root).expanduser().resolve()
    ctx_dir = root_path / ".memory-center"
    ctx_dir.mkdir(parents=True, exist_ok=True)
    workspace_file = ctx_dir / "workspace.yaml"
    if not workspace_file.exists():
        data: Dict[str, Any] = {
            "workspace": name,
            "root": str(root_path),
            "language": ["zh-CN", "en-US"],
            "services": [
                {"name": "gateway", "path": "gateway", "type": "spring-cloud-gateway", "service_name": "gateway"},
                {"name": "common-api", "path": "common-api", "type": "shared-library", "tags": ["contract"]},
                {"name": "common-core", "path": "common-core", "type": "shared-library", "tags": ["common"]},
            ],
        }
        workspace_file.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return workspace_file
