from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from .models import ServiceConfig, WorkspaceConfig


@dataclass(frozen=True)
class WorkspaceServiceEntry:
    index: int
    service: ServiceConfig
    name: str
    root: Path
    root_text: str


def collect_workspace_service_entries(config: WorkspaceConfig) -> List[WorkspaceServiceEntry]:
    entries: List[WorkspaceServiceEntry] = []
    for index, svc in enumerate(config.services):
        service_root = config.resolve_service_path(svc)
        if not service_root.exists():
            continue
        entries.append(
            WorkspaceServiceEntry(
                index=index,
                service=svc,
                name=svc.name,
                root=service_root,
                root_text=str(service_root),
            )
        )
    return entries


def is_path_within_root(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def select_primary_service_entry(
    path: Path,
    service_entries: List[WorkspaceServiceEntry],
) -> WorkspaceServiceEntry | None:
    candidates = [entry for entry in service_entries if is_path_within_root(path, entry.root)]
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: (-len(item.root_text), item.index))[0]


def analyze_workspace_shape(config: WorkspaceConfig) -> Dict[str, Any]:
    service_entries = collect_workspace_service_entries(config)
    duplicate_roots: Dict[str, List[str]] = {}
    for entry in service_entries:
        duplicate_roots.setdefault(entry.root_text, []).append(entry.name)

    nested_pairs: List[Dict[str, str]] = []
    for left in service_entries:
        for right in service_entries:
            if left.name == right.name:
                continue
            left_root = left.root_text.rstrip("/")
            right_root = right.root_text.rstrip("/")
            if right_root.startswith(left_root + "/"):
                nested_pairs.append(
                    {
                        "parent_service": left.name,
                        "parent_root": left.root_text,
                        "child_service": right.name,
                        "child_root": right.root_text,
                    }
                )

    duplicate_root_groups = [
        {"root": root, "services": names}
        for root, names in sorted(duplicate_roots.items())
        if len(names) > 1
    ]
    unique_root_count = len({entry.root_text for entry in service_entries})

    warnings: List[Dict[str, Any]] = []
    if duplicate_root_groups:
        warnings.append(
            {
                "code": "duplicate_service_roots",
                "severity": "medium",
                "message": f"发现 {len(duplicate_root_groups)} 组重复 service root，可能导致文件归属歧义和重复索引。",
                "group_count": len(duplicate_root_groups),
                "groups": duplicate_root_groups,
            }
        )
    if nested_pairs:
        warnings.append(
            {
                "code": "nested_service_roots",
                "severity": "medium" if not duplicate_root_groups else "high",
                "message": f"发现 {len(nested_pairs)} 组嵌套 service root，父子 service 可能同时覆盖同一批文件。",
                "pair_count": len(nested_pairs),
                "pairs": nested_pairs,
            }
        )

    warning_count = len(warnings)
    if warning_count == 0:
        risk_level = "low"
    elif any(item.get("severity") == "high" for item in warnings) or warning_count >= 2:
        risk_level = "high"
    else:
        risk_level = "medium"

    return {
        "service_count": len(service_entries),
        "unique_root_count": unique_root_count,
        "duplicate_root_group_count": len(duplicate_root_groups),
        "nested_service_pair_count": len(nested_pairs),
        "duplicate_root_groups": duplicate_root_groups,
        "nested_service_pairs": nested_pairs,
        "warning_count": warning_count,
        "risk_level": risk_level,
        "warnings": warnings,
    }
