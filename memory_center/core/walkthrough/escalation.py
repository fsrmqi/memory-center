"""Workspace escalation helpers: parent / covering / sibling lookup, quality scoring."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List


__all__ = [
    "resolve_walkthrough_workspace_input",
    "find_parent_or_covering_workspace",
    "registry_covering_workspaces",
    "registry_group_sibling_workspaces",
    "path_is_within",
    "walkthrough_quality_score",
    "build_workspace_escalation_status",
    "walkthrough_index_signature",
    "walkthrough_recent_bypass_feedback",
]


def resolve_walkthrough_workspace_input(workspace_file: str | Path) -> Path:
    path = Path(workspace_file).expanduser()
    if path.is_file():
        return path.resolve()
    start = path.resolve() if path.exists() else Path.cwd().resolve()
    if start.name == ".memory-center":
        candidate = start / "workspace.yaml"
        if candidate.exists():
            return candidate.resolve()
    for parent in [start, *start.parents]:
        candidate = parent / ".memory-center" / "workspace.yaml"
        if candidate.exists():
            return candidate.resolve()
    return path.resolve()


def path_is_within(path: Path, maybe_parent: Path) -> bool:
    try:
        path.resolve().relative_to(maybe_parent.resolve())
        return True
    except ValueError:
        return False


def registry_covering_workspaces(current_ws: Path, current_root: Path) -> List[Path]:
    try:
        from ..registry import load_registry
        from ..orchestrator.common import load_context
    except Exception:
        return []
    out: List[Path] = []
    try:
        registry = load_registry()
    except Exception:
        return out
    for repo in registry.get("repos", []) or []:
        raw = repo.get("workspace_file", "")
        if not raw:
            continue
        candidate = Path(raw).expanduser().resolve()
        if candidate == current_ws or not candidate.exists():
            continue
        try:
            cfg = load_context(candidate)[0]
        except Exception:
            continue
        if path_is_within(current_root, cfg.root_path):
            out.append(candidate)
    return out


def registry_group_sibling_workspaces(current_ws: Path) -> List[Path]:
    try:
        from ..registry import load_registry
    except Exception:
        return []
    try:
        registry = load_registry()
    except Exception:
        return []
    repos = registry.get("repos", []) or []
    current_names = {
        repo.get("name", "")
        for repo in repos
        if str(Path(repo.get("workspace_file", "")).expanduser().resolve()) == str(current_ws)
    }
    if not current_names:
        return []
    sibling_names = set()
    for group in registry.get("groups", []) or []:
        members = set(group.get("members", []) or [])
        if members & current_names:
            sibling_names.update(members - current_names)
    out: List[Path] = []
    for repo in repos:
        if repo.get("name", "") not in sibling_names:
            continue
        raw = repo.get("workspace_file", "")
        if not raw:
            continue
        candidate = Path(raw).expanduser().resolve()
        if candidate != current_ws and candidate.exists():
            out.append(candidate)
    return out


def find_parent_or_covering_workspace(workspace_file: str | Path) -> Path | None:
    from ..orchestrator.common import load_context

    current_ws = Path(workspace_file).expanduser().resolve()
    try:
        current_config, _ = load_context(current_ws)
        current_root = current_config.root_path
    except Exception:
        current_root = current_ws.parent.parent.resolve()

    candidates: List[Path] = []
    for parent in [current_root, *current_root.parents]:
        candidate = parent / ".memory-center" / "workspace.yaml"
        if candidate.exists() and candidate.resolve() != current_ws:
            candidates.append(candidate.resolve())
    candidates.extend(registry_covering_workspaces(current_ws, current_root))
    candidates.extend(registry_group_sibling_workspaces(current_ws))

    unique: List[Path] = []
    seen = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    if not unique:
        return None

    def score(candidate: Path) -> tuple:
        try:
            cfg = load_context(candidate)[0]
            covers = 1 if path_is_within(current_root, cfg.root_path) else 0
            service_count = len(getattr(cfg, "services", []) or [])
            root_len = len(str(cfg.root_path))
            return (covers, service_count, -root_len)
        except Exception:
            return (0, 0, 0)

    unique.sort(key=score, reverse=True)
    return unique[0]


def walkthrough_quality_score(result: Dict[str, Any]) -> int:
    if not result or not result.get("found"):
        return 0
    score = 10
    score += len(result.get("local_service_continuations", []) or []) * 5
    score += len(result.get("same_class_method_continuations", []) or []) * 3
    for feign in result.get("feign_continuations", []) or []:
        servers = feign.get("server_walkthroughs", []) or []
        score += len(servers) * 8
        for server in servers:
            impls = server.get("service_impl_continuations", []) or []
            score += len(impls) * 10
            for impl in impls:
                score += len(impl.get("same_class_method_continuations", []) or []) * 4
                score += len(impl.get("feign_continuations", []) or []) * 4
    return score


def build_workspace_escalation_status(
    workspace_file: str | Path,
    status: str,
    candidate_workspace: str = "",
    reason: str = "",
) -> Dict[str, Any]:
    return {
        "status": status,
        "original_workspace_file": str(Path(workspace_file).expanduser().resolve()),
        "workspace_used": candidate_workspace or str(Path(workspace_file).expanduser().resolve()),
        "reason": reason,
        "fallback_safe": True,
    }


def walkthrough_index_signature(store: Any) -> Dict[str, float]:
    names = ["file-index.json", "java-symbol-index.json", "feign-index.json", "api-index.json", "graph-summary.json"]
    signature: Dict[str, float] = {}
    for name in names:
        path = getattr(store, "index_dir", Path()) / name
        try:
            signature[name] = path.stat().st_mtime
        except OSError:
            signature[name] = 0.0
    return signature


def walkthrough_recent_bypass_feedback(store: Any, session_events_file: str, limit: int = 200) -> Dict[str, Any]:
    import json as _json

    rows = store.read_jsonl_prefer_backend(session_events_file, limit=limit)
    patterns = ["find", "grep -l", "sed -n", "tool-results"]
    hits: List[Dict[str, Any]] = []
    for row in rows:
        payload = row.get("payload", {}) if isinstance(row.get("payload"), dict) else row
        text = _json.dumps(payload, ensure_ascii=False)
        tool_name = str(payload.get("tool_name") or row.get("tool_name") or "")
        if any(pattern in text or pattern in tool_name for pattern in patterns):
            hits.append({
                "event_type": row.get("event_type", ""),
                "tool_name": tool_name,
                "created_at": row.get("created_at", ""),
            })
    return {
        "checked_events": len(rows),
        "suspected_bypasses": len(hits),
        "patterns": patterns,
        "recent_hits": hits[-10:],
    }
