from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import ServiceConfig, WorkspaceConfig


@dataclass(frozen=True)
class WorkspaceServiceEntry:
    index: int
    service: ServiceConfig
    name: str
    root: Path
    root_text: str


def collect_workspace_service_entries(config: WorkspaceConfig) -> list[WorkspaceServiceEntry]:
    entries: list[WorkspaceServiceEntry] = []
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
    service_entries: list[WorkspaceServiceEntry],
) -> WorkspaceServiceEntry | None:
    candidates = [entry for entry in service_entries if is_path_within_root(path, entry.root)]
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: (-len(item.root_text), item.index))[0]


def analyze_workspace_shape(config: WorkspaceConfig) -> dict[str, Any]:
    service_entries = collect_workspace_service_entries(config)
    duplicate_roots: dict[str, list[str]] = {}
    for entry in service_entries:
        duplicate_roots.setdefault(entry.root_text, []).append(entry.name)

    nested_pairs: list[dict[str, str]] = []
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

    warnings: list[dict[str, Any]] = []
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

    recommendations = build_workspace_shape_recommendations(
        config,
        service_entries=service_entries,
        duplicate_root_groups=duplicate_root_groups,
        nested_pairs=nested_pairs,
    )

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
        "recommendations": recommendations,
    }


def build_workspace_shape_recommendations(
    config: WorkspaceConfig,
    *,
    service_entries: list[WorkspaceServiceEntry] | None = None,
    duplicate_root_groups: list[dict[str, Any]] | None = None,
    nested_pairs: list[dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    entries = service_entries or collect_workspace_service_entries(config)
    root_to_entry = {entry.root_text: entry for entry in entries}
    recommendations: list[dict[str, Any]] = []

    for group in duplicate_root_groups or []:
        services = list(group.get("services", []) or [])
        if len(services) < 2:
            continue
        keep_service = services[0]
        root_text = str(group.get("root", ""))
        submodules = _discover_submodule_candidates(root_to_entry.get(root_text).root if root_text in root_to_entry else Path(root_text), config)
        recommendations.append(
            {
                "code": "deduplicate_service_root_group",
                "priority": "high" if len(services) > 2 else "medium",
                "root": root_text,
                "keep_service": keep_service,
                "duplicate_services": services[1:],
                "suggested_actions": [
                    f"优先确认 `{keep_service}` 是否应作为该 root 的唯一 service 定义。",
                    "如果重复 service 代表不同子模块，请把它们的 path 收窄到真实子模块目录，而不是共享同一个根目录。",
                ],
                "candidate_narrower_paths": submodules[:8],
            }
        )

    nested_by_parent: dict[str, list[dict[str, str]]] = {}
    for pair in nested_pairs or []:
        nested_by_parent.setdefault(pair["parent_service"], []).append(pair)

    for parent_service, pairs in sorted(nested_by_parent.items()):
        parent_root = pairs[0]["parent_root"]
        submodules = _discover_submodule_candidates(Path(parent_root), config)
        child_services = sorted({pair["child_service"] for pair in pairs})
        recommendations.append(
            {
                "code": "narrow_parent_service_root",
                "priority": "high",
                "parent_service": parent_service,
                "parent_root": parent_root,
                "child_services": child_services,
                "suggested_actions": [
                    f"如果 `{parent_service}` 只是聚合目录，建议移除它的 service 定义，改由子模块 service 负责索引。",
                    f"如果 `{parent_service}` 仍需保留，请把 path 收窄到真正业务入口，避免覆盖 {len(child_services)} 个子 service。",
                ],
                "candidate_narrower_paths": submodules[:8],
            }
        )

    return recommendations


def _discover_submodule_candidates(root: Path, config: WorkspaceConfig) -> list[str]:
    if not root.exists() or not root.is_dir():
        return []
    candidates: list[str] = []
    for child in sorted(root.iterdir(), key=lambda item: item.name):
        if not child.is_dir():
            continue
        if child.name.startswith("."):
            continue
        if _looks_like_module_root(child):
            candidates.append(_to_workspace_relative_path(child, config))
    return candidates


def _looks_like_module_root(path: Path) -> bool:
    markers = [
        path / "src",
        path / "pom.xml",
        path / "build.gradle",
        path / "build.gradle.kts",
        path / "settings.gradle",
        path / "settings.gradle.kts",
    ]
    return any(marker.exists() for marker in markers)


def _to_workspace_relative_path(path: Path, config: WorkspaceConfig) -> str:
    resolved = path.expanduser().resolve()
    try:
        return resolved.relative_to(config.root_path).as_posix()
    except ValueError:
        return resolved.as_posix()
