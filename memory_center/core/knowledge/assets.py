"""本地协作资产注册、共享审批与按角色上下文装载。"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from filelock import FileLock

from memory_center.core.storage.runtime import RuntimeStore
from memory_center.core.storage.workspace import WorkspaceStore
from memory_center.core.workspace.config import load_workspace_config

ASSET_REGISTRY_FILE = "collaboration-assets.json"
ASSET_KINDS = {"task", "skill", "wiki", "code_graph"}
VISIBILITIES = {"private", "team", "restricted"}
ASSET_STATUSES = {"draft", "pending_review", "active", "archived", "rejected"}
_MAX_ASSETS = 2_000
_MAX_LINKS = 80
_MAX_EVIDENCE = 30
_MAX_METADATA_BYTES = 16 * 1024
_DEFAULT_LOADOUT_CHARS = 12 * 1024
_MAX_LOADOUT_CHARS = 24 * 1024
_DEFAULT_STATUS_CHARS = 24 * 1024
SYSTEM_ASSET_OWNER = "workspace-system"


class AssetRegistryCorruptionError(RuntimeError):
    """协作资产 registry 无法安全恢复时中止写入，避免覆盖历史数据。"""


def register_collaboration_asset(
    workspace_file: str | Path,
    *,
    kind: str,
    title: str,
    owner: str,
    source_ref: str = "",
    visibility: str = "private",
    tags: list[str] | None = None,
    context_excerpt: str = "",
    metadata: dict[str, Any] | None = None,
    asset_id: str = "",
    actor: str = "",
) -> dict[str, Any]:
    """Create or update a local asset. Team sharing always starts pending review."""
    normalized_kind = _choice(kind, ASSET_KINDS, "kind")
    normalized_visibility = _choice(visibility, VISIBILITIES, "visibility")
    normalized_owner = _bounded(owner, 120) or "workspace-owner"
    normalized_title = _bounded(title, 200) or f"{normalized_kind} asset"
    store = WorkspaceStore(workspace_file)
    asset_id = _bounded(asset_id, 120) or _asset_id(normalized_kind, source_ref or normalized_title)
    update_actor = _bounded(actor, 120)
    if not update_actor:
        raise ValueError("actor is required when registering a collaboration asset")
    if update_actor != normalized_owner:
        raise PermissionError("asset actor must match the declared owner")
    normalized_metadata = _safe_metadata(metadata)
    if _json_size(normalized_metadata) > _MAX_METADATA_BYTES:
        raise ValueError(f"asset metadata exceeds {_MAX_METADATA_BYTES} bytes; store content externally and keep a source_ref")

    def mutate(registry: dict[str, Any]) -> dict[str, Any]:
        existing = next((item for item in registry["assets"] if item.get("asset_id") == asset_id), None)
        system_graph_migration = bool(
            existing
            and asset_id == "asset-code-graph-active"
            and normalized_kind == "code_graph"
            and update_actor == SYSTEM_ASSET_OWNER
        )
        if existing and update_actor != existing.get("owner") and not system_graph_migration:
            raise PermissionError("only the existing asset owner can update an asset")
        now = _now()
        visibility_changed = bool(existing and normalized_visibility != existing.get("visibility"))
        asset = {
            "schema_version": 1,
            "asset_id": asset_id,
            "kind": existing.get("kind", normalized_kind) if existing else normalized_kind,
            "title": normalized_title,
            "owner": SYSTEM_ASSET_OWNER if system_graph_migration else (existing.get("owner", normalized_owner) if existing else normalized_owner),
            "visibility": normalized_visibility,
            "status": ("pending_review" if normalized_visibility != "private" else "active") if not existing or visibility_changed else existing.get("status", "active"),
            "version": int((existing or {}).get("version", 0)) + 1,
            "source_ref": _bounded(source_ref, 300),
            "tags": _strings(tags, 20, 80),
            "context_excerpt": _bounded(context_excerpt, 800),
            "metadata": normalized_metadata,
            "allowed_agents": _strings((existing or {}).get("allowed_agents"), 50, 120),
            "allowed_roles": _strings((existing or {}).get("allowed_roles"), 30, 80),
            "approval": {} if visibility_changed else (existing or {}).get("approval", {}),
            "created_at": (existing or {}).get("created_at", now),
            "updated_at": now,
        }
        if existing:
            registry["assets"][registry["assets"].index(existing)] = asset
        else:
            registry["assets"].append(asset)
        return asset

    asset = _mutate_registry(store, mutate)
    return {"registered": True, "asset": asset, "next_action": "私有资产可直接绑定；团队或受限资产需 asset_approve 后才可装载。"}


def submit_asset_for_sharing(workspace_file: str | Path, asset_id: str, *, visibility: str, actor: str, allowed_agents: list[str] | None = None, allowed_roles: list[str] | None = None) -> dict[str, Any]:
    store = WorkspaceStore(workspace_file)
    def mutate(registry: dict[str, Any]) -> dict[str, Any] | None:
        asset = _find_asset(registry, asset_id)
        if not asset or _bounded(actor, 120) != asset["owner"]:
            return None
        shared_visibility = _choice(visibility, VISIBILITIES, "visibility")
        if shared_visibility == "private":
            return None
        asset["visibility"] = shared_visibility
        asset["allowed_agents"] = _strings(allowed_agents, 50, 120)
        asset["allowed_roles"] = _strings(allowed_roles, 30, 80)
        asset["status"] = "pending_review"
        asset["approval"] = {"submitted_by": _bounded(actor, 120), "submitted_at": _now()}
        asset["updated_at"] = _now()
        return asset

    asset = _mutate_registry(store, mutate)
    if not asset:
        return {"submitted": False, "reason": "asset_not_found_or_owner_required", "next_action": "确认 asset_id 且仅由资产 owner 提交共享。"}
    return {"submitted": True, "asset": asset, "next_action": "由团队维护者使用 asset_approve 审核；审核前不会进入任何 Agent 装载。"}


def approve_collaboration_asset(workspace_file: str | Path, asset_id: str, *, approved: bool, actor: str, note: str = "") -> dict[str, Any]:
    store = WorkspaceStore(workspace_file)
    approver = _bounded(actor, 120)
    if not approver:
        return {"approved": False, "reason": "approver_required", "next_action": "审批必须记录操作人。"}
    def mutate(registry: dict[str, Any]) -> dict[str, Any] | None:
        asset = _find_asset(registry, asset_id)
        if not asset:
            return None
        if approver == asset.get("owner"):
            raise PermissionError("asset owner cannot approve its own sharing request")
        if asset.get("visibility") == "private" or asset.get("status") != "pending_review":
            return None
        asset["status"] = "active" if approved else "rejected"
        asset["approval"] = {**asset.get("approval", {}), "approved": bool(approved), "approved_by": approver, "approved_at": _now(), "note": _bounded(note, 500)}
        asset["updated_at"] = _now()
        return asset

    asset = _mutate_registry(store, mutate)
    if not asset:
        return {"approved": False, "reason": "asset_not_pending_review", "next_action": "先由 owner 提交 team 或 restricted 共享申请。"}
    return {"approved": bool(approved), "asset": asset, "next_action": "资产已可按绑定范围装载。" if approved else "修订资产后可重新提交审核。"}


def bind_collaboration_asset(workspace_file: str | Path, asset_id: str, *, actor: str, agents: list[str] | None = None, roles: list[str] | None = None) -> dict[str, Any]:
    store = WorkspaceStore(workspace_file)
    def mutate(registry: dict[str, Any]) -> dict[str, Any] | None:
        asset = _find_asset(registry, asset_id)
        if not asset or _bounded(actor, 120) != asset["owner"] or asset["status"] != "active":
            return None
        asset["allowed_agents"] = _strings(agents, 50, 120)
        asset["allowed_roles"] = _strings(roles, 30, 80)
        asset["updated_at"] = _now()
        return asset

    asset = _mutate_registry(store, mutate)
    if not asset:
        return {"bound": False, "reason": "asset_not_found_or_not_active_or_owner_required", "next_action": "确认 asset_id、激活状态及 owner。"}
    return {"bound": True, "asset": asset, "next_action": "Agent 下一次 context pack 会按绑定范围读取资产摘要。"}


def collaboration_asset_loadout(workspace_file: str | Path, *, agent_id: str = "", role: str = "", limit: int = 12, max_chars: int = _DEFAULT_LOADOUT_CHARS) -> dict[str, Any]:
    store = WorkspaceStore(workspace_file)
    agent, normalized_role = _bounded(agent_id, 120), _bounded(role, 80)
    visible = [asset for asset in _read_registry(store)["assets"] if _asset_visible(asset, agent, normalized_role)]
    visible.sort(key=lambda item: (item["kind"] != "skill", item["title"], item["asset_id"]))
    items = []
    budget = _normalize_budget(max_chars, _DEFAULT_LOADOUT_CHARS, _MAX_LOADOUT_CHARS)
    remaining = budget
    truncated = False
    for asset in visible[:max(1, min(limit, 50))]:
        item = _asset_summary(asset)
        encoded = json.dumps(item, ensure_ascii=False)
        if remaining and len(encoded) > remaining:
            item["context_excerpt"] = _bounded(str(item.get("context_excerpt", "")), max(0, remaining // 3))
            item["metadata"] = {"truncated": True, "source_ref": item.get("source_ref", "")}
            encoded = json.dumps(item, ensure_ascii=False)
        if remaining and len(encoded) > remaining:
            truncated = True
            continue
        items.append(item)
        if remaining:
            remaining -= len(encoded)
    if len(items) < min(len(visible), max(1, min(limit, 50))):
        truncated = True
    return {"agent_id": agent, "role": normalized_role, "assets": items, "count": len(items), "max_chars": budget, "truncated": truncated, "next_action": "优先读取 Skill 的契约和 Wiki/CodeGraph 的来源引用；未命中资产时走默认图谱检索。"}


def collaboration_asset_status(workspace_file: str | Path, *, limit: int = 100, max_chars: int = _DEFAULT_STATUS_CHARS) -> dict[str, Any]:
    store = WorkspaceStore(workspace_file)
    assets = _read_registry(store)["assets"]
    counts = {kind: sum(asset.get("kind") == kind for asset in assets) for kind in sorted(ASSET_KINDS)}
    budget = _normalize_budget(max_chars, _DEFAULT_STATUS_CHARS, _MAX_LOADOUT_CHARS)
    selected = assets[-max(1, min(limit, 200)):]
    summaries, truncated = _bounded_summaries(selected, budget)
    return {"assets": summaries, "counts": counts, "pending_review": sum(item.get("status") == "pending_review" for item in assets), "max_chars": budget, "truncated": truncated}


def sync_workspace_collaboration_assets(workspace_file: str | Path, *, owner: str = "") -> dict[str, Any]:
    """Register current task, published Skill, and code graph metadata without copying content."""
    store = WorkspaceStore(workspace_file)
    owner = _bounded(owner, 120) or "workspace-owner"
    created: list[str] = []
    from memory_center.core.tasks.artifacts import list_task_spaces

    task_index = list_task_spaces(workspace_file, include_archived=True)
    for task in [*task_index.get("active_tasks", []), *task_index.get("archived_tasks", [])]:
        task_owner = str(task.get("owner", "")) or owner
        result = register_collaboration_asset(workspace_file, kind="task", title=str(task.get("title", "任务")), owner=task_owner, source_ref=f"task:{task.get('task_id', '')}", metadata={"task_id": task.get("task_id", ""), "status": task.get("status", "")}, actor=task_owner)
        created.append(result["asset"]["asset_id"])
    try:
        registry = json.loads(store.read_artifact("skills/delivery-skill-registry.json", ""))
    except json.JSONDecodeError:
        registry = {"skills": []}
    if not isinstance(registry, dict):
        registry = {"skills": []}
    for skill in registry.get("skills", []):
        if skill.get("lifecycle") != "published":
            continue
        skill_owner = str(skill.get("actor", "")) or owner
        result = register_collaboration_asset(workspace_file, kind="skill", title=str(skill.get("title", "Delivery Skill")), owner=skill_owner, source_ref=f"skill:{skill.get('skill_id', '')}", metadata={"skill_id": skill.get("skill_id", ""), "contract": skill.get("contract", {}), "evidence_refs": skill.get("evidence_refs", [])[:_MAX_EVIDENCE]}, asset_id=f"asset-skill-{_bounded(str(skill.get('skill_id', '')), 80)}", actor=skill_owner)
        created.append(result["asset"]["asset_id"])
    config = load_workspace_config(workspace_file)
    with RuntimeStore(store.graph_db_path) as graph:
        counts = graph.counts()
    result = register_collaboration_asset(workspace_file, kind="code_graph", title=f"{config.workspace} CodeGraph", owner=SYSTEM_ASSET_OWNER, source_ref="graph:active", visibility="team", metadata={"counts": counts, "workspace": config.workspace}, context_excerpt="代码图谱资产：通过 mc_lookup、mc_context_pack 与 mc_analyze 按需读取。", asset_id="asset-code-graph-active", actor=SYSTEM_ASSET_OWNER)
    created.append(result["asset"]["asset_id"])
    return {"synced": True, "asset_ids": created, "next_action": "团队共享资产仍需提交并审批；私有资产可直接绑定。"}


def ingest_wiki_document_asset(workspace_file: str | Path, document_path: str | Path, *, owner: str, visibility: str = "private", tags: list[str] | None = None) -> dict[str, Any]:
    """Register a bounded Markdown document graph node with graph-backed code evidence."""
    config = load_workspace_config(workspace_file)
    path = Path(document_path).expanduser().resolve()
    root = Path(config.root).resolve()
    if path.suffix.lower() not in {".md", ".markdown", ".txt", ".rst"} or not path.is_file() or root not in path.parents:
        return {"ingested": False, "reason": "document_must_be_a_workspace_text_file", "next_action": "只允许注册 workspace 根目录内的 Markdown、文本或 RST 文档。"}
    text = path.read_text(encoding="utf-8", errors="ignore")[:256 * 1024]
    relative = str(path.relative_to(root))
    title = next((line.lstrip("# ").strip() for line in text.splitlines() if line.startswith("#")), path.stem)
    links = _document_links(text)[:_MAX_LINKS]
    symbols = _document_symbols(text)[:30]
    store = WorkspaceStore(workspace_file)
    evidence = []
    with RuntimeStore(store.graph_db_path) as graph:
        for symbol in symbols:
            for node in graph.find_nodes(symbol, limit=3):
                evidence.append({"node_id": node.get("id", ""), "name": node.get("name", ""), "type": node.get("type", ""), "file_path": node.get("file_path", "")})
    excerpt = " ".join(line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#"))[:800]
    result = register_collaboration_asset(workspace_file, kind="wiki", title=title, owner=owner, source_ref=f"wiki:{relative}", visibility=visibility, tags=tags, context_excerpt=excerpt, metadata={"path": relative, "content_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()[:20], "links": links, "code_evidence": _dedupe_evidence(evidence)[:_MAX_EVIDENCE]}, asset_id=_asset_id("wiki", relative), actor=owner)
    return {"ingested": True, "asset": result["asset"], "document_graph": {"path": relative, "links": links, "code_evidence": result["asset"]["metadata"]["code_evidence"]}, "next_action": "需要共享时提交 asset_share 并由维护者审批；上下文包只装载摘要和证据引用。"}


def _read_registry(store: WorkspaceStore) -> dict[str, Any]:
    path = store.artifacts_dir / ASSET_REGISTRY_FILE
    backup = _registry_backup_path(path)
    if not path.exists():
        return {"schema_version": 1, "assets": []}
    value = _parse_registry(path)
    if value is None:
        value = _parse_registry(backup)
        if value is None:
            raise AssetRegistryCorruptionError("collaboration asset registry is invalid; preserve the file and restore it from a backup before writing")
    return {"schema_version": 1, "assets": [item for item in value["assets"] if isinstance(item, dict)][-_MAX_ASSETS:]}


def _write_registry(store: WorkspaceStore, registry: dict[str, Any]) -> None:
    registry["updated_at"] = _now()
    registry["assets"] = registry.get("assets", [])[-_MAX_ASSETS:]
    path = store.artifacts_dir / ASSET_REGISTRY_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = _registry_backup_path(path)
    if path.exists() and _parse_registry(path) is not None:
        shutil.copy2(path, backup)
    payload = json.dumps(registry, ensure_ascii=False, indent=2) + "\n"
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _mutate_registry(store: WorkspaceStore, operation):
    with FileLock(str(store.artifact_lock_file)):
        registry = _read_registry(store)
        result = operation(registry)
        _write_registry(store, registry)
        return result


def _find_asset(registry: dict[str, Any], asset_id: str) -> dict[str, Any] | None:
    return next((item for item in registry["assets"] if item.get("asset_id") == asset_id), None)


def _parse_registry(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) and isinstance(value.get("assets"), list) else None


def _registry_backup_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.bak")


def _json_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _normalize_budget(value: int, default: int, maximum: int) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        normalized = default
    return min(maximum, normalized if normalized > 0 else default)


def _bounded_summaries(assets: list[dict[str, Any]], budget: int) -> tuple[list[dict[str, Any]], bool]:
    summaries: list[dict[str, Any]] = []
    remaining = budget
    for asset in assets:
        summary = _asset_summary(asset)
        encoded = json.dumps(summary, ensure_ascii=False)
        if len(encoded) > remaining:
            summary["context_excerpt"] = _bounded(str(summary.get("context_excerpt", "")), max(0, remaining // 3))
            summary["metadata"] = {"truncated": True, "source_ref": summary.get("source_ref", "")}
            encoded = json.dumps(summary, ensure_ascii=False)
        if len(encoded) > remaining:
            return summaries, True
        summaries.append(summary)
        remaining -= len(encoded)
    return summaries, False


def _asset_visible(asset: dict[str, Any], agent_id: str, role: str) -> bool:
    if asset.get("status") != "active":
        return False
    visibility = asset.get("visibility")
    if visibility == "team":
        agents, roles = asset.get("allowed_agents", []), asset.get("allowed_roles", [])
        return not agents and not roles or (bool(agent_id) and agent_id in agents) or (bool(role) and role in roles)
    if visibility == "private":
        return bool(agent_id and (agent_id == asset.get("owner") or agent_id in asset.get("allowed_agents", []))) or (bool(role) and role in asset.get("allowed_roles", []))
    return (bool(agent_id) and agent_id in asset.get("allowed_agents", [])) or (bool(role) and role in asset.get("allowed_roles", []))


def _asset_summary(asset: dict[str, Any]) -> dict[str, Any]:
    return {key: asset.get(key) for key in ("asset_id", "kind", "title", "owner", "visibility", "status", "version", "source_ref", "tags", "context_excerpt", "metadata")}


def _asset_id(kind: str, source: str) -> str:
    return f"asset-{kind}-{hashlib.sha256(source.encode('utf-8')).hexdigest()[:16]}"


def _choice(value: str, allowed: set[str], field: str) -> str:
    normalized = str(value).strip().lower()
    if normalized not in allowed:
        raise ValueError(f"{field} must be one of: {', '.join(sorted(allowed))}")
    return normalized


def _strings(value: Any, limit: int, width: int) -> list[str]:
    values = value if isinstance(value, list) else []
    return list(dict.fromkeys(_bounded(str(item), width) for item in values if str(item).strip()))[:limit]


def _safe_metadata(value: dict[str, Any] | None) -> dict[str, Any]:
    def sanitize(item: Any, depth: int = 0) -> Any:
        if depth > 3:
            return "<truncated>"
        if isinstance(item, dict):
            return {str(key)[:80]: sanitize(child, depth + 1) for key, child in list(item.items())[:40]}
        if isinstance(item, list):
            return [sanitize(child, depth + 1) for child in item[:40]]
        if isinstance(item, str):
            return _bounded(item, 800)
        if isinstance(item, (int, float, bool)) or item is None:
            return item
        return _bounded(str(item), 800)

    return sanitize(value if isinstance(value, dict) else {})


def _bounded(value: str, limit: int) -> str:
    return str(value).strip()[:limit]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _document_links(text: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r"\[[^\]]+\]\(([^)#]+)(?:#[^)]+)?\)", text)))


def _document_symbols(text: str) -> list[str]:
    values = re.findall(r"`([A-Za-z_][\w.$]*(?:#[A-Za-z_]\w*)?)`", text)
    return list(dict.fromkeys(values))


def _dedupe_evidence(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result = []
    for item in items:
        marker = str(item.get("node_id", ""))
        if marker and marker not in seen:
            seen.add(marker)
            result.append(item)
    return result
