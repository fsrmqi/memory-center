"""脱敏运行时检查：聚合宿主接入、索引与交互历史状态。"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from memory_center import __version__
from memory_center.core.audit.hook_config import load_hooks_config, validate_hooks_config
from memory_center.core.audit.interactions import (
    ACTIVE_SESSION_BINDINGS_FILE,
    EFFECT_SUMMARY_FILE,
    build_effect_summary,
)
from memory_center.core.audit.runtime import audit_agent_runtime
from memory_center.core.indexing.control_plane import index_control_status
from memory_center.core.indexing.reindex_state import workspace_reindex_status
from memory_center.core.knowledge.ontology import ALL_EDGE_TYPES, ALL_NODE_TYPES
from memory_center.core.storage.runtime import RuntimeStore
from memory_center.core.storage.workspace import WorkspaceStore
from memory_center.core.workspace.config import load_workspace_config


def inspect_runtime(workspace_file: str | Path, *, thread_id: str = "") -> dict[str, Any]:
    """Return a path-free runtime snapshot with concrete remediation actions."""
    config = load_workspace_config(workspace_file)
    store = WorkspaceStore(workspace_file)
    root = Path(config.root_path).expanduser().resolve()
    active_thread = thread_id or os.environ.get("MEMORY_CENTER_THREAD_ID", "")
    audit = audit_agent_runtime(workspace_file, record=False)
    hooks = _hooks_status(workspace_file, root)
    bindings = _binding_status(store, active_thread)
    effects = _effect_status(workspace_file, store)
    index = _index_status(store)
    ontology = _ontology_status(store)
    mcp = _mcp_status()
    instructions = _instruction_status(root)
    actions = _recommended_actions(audit, hooks, bindings, index, mcp, instructions)
    status = _overall_status(audit, mcp, index, actions)

    return {
        "schema_version": 1,
        "status": status,
        "workspace": {
            "name": config.workspace,
            "config": "workspace.yaml",
            "root": "<workspace-root>",
            "service_count": len(config.services),
        },
        "cli": {"command": "memory-center", "version": __version__},
        "mcp": mcp,
        "instructions": instructions,
        "hooks": hooks,
        "session": bindings,
        "history": effects,
        "index": index,
        "ontology": ontology,
        "runtime_audit": {
            "score": audit.get("score", 0),
            "quality": audit.get("quality", "unknown"),
            "finding_codes": [
                str(item.get("code", ""))
                for item in audit.get("findings", [])
                if item.get("code")
            ][:20],
        },
        "recommended_actions": actions,
    }


def _ontology_status(store: WorkspaceStore) -> dict[str, Any]:
    assertion_index = store.read_json_prefer_backend("assertion-index.json", {}) or {}
    governance_index = store.read_json_prefer_backend("governance-assertion-index.json", {}) or {}
    aliases = store.read_json_prefer_backend("identity-alias-index.json", {}) or {}
    active_generation = str(assertion_index.get("generation", "") or "")
    diagnostics = store.memory_backend().assertion_diagnostics(active_generation)
    unknown = _unknown_graph_types(store)
    findings = []
    if unknown["node_types"] or unknown["edge_types"]:
        findings.append({"code": "unknown_graph_type", "command": "memory-center reindex --workspace <workspace.yaml>"})
    if diagnostics["verified_without_source"]:
        findings.append({"code": "verified_without_source", "command": "memory-center runtime-inspect --workspace <workspace.yaml>"})
    if diagnostics["active_old_generation"]:
        findings.append({"code": "active_old_generation", "command": "memory-center reindex --workspace <workspace.yaml>"})
    return {
        "assertions": {
            "generation": active_generation,
            "active": int(assertion_index.get("active", 0) or 0),
            "by_status": assertion_index.get("by_status", {}),
        },
        "governance_recent": len(governance_index.get("recent", []) or []),
        "identity_aliases": len(aliases.get("aliases", {}) or {}),
        "diagnostics": {**unknown, **diagnostics, "findings": findings},
        "recommended_action": "inspect_evidence_subgraph" if assertion_index else "run_reindex_to_materialize_assertions",
    }


def _unknown_graph_types(store: WorkspaceStore) -> dict[str, list[str]]:
    with RuntimeStore(store.graph_db_path) as graph:
        conn = graph.connect()
        node_types = {str(row[0]) for row in conn.execute("SELECT DISTINCT type FROM nodes").fetchall()}
        edge_types = {str(row[0]) for row in conn.execute("SELECT DISTINCT type FROM edges").fetchall()}
    return {"node_types": sorted(node_types - ALL_NODE_TYPES), "edge_types": sorted(edge_types - ALL_EDGE_TYPES)}


def _mcp_status() -> dict[str, Any]:
    command = "memory-center-mcp"
    available = bool(shutil.which(command))
    version_command = "memory-center"
    version = _command_version(version_command) if available and shutil.which(version_command) else ""
    return {
        "command": command,
        "available": available,
        "version": version or "unknown",
        "version_source": f"{version_command} --version" if version else "unavailable",
        "recommended_action": "use_current_mcp" if available else "install_or_expose_memory_center_mcp_on_path",
    }


def _command_version(command: str) -> str:
    try:
        completed = subprocess.run(
            [command, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if completed.returncode != 0:
        return ""
    output = " ".join((completed.stdout or completed.stderr or "").split())
    return output[:120]


def _instruction_status(root: Path) -> dict[str, Any]:
    agents = root / "AGENTS.md"
    return {
        "agents_md_present": agents.exists(),
        "managed_protocol_present": _managed_protocol_present(agents),
        "recommended_action": "use_current_instructions" if agents.exists() else "run_setup_agent",
    }


def _managed_protocol_present(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return False
    return "<!-- memory-center:start -->" in content and "<!-- memory-center:end -->" in content


def _hooks_status(workspace_file: str | Path, root: Path) -> dict[str, Any]:
    config = load_hooks_config(workspace_file)
    validation_errors = validate_hooks_config(config)
    hook_specs = config.get("hooks", {}) if isinstance(config, dict) else {}
    enabled = sorted(
        str(name)
        for name, spec in hook_specs.items()
        if isinstance(spec, dict) and spec.get("enabled", True) and spec.get("mode", "soft") != "off"
    )
    expected_codex_scripts = {
        "session_start": "mc_session_start.sh",
        "pre_edit": "mc_pre_edit.sh",
        "session_stop": "mc_session_stop.sh",
        "user_prompt_submit": "mc_prompt_submit.sh",
    }
    expected = [expected_codex_scripts[name] for name in enabled if name in expected_codex_scripts]
    generated = root / ".codex-hooks"
    missing = [name for name in expected if not (generated / name).exists()]
    return {
        "config_present": (Path(workspace_file).expanduser().resolve().parent / "hooks.yaml").exists(),
        "config_valid": not validation_errors,
        "validation_errors": validation_errors[:10],
        "enabled_events": enabled,
        "codex_generated_count": len(expected) - len(missing),
        "codex_missing_scripts": missing,
        "claude_settings_present": (root / ".claude" / "settings.local.json").exists(),
        "cursor_rules_present": (root / ".cursorrules").exists(),
    }


def _binding_status(store: WorkspaceStore, thread_id: str) -> dict[str, Any]:
    raw = store.read_json_prefer_backend(ACTIVE_SESSION_BINDINGS_FILE, {})
    entries = raw if isinstance(raw, dict) else {}
    bound = bool(thread_id and isinstance(entries.get(thread_id), dict) and entries[thread_id].get("session_id"))
    return {
        "thread_id_provided": bool(thread_id),
        "thread_session_bound": bound,
        "active_binding_count": len(entries),
        "recommended_action": "use_current_session" if bound else "mc_start_or_set_memory_center_thread_id",
    }


def _effect_status(workspace_file: str | Path, store: WorkspaceStore) -> dict[str, Any]:
    cached = store.read_json_prefer_backend(EFFECT_SUMMARY_FILE, {})
    summary = cached if isinstance(cached, dict) and cached else build_effect_summary(str(workspace_file))
    return {
        "retention": dict(summary.get("retention", {}) or {"days": 30, "max_records": 100_000}),
        "mcp_call_count": int(((summary.get("calls", {}) or {}).get("total", 0)) or 0),
        "host_interaction_count": int(((summary.get("host_interactions", {}) or {}).get("total", 0)) or 0),
        "session_link_rate": float(((summary.get("calls", {}) or {}).get("session_link_rate", 0.0)) or 0.0),
        "verified_success_rate": float(((summary.get("outcomes", {}) or {}).get("verified_success_rate", 0.0)) or 0.0),
    }


def _index_status(store: WorkspaceStore) -> dict[str, Any]:
    summary = store.read_json_prefer_backend("index-summary.json", {})
    summary = summary if isinstance(summary, dict) else {}
    control = index_control_status(store)
    reindex = workspace_reindex_status(store)
    return {
        "generation_status": str(control.get("status", "uninitialized") or "uninitialized"),
        "active_generation_present": bool(control.get("active_generation")),
        "reindex_status": str(reindex.get("status", "idle") or "idle"),
        "reindex_lock_held": bool(reindex.get("lock_held", False)),
        "files": int(summary.get("files", 0) or 0),
        "semantic_backend": str(summary.get("semantic_backend", "unknown") or "unknown"),
        "vector_status": str(summary.get("vector_status", "unknown") or "unknown"),
    }


def _recommended_actions(
    audit: dict[str, Any],
    hooks: dict[str, Any],
    bindings: dict[str, Any],
    index: dict[str, Any],
    mcp: dict[str, Any],
    instructions: dict[str, Any],
) -> list[str]:
    actions: list[str] = []
    if not mcp["available"]:
        actions.append("确认 memory-center-mcp 已安装且在宿主 PATH 中。")
    if not instructions["agents_md_present"]:
        actions.append(
            "项目根缺少 AGENTS.md：按 docs/MCP_GUIDE.md §1 配置宿主 MCP 端点即可；"
            "5.0 不自动写入该文件，受管协议块由宿主集成脚本调用 write_agent_instructions() 落盘。"
        )
    if not hooks["config_valid"]:
        actions.append(
            "hooks.yaml 格式不合法且 5.0 不会执行任何 hook：修正格式，或直接删除该文件停止审计校验。"
        )
    if not bindings["thread_session_bound"]:
        actions.append("新任务先调用 mc_start；跨进程续接时设置 MEMORY_CENTER_THREAD_ID。")
    if index["generation_status"] != "ready" or index["reindex_status"] in {"failed", "interrupted"}:
        actions.append("在管理页对该项目的失败作业点重试（POST /api/v1/jobs/{job_id}/retry）；仍失败则重新保存项目设置以触发重建。")
    if audit.get("quality") == "low":
        actions.append("按 findings 与 diagnostics 修复后重新运行诊断；宿主接入模板可由 memory-center-integrations 输出。")
    return actions[:8]


def _overall_status(audit: dict[str, Any], mcp: dict[str, Any], index: dict[str, Any], actions: list[str]) -> str:
    if not mcp["available"] or audit.get("quality") == "low" or index["reindex_status"] in {"failed", "interrupted"}:
        return "error"
    if actions or index["generation_status"] != "ready":
        return "warning"
    return "ready"
