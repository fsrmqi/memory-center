"""Lookup scope resolution: active project inference and bounded stale refresh."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .shared import load_context


def infer_project_from_workspace_context(workspace_file: str | Path) -> str:
    try:
        config, _store = load_context(workspace_file)
    except Exception:
        return ""
    cwd = Path.cwd().expanduser().resolve()
    candidates: list[tuple[int, str]] = []
    for service in getattr(config, "services", []) or []:
        try:
            relative = cwd.relative_to(config.resolve_service_path(service))
        except Exception:
            continue
        candidates.append((len(relative.parts), str(service.name or "")))
    if not candidates:
        return ""
    candidates.sort(key=lambda item: (-item[0], item[1]))
    return candidates[0][1]


def resolve_effective_project(workspace_file: str | Path, project: str = "") -> dict[str, str]:
    explicit = project.strip()
    if explicit:
        return {"project": explicit, "source": "explicit"}
    inferred = infer_project_from_workspace_context(workspace_file)
    return {"project": inferred, "source": "active_service_root" if inferred else "none"}


def refresh_scoped_query_if_stale(
    workspace_file: str | Path, query: str, project: str, *, freshness_status: str = "",
) -> dict[str, Any]:
    if not project:
        return {"attempted": False, "reason": "no_project_scope"}
    if freshness_status not in {"stale", "pending"}:
        return {"attempted": False, "reason": "index_current"}
    try:
        from ..freshness.targeted_refresh import refresh_query_targets

        return {"attempted": True, **refresh_query_targets(workspace_file, query, limit=4)}
    except Exception as exc:
        return {"attempted": True, "refreshed": False, "reason": f"refresh_unavailable:{type(exc).__name__}"}


__all__ = ["infer_project_from_workspace_context", "resolve_effective_project", "refresh_scoped_query_if_stale"]
