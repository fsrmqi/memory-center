from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from memory_center.core.storage.runtime import RuntimeStore
from memory_center.core.storage.workspace import WorkspaceStore
from memory_center.core.workspace.config import load_workspace_config

WIKI_MANIFEST_FILE = "wiki-manifest.json"
WIKI_PROFILE_FILE = "wiki-profile.json"
L3_BRIDGE_DIR = "semantic-bridge"


def generate_wiki(
    workspace_file: str | Path,
    output_dir: str | Path | None = None,
    *,
    dirty_paths: list[str] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Generate or incrementally refresh the three-level project map.

    L1: workspace/module overview (bounded, always regenerated)
    L2: per-module symbol map (regenerated only for dirty modules)
    L3: semantic bridge (business terms, contracts, config keys -> code entities)

    Args:
        dirty_paths: If provided, only regenerate modules affected by these paths.
        force: Force full regeneration regardless of manifest state.
    """
    config, store = load_workspace_config(workspace_file), WorkspaceStore(workspace_file)
    out = Path(output_dir) if output_dir else store.base_dir / "wiki"
    out.mkdir(parents=True, exist_ok=True)
    generation_id = f"gen-{int(time.time())}-{sha256(str(time.time()).encode()).hexdigest()[:8]}"
    now = datetime.now(timezone.utc).isoformat()
    profile = _load_wiki_profile(store)
    manifest = _load_wiki_manifest(store)
    topology = store.read_json_prefer_backend("service-topology.json", {})
    cases = store.read_jsonl_prefer_backend("cross-service-task-memory.jsonl", limit=1000)
    dirty_modules = _resolve_dirty_modules(dirty_paths, config) if dirty_paths else None
    with RuntimeStore(store.graph_db_path) as graph:
        status = {"workspace": config.workspace, "index_counts": graph.counts()}

    # L1: Always regenerate overview (bounded, lightweight)
    (out / "overview.md").write_text(_overview(config.workspace, status, topology), encoding="utf-8")

    # L2: Regenerate only dirty modules or all if force/no dirty_paths
    service_dir = out / "services"
    service_dir.mkdir(exist_ok=True)
    module_manifest: list[dict[str, Any]] = []
    refreshed_modules: list[str] = []
    skipped_modules: list[str] = []

    for svc in topology.get("services", []):
        name = str(svc["name"])
        should_refresh = force or dirty_modules is None or name in dirty_modules
        existing_entry = next((m for m in manifest.get("modules", []) if m.get("module") == name), None)

        if not should_refresh and existing_entry:
            # Reuse existing entry, mark as not stale
            module_manifest.append({**existing_entry, "last_checked_at": now, "stale": False})
            skipped_modules.append(name)
            continue

        (service_dir / f"{name}.md").write_text(_service_page(svc, topology), encoding="utf-8")
        with RuntimeStore(store.graph_db_path) as graph:
            nodes, _ = graph.project_subgraph(name)
        module_path = out / "modules" / f"{name}.md"
        module_path.parent.mkdir(exist_ok=True)
        module_path.write_text(_module_page(name, nodes), encoding="utf-8")
        input_hash = sha256("|".join(node.id for node in nodes).encode()).hexdigest()[:16]
        module_manifest.append({
            "module": name,
            "path": str(module_path.relative_to(out)),
            "node_count": len(nodes),
            "input_hash": input_hash,
            "generation_id": generation_id,
            "generated_at": now,
            "last_checked_at": now,
            "stale": False,
            "profile": profile.get("profile_id", "default"),
        })
        refreshed_modules.append(name)

    # L3: Generate semantic bridge
    bridge_dir = out / L3_BRIDGE_DIR
    bridge_dir.mkdir(exist_ok=True)
    bridge_result = _generate_semantic_bridge(store, config, topology, bridge_dir, profile, generation_id, now)

    # Write manifest with generation tracking
    manifest_payload = {
        "schema_version": 2,
        "generation_id": generation_id,
        "generated_at": now,
        "workspace": config.workspace,
        "profile": profile.get("profile_id", "default"),
        "modules": module_manifest,
        "refresh_stats": {
            "refreshed": refreshed_modules,
            "skipped": skipped_modules,
            "dirty_paths": dirty_paths or [],
            "force": force,
        },
        "semantic_bridge": bridge_result,
    }
    (out / "module-manifest.json").write_text(json.dumps(manifest_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    store.write_json(WIKI_MANIFEST_FILE, manifest_payload)
    (out / "memory.md").write_text(_memory_page(cases), encoding="utf-8")

    return {
        "generated": True,
        "generation_id": generation_id,
        "output_dir": str(out),
        "files": [str(p.relative_to(out)) for p in out.rglob("*.md")],
        "modules": module_manifest,
        "refresh_stats": manifest_payload["refresh_stats"],
        "semantic_bridge": bridge_result,
        "profile": profile.get("profile_id", "default"),
    }


def wiki_status(workspace_file: str | Path) -> dict[str, Any]:
    """Return the current wiki manifest and staleness information."""
    store = WorkspaceStore(workspace_file)
    manifest = _load_wiki_manifest(store)
    if not manifest:
        return {"generated": False, "next_action": "执行 generate-wiki 生成项目地图。"}
    stale_modules = [m["module"] for m in manifest.get("modules", []) if m.get("stale")]
    return {
        "generated": True,
        "generation_id": manifest.get("generation_id", ""),
        "generated_at": manifest.get("generated_at", ""),
        "profile": manifest.get("profile", "default"),
        "module_count": len(manifest.get("modules", [])),
        "stale_modules": stale_modules,
        "has_stale": bool(stale_modules),
        "next_action": "部分模块地图已过期，建议执行 generate-wiki --dirty-paths 定向刷新。" if stale_modules else "地图新鲜，可直接使用。",
    }


def mark_wiki_modules_stale(workspace_file: str | Path, dirty_paths: list[str]) -> dict[str, Any]:
    """Mark modules as stale when their source files change."""
    store = WorkspaceStore(workspace_file)
    config = load_workspace_config(workspace_file)
    manifest = _load_wiki_manifest(store)
    if not manifest:
        return {"marked": 0, "reason": "wiki_not_generated"}
    dirty_modules = _resolve_dirty_modules(dirty_paths, config)
    marked = []
    for module in manifest.get("modules", []):
        if module.get("module") in dirty_modules:
            module["stale"] = True
            module["stale_since"] = datetime.now(timezone.utc).isoformat()
            marked.append(module["module"])
    store.write_json(WIKI_MANIFEST_FILE, manifest)
    return {"marked": len(marked), "modules": marked, "dirty_paths": dirty_paths}


def get_l1_context(workspace_file: str | Path, *, budget: str = "medium") -> dict[str, Any]:
    """Return bounded L1 overview as lightweight context for task positioning.

    L1 is always fresh (regenerated on each call) and bounded by budget.
    """
    config, store = load_workspace_config(workspace_file), WorkspaceStore(workspace_file)
    topology = store.read_json_prefer_backend("service-topology.json", {})
    services = topology.get("services", [])
    budget_limits = {"small": 5, "medium": 15, "large": 50}
    limit = budget_limits.get(budget, 15)
    with RuntimeStore(store.graph_db_path) as graph:
        counts = graph.counts()
    return {
        "level": "L1",
        "workspace": config.workspace,
        "service_count": len(services),
        "services": [{"name": s.get("name"), "type": s.get("type"), "service_name": s.get("service_name")} for s in services[:limit]],
        "index_counts": counts,
        "truncated": len(services) > limit,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "usage": "作为任务定位的默认轻量上下文；确定候选模块后再读取 L2。",
    }


def get_l2_context(workspace_file: str | Path, module: str, *, budget: str = "medium") -> dict[str, Any]:
    """Return L2 module map for one specific module."""
    store = WorkspaceStore(workspace_file)
    manifest = _load_wiki_manifest(store)
    entry = next((m for m in manifest.get("modules", []) if m.get("module") == module), None)
    if not entry:
        return {"level": "L2", "module": module, "found": False, "next_action": f"模块 {module} 未在地图中；先执行 generate-wiki。"}
    out = store.base_dir / "wiki"
    module_path = out / entry.get("path", "")
    content = module_path.read_text(encoding="utf-8") if module_path.exists() else ""
    return {
        "level": "L2",
        "module": module,
        "found": True,
        "stale": entry.get("stale", False),
        "generation_id": entry.get("generation_id", ""),
        "generated_at": entry.get("generated_at", ""),
        "node_count": entry.get("node_count", 0),
        "content": content[:10000] if budget != "large" else content,
        "truncated": len(content) > 10000 and budget != "large",
        "next_action": "地图已过期，建议先刷新再使用。" if entry.get("stale") else "",
    }


def get_l3_bridge(workspace_file: str | Path, *, query: str = "", bridge_type: str = "") -> dict[str, Any]:
    """Query the L3 semantic bridge for business terms, contracts, or config keys."""
    store = WorkspaceStore(workspace_file)
    out = store.base_dir / "wiki" / L3_BRIDGE_DIR
    if not out.exists():
        return {"level": "L3", "found": False, "next_action": "语义桥未生成；先执行 generate-wiki。"}
    bridges: list[dict[str, Any]] = []
    for bridge_file in out.glob("*.json"):
        try:
            data = json.loads(bridge_file.read_text(encoding="utf-8"))
            if isinstance(data, list):
                bridges.extend(data)
        except (json.JSONDecodeError, OSError):
            continue
    if bridge_type:
        bridges = [b for b in bridges if b.get("bridge_type") == bridge_type]
    if query:
        query_lower = query.lower()
        bridges = [b for b in bridges if query_lower in b.get("term", "").lower() or query_lower in str(b.get("targets", [])).lower()]
    return {
        "level": "L3",
        "found": bool(bridges),
        "count": len(bridges),
        "bridges": bridges[:50],
        "query": query,
        "bridge_type": bridge_type,
    }


def update_wiki_profile(workspace_file: str | Path, profile: dict[str, Any], *, actor: str = "") -> dict[str, Any]:
    """Update the workspace wiki profile for semantic bridge customization."""
    store = WorkspaceStore(workspace_file)
    normalized = _normalize_wiki_profile(profile)
    normalized["updated_at"] = datetime.now(timezone.utc).isoformat()
    normalized["actor"] = actor[:120] if actor else ""
    store.write_json(WIKI_PROFILE_FILE, normalized)
    return {"updated": True, "profile": normalized}


def _load_wiki_manifest(store: WorkspaceStore) -> dict[str, Any]:
    return store.read_json_prefer_backend(WIKI_MANIFEST_FILE, {}) or {}


def _load_wiki_profile(store: WorkspaceStore) -> dict[str, Any]:
    return store.read_json_prefer_backend(WIKI_PROFILE_FILE, _default_wiki_profile())


def _default_wiki_profile() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "profile_id": "default",
        "semantic_bridge_rules": {
            "business_terms": True,
            "interface_contracts": True,
            "config_keys": True,
            "design_patterns": False,
        },
        "custom_mappings": [],
    }


def _normalize_wiki_profile(raw: dict[str, Any]) -> dict[str, Any]:
    rules = raw.get("semantic_bridge_rules", {})
    return {
        "schema_version": 1,
        "profile_id": str(raw.get("profile_id", "default"))[:80] or "default",
        "semantic_bridge_rules": {
            "business_terms": bool(rules.get("business_terms", True)),
            "interface_contracts": bool(rules.get("interface_contracts", True)),
            "config_keys": bool(rules.get("config_keys", True)),
            "design_patterns": bool(rules.get("design_patterns", False)),
        },
        "custom_mappings": [
            {"term": str(m.get("term", ""))[:100], "targets": [str(t)[:200] for t in m.get("targets", [])][:20], "bridge_type": str(m.get("bridge_type", "custom"))[:40]}
            for m in raw.get("custom_mappings", [])[:50]
            if isinstance(m, dict) and m.get("term")
        ],
    }


def _resolve_dirty_modules(dirty_paths: list[str], config: Any) -> set[str]:
    """Map dirty file paths to affected module names.

    Matches by relative service-path prefix first, then falls back to path
    segment overlap (service name or service path leaf appearing as a segment
    of the dirty path), so both workspace-relative and absolute dirty paths work.
    """
    dirty_modules: set[str] = set()
    for service in config.services:
        service_path = str(service.path).replace("\\", "/").strip("/")
        segments = [seg for seg in service_path.split("/") if seg]
        if not segments:
            continue
        leaf = segments[-1]
        for dirty_path in dirty_paths:
            normalized = str(dirty_path).replace("\\", "/").strip()
            parts = [p for p in normalized.split("/") if p]
            if not parts:
                continue
            if normalized == service_path or normalized.startswith(service_path + "/"):
                dirty_modules.add(service.name)
            elif service.name in parts or leaf in parts:
                dirty_modules.add(service.name)
    return dirty_modules


def _generate_semantic_bridge(
    store: WorkspaceStore,
    config: Any,
    topology: dict[str, Any],
    bridge_dir: Path,
    profile: dict[str, Any],
    generation_id: str,
    now: str,
) -> dict[str, Any]:
    """Generate L3 semantic bridge: business terms, contracts, config keys -> code entities."""
    rules = profile.get("semantic_bridge_rules", {})
    bridges: list[dict[str, Any]] = []

    # Interface contracts bridge (Feign clients, endpoints)
    if rules.get("interface_contracts", True):
        for feign_edge in topology.get("feign_edges", []):
            bridges.append({
                "bridge_type": "interface_contract",
                "term": f"{feign_edge.get('from_project', '')} -> {feign_edge.get('to_project', '')}",
                "targets": [feign_edge.get("feign_client", ""), feign_edge.get("method", "")],
                "source": "topology",
                "generation_id": generation_id,
            })
        for mq_topic in topology.get("mq_topics", []):
            bridges.append({
                "bridge_type": "message_contract",
                "term": mq_topic.get("topic", ""),
                "targets": [c.get("consumer_class", "") for c in mq_topic.get("consumers", [])],
                "source": "topology",
                "generation_id": generation_id,
            })

    # Config keys bridge
    if rules.get("config_keys", True):
        with RuntimeStore(store.graph_db_path) as graph:
            for svc in topology.get("services", []):
                nodes, _ = graph.project_subgraph(str(svc.get("name", "")))
                for node in nodes:
                    if node.type == "ConfigKey" and len(bridges) < 100:
                        bridges.append({
                            "bridge_type": "config_key",
                            "term": node.name,
                            "targets": [node.file_path] if node.file_path else [],
                            "source": "graph",
                            "generation_id": generation_id,
                        })

    # Custom mappings from profile
    for mapping in profile.get("custom_mappings", []):
        bridges.append({
            "bridge_type": mapping.get("bridge_type", "custom"),
            "term": mapping.get("term", ""),
            "targets": mapping.get("targets", []),
            "source": "profile",
            "generation_id": generation_id,
        })

    # Write bridge files grouped by type
    bridge_types: dict[str, list[dict[str, Any]]] = {}
    for bridge in bridges:
        bridge_types.setdefault(bridge["bridge_type"], []).append(bridge)

    for bridge_type, items in bridge_types.items():
        bridge_file = bridge_dir / f"{bridge_type}.json"
        bridge_file.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return {
        "generated": True,
        "bridge_count": len(bridges),
        "bridge_types": {k: len(v) for k, v in bridge_types.items()},
        "generation_id": generation_id,
        "generated_at": now,
    }


def generate_skills(workspace_file: str | Path, output_dir: str | Path | None = None) -> dict[str, Any]:
    store = WorkspaceStore(workspace_file)
    out = Path(output_dir) if output_dir else store.base_dir / "skills" / "generated"
    out.mkdir(parents=True, exist_ok=True)
    cases = store.read_jsonl_prefer_backend("cross-service-task-memory.jsonl", limit=1000)
    if not cases:
        cases = [{"task": "Spring Cloud safe change", "projects": [], "files": [], "flow": "Controller/Consumer → Service → Feign/MQ/Data", "risk_points": ["contract compatibility", "idempotency", "observability"]}]
    files = []
    manifest = {}
    for i, case in enumerate(cases[-20:], start=1):
        slug = _slug(case.get("task", f"case-{i}"))[:60] or f"case-{i}"
        path = out / slug / "SKILL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_skill_page(case), encoding="utf-8")
        files.append(str(path.relative_to(out)))
        manifest[slug] = {"case_index": len(cases) - 20 + i - 1, "task": case.get("task", ""), "path": str(path.relative_to(out))}
    manifest_path = out / "MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"generated": True, "output_dir": str(out), "files": files, "manifest": str(manifest_path.relative_to(out))}


def _overview(name: str, status: dict[str, Any], topology: dict[str, Any]) -> str:
    return f"""# {name} Architecture Overview / 架构总览

This wiki is generated by Memory Center. It summarizes services, contracts, topics, and task memory for AI coding agents and human maintainers.

本 Wiki 由 Memory Center 自动生成，用于沉淀服务拓扑、接口契约、消息主题和历史任务经验。

## Index Counts / 索引统计

```json
{status.get('index_counts', {})}
```

## Services / 服务

""" + "\n".join(f"- `{s.get('name')}` → `{s.get('service_name')}`" for s in topology.get("services", [])) + "\n"


def _service_page(service: dict[str, Any], topology: dict[str, Any]) -> str:
    feigns = [e for e in topology.get("feign_edges", []) if e.get("from_project") == service.get("name") or e.get("to_project") == service.get("name")]
    topics = [t for t in topology.get("mq_topics", []) if any(c.get("project") == service.get("name") for c in t.get("consumers", []))]
    feign_lines = "\n".join(f"- `{e.get('from_project')}` → `{e.get('feign_client')}` → `{e.get('to_project')}`" for e in feigns) or "- (none)"
    topic_lines = "\n".join(f"- `{t.get('topic')}`" for t in topics) or "- (none)"
    return (
        f"# {service.get('name')}\n\n"
        f"- Service name: `{service.get('service_name')}`\n"
        f"- Type: `{service.get('type')}`\n"
        f"- Path: `{service.get('path')}`\n\n"
        f"## Feign edges / Feign 调用\n\n{feign_lines}\n\n"
        f"## MQ topics / 消息主题\n\n{topic_lines}\n"
    )


def _memory_page(cases: list[dict[str, Any]]) -> str:
    body = "# Task Memory / 任务记忆\n\n"
    for c in cases:
        body += f"## {c.get('task')}\n\n- Projects: {', '.join(c.get('projects', []))}\n- Flow: {c.get('flow', '')}\n- Risk: {', '.join(c.get('risk_points', []))}\n\n"
    return body


def _module_page(name: str, nodes: list[Any]) -> str:
    """Generate a bounded L2 map from one project graph shard."""
    grouped: dict[str, list[Any]] = {}
    for node in nodes:
        if node.type in {"Class", "Method", "Endpoint", "FeignClient", "MQTopic", "ConfigKey", "File"}:
            grouped.setdefault(node.type, []).append(node)
    lines = [f"# {name} 模块地图 / Module Map", "", "本页由已发布图索引派生；索引过期时请先执行定向刷新。", ""]
    for kind in sorted(grouped):
        lines.extend([f"## {kind}", ""])
        entries = sorted(grouped[kind], key=lambda item: (item.file_path, item.name))
        for node in entries[:120]:
            location = f" — `{node.file_path}`" if node.file_path else ""
            lines.append(f"- `{node.name}`{location}")
        if len(entries) > 120:
            lines.append(f"- 其余 {len(entries) - 120} 项请通过精确查询展开。")
        lines.append("")
    return "\n".join(lines)


def _skill_page(case: dict[str, Any]) -> str:
    task = case.get('task', 'Spring Cloud task')
    flow = case.get('flow', '')
    files = case.get('files', [])
    risk_points = case.get('risk_points', [])
    projects = case.get('projects', [])

    prompt_template = f"""You are working on a task similar to: {task}

Before making changes:
1. Read these files: {', '.join(f'`{f}`' for f in files) if files else '(none specified)'}
2. Follow this flow: {flow}
3. Watch for these risks: {', '.join(risk_points) if risk_points else '(none specified)'}

After changes:
- Run: memory-center eval-write-quality --workspace <ws> --task-id <tid>
- Verify: memory-center eval-regression-suite --workspace <ws>"""

    trigger = f"Task involves: {', '.join(projects) if projects else '(any project)'}"
    if flow:
        trigger += f" | Flow: {flow}"

    files_section = "\n".join(f"- `{f}`" for f in files)
    risks_section = "\n".join(f"- {r}" for r in risk_points)

    return (
        f"# Skill: {task}\n\n"
        f"## When to use / 适用场景\n\n"
        f"Use this skill when the task resembles this historical case.\n\n"
        f"当新任务与该历史案例类似时，优先读取本 Skill。\n\n"
        f"## Trigger / 触发条件\n\n"
        f"{trigger}\n\n"
        f"## Flow / 流程\n\n"
        f"{flow}\n\n"
        f"## Important files / 关键文件\n\n"
        f"{files_section}\n\n"
        f"## Risk checklist / 风险检查\n\n"
        f"{risks_section}\n\n"
        f"## Prompt Template / 提示模板\n\n"
        f"```markdown\n"
        f"{prompt_template}\n"
        f"```\n"
    )


def _slug(text: str) -> str:
    return "-".join("".join(ch.lower() if ch.isalnum() else " " for ch in text).split())
