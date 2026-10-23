import json
import os
import socket
from pathlib import Path
from urllib.request import Request, urlopen

import pytest

from memory_center.application.presentation import (
    export_mermaid,
    export_workspace_dashboard_markdown,
)
from memory_center.application.tasks import execute_task_repair as task_space_repair_execute

pass  # 4.x 入口已退役
from memory_center.core.foundation.schemas import validate_schema_payload
from memory_center.core.governance.instructions import write_agent_instructions
from memory_center.core.governance.registry import add_to_group, create_group, register_workspace
from memory_center.core.governance.rules import ensure_default_rules
from memory_center.core.indexing.reindex import reindex_workspace
from memory_center.core.orchestrator import (
    memory_backend_query,
    memory_eval_agent_guidance,
    memory_eval_agent_guidance_replay,
    memory_eval_context_weight,
    memory_eval_handoff,
    memory_eval_index_freshness,
    memory_eval_regression_suite,
    memory_eval_resume,
    memory_eval_token_benchmark,
    memory_eval_tool_adoption,
    memory_eval_write_quality,
    memory_execute_write,
    memory_plan_write,
    memory_ref_batch,
    memory_ref_get,
    memory_tool_usage_report,
    memory_write_judge,
    workspace_continuity_dashboard,
    workspace_dashboard,
    workspace_end_session,
    workspace_handoff_history,
    workspace_handoff_packet,
    workspace_log_session_event,
    workspace_lookup_hint,
    workspace_model_profile,
    workspace_next_actions,
    workspace_recent_evidence,
    workspace_record_case,
    workspace_replay_write_chain,
    workspace_resume_packet,
    workspace_sniff,
    workspace_start_session,
    workspace_status,
    workspace_sync_sniff_to_artifacts,
    workspace_task_resume_check,
    workspace_trace,
    workspace_unresolved_items,
    workspace_write_receipts,
)
from memory_center.core.orchestrator.shared import _merge_artifact_section
from memory_center.core.storage.workspace import WorkspaceStore
from memory_center.core.tasks.artifacts import (
    ARTIFACT_WRITE_AUDIT_FILE,
    append_change_log,
    append_task_change_log,
    archive_task_space,
    artifact_context,
    artifact_outline,
    auto_archive_task_spaces,
    compact_change_log,
    create_task_space,
    get_artifact,
    get_task_artifact,
    list_artifacts,
    list_task_spaces,
    resolve_task_space,
    task_space_health,
    task_space_repair_plan,
    touch_task_activity,
    update_artifact,
    update_task_artifact,
    update_task_current_summary_snapshot,
    update_task_status,
)
from memory_center.core.tasks.timeline import timeline_query
from memory_center.core.workspace.config import load_workspace_config
from memory_center.core.workspace.doctor import doctor

pass  # 4.x 入口已退役


def _post_json(url: str, payload: dict | None = None) -> dict:
    request = Request(
        url,
        data=json.dumps(payload or {}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return json.loads(urlopen(request).read().decode("utf-8"))


def _copy_root_demo_workspace(tmp_path: Path) -> Path:
    from tests.fixtures import copy_demo_workspace
    return copy_demo_workspace(tmp_path)

def test_demo_workspace_indexes_spring_cloud_patterns(tmp_path: Path):
    workspace = _copy_root_demo_workspace(tmp_path)

    config = load_workspace_config(workspace)
    store = WorkspaceStore(workspace)
    counts = reindex_workspace(config, store)
    ensure_default_rules(store)
    assert (store.rules_dir / "write-policy-rules.yaml").exists()
    assert (store.rules_dir / "auto-sync-rules.yaml").exists()
    assert (store.rules_dir / "eval-rules.yaml").exists()

    assert counts["files"] >= 5
    assert counts["apis"] >= 1
    assert counts["feigns"] >= 1
    assert counts["mq"] >= 1
    assert counts["semantic_docs"] > 0

    sniffed = workspace_sniff(workspace, "oldPubTime newPubTime Kafka ArticleFeignClient move", view="full")
    assert sniffed["candidate_files"]
    assert sniffed["related_rules"]
    assert sniffed["risk_level"] == "high"
    assert "symbolic_context" in sniffed
    assert "mermaid" in sniffed["symbolic_context"]
    assert "entities_mermaid" in sniffed["symbolic_context"]
    assert "flow_mermaid" in sniffed["symbolic_context"]
    assert "mc_lookup (mode=code)" in sniffed["symbolic_context"]["flow_mermaid"]
    assert "mc_analyze (depth=standard)" in sniffed["symbolic_context"]["flow_mermaid"]
    assert sniffed["symbolic_context"]["flow_flags"]["has_contract"] is True
    assert sniffed["symbolic_context"]["flow_flags"]["has_mq"] is True
    assert sniffed["symbolic_context"]["flow_flags"]["risk_level"] == "high"
    assert "resolved_task" in sniffed
    assert "task_candidates" in sniffed
    assert "auto_sync_recommendation" in sniffed
    assert "recommended" in sniffed["auto_sync_recommendation"]
    assert "score_threshold" in sniffed["auto_sync_recommendation"]
    assert "reason" in sniffed["auto_sync_recommendation"]
    assert "mc_analyze (contract, depth=full)" in sniffed["symbolic_context"]["flow_mermaid"]
    assert "MQ compatibility review" in sniffed["symbolic_context"]["flow_mermaid"]
    assert "mc_sync" in "\n".join(sniffed["next_steps"])
    assert "mc_close" in "\n".join(sniffed["next_steps"])
    assert "write_judge" in "\n".join(sniffed["next_steps"])
    assert "write_judge_recommendation" in sniffed
    assert "selected_layer" in sniffed["write_judge_recommendation"]
    assert "lookup_hint" in sniffed
    assert "preferred_tools" in sniffed["lookup_hint"]
    assert "candidate_paths" in sniffed
    assert sniffed["candidate_paths"]
    assert "recommended_path" in sniffed
    assert sniffed["recommended_path"]["candidate_type"]
    assert sniffed["recommended_path"]["target"]
    assert sniffed["candidate_paths"][0]["target"] == sniffed["recommended_path"]["target"]
    assert "mc_close (end session)" in sniffed["symbolic_context"]["flow_mermaid"]
    assert "mc_close (sync case)" in sniffed["symbolic_context"]["flow_mermaid"]
    assert sniffed["source_refs"]

    traced = workspace_trace(workspace, "article-pubtime-change")
    assert traced["matched_mq"]
    assert traced["trace_mode"] == "index_overview"

    diagram = export_mermaid(workspace)
    assert "flowchart LR" in diagram
    assert "article-service" in diagram

    report = doctor(workspace)
    assert report["ok"] is True


def test_merge_artifact_section_preserves_following_sections():
    existing = (
        "# Doc\n\n"
        "intro text\n\n"
        "## Sniff Context\n\n"
        "old body\n\n"
        "### Details\n\n"
        "old details\n\n"
        "## Sniff Plan\n\n"
        "keep me\n\n"
        "## Another Section\n\n"
        "keep me too\n"
    )
    merged = _merge_artifact_section(existing, "Sniff Context", "new body")
    assert "## Sniff Context\n\nnew body" in merged
    assert "## Sniff Plan\n\nkeep me" in merged
    assert "## Another Section\n\nkeep me too" in merged
    assert "old details" not in merged


def test_workspace_supports_absolute_service_paths_across_multiple_roots(tmp_path: Path):
    import shutil

    import yaml

    source = Path("examples/spring-cloud-demo")
    root_a = tmp_path / "root-a"
    root_b = tmp_path / "root-b"
    root_c = tmp_path / "root-c"
    root_a.mkdir()
    root_b.mkdir()
    root_c.mkdir()

    shutil.copytree(source / "article-service", root_a / "article-service")
    shutil.copytree(source / "task-service", root_b / "task-service")
    shutil.copytree(source / "common-api", root_c / "common-api")

    memory_dir = root_a / ".memory-center"
    memory_dir.mkdir()
    workspace = memory_dir / "workspace.yaml"
    workspace.write_text(
        yaml.safe_dump(
            {
                "workspace": "multi-root-demo",
                "root": str(root_a),
                "services": [
                    {"name": "article-service", "path": "article-service", "type": "spring-boot-service", "service_name": "article-service"},
                    {"name": "task-service", "path": str((root_b / "task-service").resolve()), "type": "spring-boot-service", "service_name": "task-service"},
                    {"name": "common-api", "path": str((root_c / "common-api").resolve()), "type": "shared-library", "tags": ["contract"]},
                ],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    config = load_workspace_config(workspace)
    store = WorkspaceStore(workspace)
    counts = reindex_workspace(config, store)
    ensure_default_rules(store)

    assert counts["files"] > 0
    file_index = store.read_json("file-index.json", [])
    assert any(item["project"] == "task-service" for item in file_index)
    assert any(item["project"] == "common-api" for item in file_index)
    assert any(item["path"].startswith("task-service/") for item in file_index)
    assert any(item["path"].startswith("common-api/") for item in file_index)
    assert any(item.get("abs_path", "").endswith("task-service/src/main/java/com/example/task/ArticleMoveService.java") for item in file_index)

    sniffed = workspace_sniff(workspace, "ArticleFeignClient move")
    assert sniffed["candidate_files"]
    report = doctor(workspace)
    assert report["ok"] is True


def test_reindex_workspace_supports_project_and_path_filters(tmp_path: Path):
    import shutil

    source = Path("examples/spring-cloud-demo")
    target = tmp_path / "incremental-index-demo"
    shutil.copytree(source, target)
    workspace = target / ".memory-center" / "workspace.yaml"
    lines = workspace.read_text(encoding="utf-8").splitlines()
    lines = [f"root: {target.as_posix()}" if line.startswith("root:") else line for line in lines]
    workspace.write_text("\n".join(lines) + "\n", encoding="utf-8")

    config = load_workspace_config(workspace)
    store = WorkspaceStore(workspace)
    counts_before = reindex_workspace(config, store)

    added_file = target / "task-service" / "src" / "main" / "java" / "com" / "example" / "task" / "IncrementalIndexSmoke.java"
    added_file.parent.mkdir(parents=True, exist_ok=True)
    added_file.write_text(
        "package com.example.task;\n\npublic class IncrementalIndexSmoke {\n    public void ping() {}\n}\n",
        encoding="utf-8",
    )

    counts_after_project = reindex_workspace(config, store, projects=["task-service"])
    file_index = store.read_json("file-index.json", [])
    symbol_index = store.read_json("java-symbol-index.json", [])
    assert counts_after_project["mode"] == "partial"
    assert "task-service" in counts_after_project["filtered_projects"]
    assert any(item.get("path", "").endswith("IncrementalIndexSmoke.java") for item in file_index)
    assert any("IncrementalIndexSmoke" in item.get("classes", []) for item in symbol_index)
    assert counts_after_project["files"] >= counts_before["files"] + 1

    added_file_two = target / "task-service" / "src" / "main" / "java" / "com" / "example" / "task" / "IncrementalPathOnly.java"
    added_file_two.write_text(
        "package com.example.task;\n\npublic class IncrementalPathOnly {}\n",
        encoding="utf-8",
    )

    logical_path = "task-service/src/main/java/com/example/task/IncrementalPathOnly.java"
    counts_after_path = reindex_workspace(config, store, paths=[logical_path])
    file_index_after_path = store.read_json("file-index.json", [])
    assert counts_after_path["mode"] == "partial"
    assert logical_path in counts_after_path["filtered_paths"]
    assert any(item.get("path", "") == logical_path for item in file_index_after_path)


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_record_case_cli_writes_history(tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


def _cli_project_workspace(tmp_path: Path):
    """Helper: copy demo workspace and patch root for CLI tests."""
    source = Path("examples/spring-cloud-demo")
    target = tmp_path / "cli-project-demo"
    import shutil
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)
    workspace = target / ".memory-center" / "workspace.yaml"
    lines = workspace.read_text(encoding="utf-8").splitlines()
    lines = [f"root: {target.as_posix()}" if line.startswith("root:") else line for line in lines]
    workspace.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(workspace)


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_reindex_cli_defaults_to_parallel(monkeypatch, tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_reindex_cli_can_disable_parallel(monkeypatch, tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_query_cli_forwards_vector_options(monkeypatch, tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_query_cli_forwards_evidence_index_view(monkeypatch, tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_cli_query_project_filter(tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_query_agent_next_steps_consistent_across_core_cli_http(tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_query_with_session_id_records_agent_guidance_for_cli_and_http(tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_query_http_evidence_index_view(tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_eval_agent_guidance_available_from_cli_and_http(tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_cli_symbol_project_filter(tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_cli_callers_project_filter(tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_cli_callees_project_filter(tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_cli_context_project_filter(tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_cli_impact_project_filter(tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_export_workspace_dashboard_cli(tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_cli_version_flag():
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


def test_write_agent_instructions_includes_sync_workflow(tmp_path: Path):
    workspace_root = tmp_path / "workspace-root"
    workspace_root.mkdir()
    store = WorkspaceStore(tmp_path / ".memory-center" / "workspace.yaml")

    write_agent_instructions(store, workspace_root)

    agents = (workspace_root / "AGENTS.md").read_text(encoding="utf-8")
    claude = (workspace_root / "CLAUDE.md").read_text(encoding="utf-8")

    for content in [agents, claude]:
        assert "<!-- memory-center:start -->" in content
        assert "Memory Center 5.0 Agent Protocol" in content
        assert "mc_workspaces()" in content
        assert "mc_start(workspace_id=" in content
        assert "mc_lookup(workspace_id=" in content
        assert "mc_analyze(workspace_id=" in content
        assert "mc_close(session_id=" in content
        assert "mc_memory_write(workspace_id=" in content
        assert "assistant_knowledge(" in content
        assert "assistant_admin(" in content
        assert "http://127.0.0.1:8765/mcp" in content
        assert "English:" in content
        # 4.x 工具只能以“不要调用”的形式出现
        assert "不要调用旧 `mc_admin`" in content
        assert "--workspace" in content  # 仅用于说明 stdio 代理不带旧参数
        assert "mc_sync(intent=" not in content
        assert "mc_handoff(" not in content
        assert "mc_freshness(" not in content


def test_write_agent_instructions_are_mirrored_to_service_roots(tmp_path: Path):
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    store = WorkspaceStore(workspace)
    workspace_root = workspace.parent.parent

    write_agent_instructions(store, workspace_root)

    service_agents = (workspace_root / "task-service" / "AGENTS.md").read_text(encoding="utf-8")
    cursor_rules = (workspace_root / "task-service" / ".cursor" / "rules" / "memory-center.mdc").read_text(encoding="utf-8")

    assert "当前目录是聚合工作区下的子项目" in service_agents
    assert str(workspace.resolve()) in service_agents
    assert "mc_workspaces()" in service_agents
    assert "5.0 不读取旧 workspace 文件" in service_agents
    assert "Current directory is a service root under the aggregate workspace" in service_agents
    assert "mc_start(workspace_id=" in service_agents
    assert str(workspace.resolve()) in cursor_rules


def test_write_agent_instructions_write_mcp_configs_to_service_roots(tmp_path: Path):
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    store = WorkspaceStore(workspace)
    workspace_root = workspace.parent.parent

    write_agent_instructions(store, workspace_root)

    service_root = workspace_root / "task-service"
    codex_config = json.loads((service_root / ".codex" / "mcp.json").read_text(encoding="utf-8"))
    claude_config = json.loads((service_root / ".mcp.json").read_text(encoding="utf-8"))
    cursor_config = json.loads((service_root / ".cursor" / "mcp.json").read_text(encoding="utf-8"))

    for config in (codex_config, claude_config, cursor_config):
        server = config["mcpServers"]["memory-center"]
        assert server["type"] == "http"
        assert server["url"] == "http://127.0.0.1:8765/mcp"
        assert "command" not in server
        assert "--workspace" not in json.dumps(config)


def test_write_agent_instructions_merge_existing_mcp_configs(tmp_path: Path):
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    store = WorkspaceStore(workspace)
    workspace_root = workspace.parent.parent
    codex_config_path = workspace_root / ".codex" / "mcp.json"
    codex_config_path.parent.mkdir(parents=True, exist_ok=True)
    codex_config_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "idea": {
                        "url": "http://127.0.0.1:64342/sse",
                    }
                }
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    write_agent_instructions(store, workspace_root)

    merged = json.loads(codex_config_path.read_text(encoding="utf-8"))
    assert "idea" in merged["mcpServers"]
    assert "memory-center" in merged["mcpServers"]
    assert merged["mcpServers"]["memory-center"]["url"] == "http://127.0.0.1:8765/mcp"
    assert merged["mcpServers"]["memory-center"]["type"] == "http"


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_mcp_workspace_context_exposes_startup_diagnostics_for_service_root(tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_workspace_service_maintenance_commands(tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


def test_workspace_artifacts_flow(tmp_path: Path):
    source = Path("examples/spring-cloud-demo")
    target = tmp_path / "artifact-demo"
    import shutil
    shutil.copytree(source, target)
    workspace = target / ".memory-center" / "workspace.yaml"
    lines = workspace.read_text(encoding="utf-8").splitlines()
    lines = [f"root: {target.as_posix()}" if line.startswith("root:") else line for line in lines]
    workspace.write_text("\n".join(lines) + "\n", encoding="utf-8")

    artifacts = list_artifacts(workspace)
    assert artifacts["artifacts"]
    assert any(item["name"] == "context" for item in artifacts["artifacts"])

    update = update_artifact(workspace, "context", "# Context\n\n共享上下文")
    assert update["updated"] is True
    assert update["write_mode"] in {"append_guarded", "append_full_document", "initial_write"}
    assert "artifact-write-audit.jsonl" in update["audit_ref"]
    artifact = get_artifact(workspace, "context")
    assert "共享上下文" in artifact["content"]
    assert "Fill this artifact collaboratively." in artifact["content"]

    changed = append_change_log(workspace, "新增共享工件能力")
    assert changed["appended"] is True
    change_log = get_artifact(workspace, "change_log")
    assert "新增共享工件能力" in change_log["content"]

    outline = artifact_outline(workspace, "change_log")
    assert outline["sections"]
    context = artifact_context(workspace, "共享工件", limit=3)
    assert "summary" in context

    for idx in range(35):
        append_change_log(workspace, f"历史记录 {idx}")
    compacted = compact_change_log(workspace, keep_recent=10)
    assert compacted["compacted"] is True
    archive = get_artifact(workspace, "change-log.archive.md")
    assert "历史记录" in archive["content"]

    created_task = create_task_space(workspace, title="修复 Feign DTO 兼容", owner="cjq", tags=["feign", "dto"], priority="high")
    assert created_task["created"] is True
    assert created_task["owner"] == "cjq"
    assert created_task["priority"] == "high"
    tasks = list_task_spaces(workspace)
    assert tasks["active_tasks"]
    task_id = created_task["task_id"]
    status_after_create = workspace_status(workspace)
    assert status_after_create["current_focus_task"]
    assert status_after_create["current_focus_task"]["task_id"] == task_id
    assert "focus_reason" in status_after_create["current_focus_task"]
    task_context = get_task_artifact(workspace, task_id, "context")
    assert "修复 Feign DTO 兼容" in task_context["content"]
    task_summary = get_task_artifact(workspace, task_id, "current_summary")
    assert "Current Summary / 当前最短上下文" in task_summary["content"]
    updated_task = update_task_artifact(workspace, task_id, "plan", "# Plan\n\n先做影响分析")
    assert updated_task["updated"] is True
    assert updated_task["write_mode"] in {"append_guarded", "append_full_document", "initial_write"}
    assert "artifact-write-audit.jsonl" in updated_task["audit_ref"]
    task_plan = get_task_artifact(workspace, task_id, "plan")
    assert "Title: 修复 Feign DTO 兼容" in task_plan["content"]
    assert "先做影响分析" in task_plan["content"]
    changed_task = append_task_change_log(workspace, task_id, "完成第一轮分析", keep_recent=5)
    assert changed_task["appended"] is True
    archived_task = archive_task_space(workspace, task_id, reason="done")
    assert archived_task["archived"] is True
    listed = list_task_spaces(workspace, include_archived=True)
    assert listed["archived_tasks"]

    active_task = create_task_space(workspace, title="站点连通性告警治理")
    update_task_artifact(workspace, active_task["task_id"], "plan", "# Plan\n\n处理站点连通性告警与告警链路")
    resolved = resolve_task_space(workspace, intent="继续处理站点告警连通性问题", create_if_missing=False, limit_candidates=3, score_threshold=1)
    assert resolved["resolved"] is True
    assert resolved["task_id"] == active_task["task_id"]
    assert resolved["candidates"]
    assert "match_reasons" in resolved
    assert "artifact_hits" in resolved["match_reasons"]
    status_updated = update_task_status(workspace, active_task["task_id"], "blocked")
    assert status_updated["status"] == "blocked"


def test_memory_write_judge_and_plan_write(tmp_path: Path):
    source = Path("examples/spring-cloud-demo")
    target = tmp_path / "memory-judge-demo"
    import shutil
    shutil.copytree(source, target)
    workspace = target / ".memory-center" / "workspace.yaml"
    lines = workspace.read_text(encoding="utf-8").splitlines()
    lines = [f"root: {target.as_posix()}" if line.startswith("root:") else line for line in lines]
    workspace.write_text("\n".join(lines) + "\n", encoding="utf-8")

    l3_judge = memory_write_judge(
        workspace,
        text="团队规范：所有 DTO 变更必须向后兼容，并在迁移策略中记录灰度周期。",
        source="note",
        intent="更新团队规则",
    )
    assert l3_judge["decision"]["selected_layer"] == "L3_workspace_profile"
    assert l3_judge["decision"]["suggested_tool"] == "workspace_artifact_update"

    l2_plan = memory_plan_write(
        workspace,
        text="外链处理任务新增 Kafka 校验与计划更新",
        source="note",
        intent="外链处理任务持续推进",
        task_id="",
    )
    assert l2_plan["memory_layer"] == "L2_task_spaces"
    assert l2_plan["plan"]["steps"]
    assert l2_plan["plan"]["steps"][0]["tool"] in {"workspace_sync_sniff_artifacts", "workspace_sync_case_artifacts"}

    l0_judge = memory_write_judge(
        workspace,
        text="启动会话记录调试过程",
        source="note",
        intent="记录会话过程",
    )
    # When text has no keyword boosts overriding the source boost, L0 wins
    assert l0_judge["decision"]["selected_layer"] in {"L0_session_events", "L1_case_atoms"}

    l0_plan = memory_plan_write(
        workspace,
        text="启动会话记录调试过程",
        source="note",
        intent="记录会话过程",
    )
    assert l0_plan["memory_layer"] in {"L0_session_events", "L1_case_atoms"}

    executed = memory_execute_write(
        workspace,
        text="团队规范：DTO 变更必须保兼容并记录迁移策略。",
        source="note",
        intent="更新团队规则",
    )
    assert executed["memory_layer"] == "L3_workspace_profile"
    assert executed["executed"]
    assert executed["executed"][0]["tool"] == "workspace_artifact_update"
    assert executed["write_receipts"]
    assert executed["write_receipts"][0]["layer"] == "L3_workspace_profile"
    assert executed["write_receipts"][0]["receipt_id"].startswith("wr:")
    assert executed["write_receipts"][0]["summary"]
    store = WorkspaceStore(workspace)
    receipt_rows = store.read_jsonl("write-receipts.jsonl", limit=20)
    assert receipt_rows
    assert any(row.get("layer") == "L3_workspace_profile" for row in receipt_rows)
    queried = workspace_write_receipts(workspace, layer="L3_workspace_profile", limit=10)
    assert queried["receipts"]
    assert queried["summary"]["total"] >= 1
    replay = workspace_replay_write_chain(workspace, limit=20)
    assert replay["timeline"]
    assert replay["schema"]["name"] == "timeline_result"
    quality = memory_eval_write_quality(workspace, intent="更新团队规则", limit=20)
    assert quality["receipt_count"] >= 1
    assert quality["quality"] in {"high", "medium", "low"}
    assert quality["schema"]["name"] == "eval_result"
    next_actions = workspace_next_actions(workspace, intent="更新团队规则", limit=5)
    assert next_actions["actions"]
    unresolved = workspace_unresolved_items(workspace, intent="更新团队规则", limit=5)
    assert "items" in unresolved
    resume_packet = workspace_resume_packet(workspace, intent="更新团队规则", limit=5)
    assert "next_recommended_actions" in resume_packet
    assert resume_packet["resume_rule_profile"] in {"default", "rule_update", "implementation"}
    assert resume_packet["schema"]["name"] == "resume_packet"
    resume_eval = memory_eval_resume(workspace, intent="更新团队规则", limit=10)
    assert resume_eval["quality"] in {"high", "medium", "low"}
    assert resume_eval["schema"]["name"] == "eval_result"
    recent_evidence = workspace_recent_evidence(workspace, limit=5, view="full")
    assert "evidence" in recent_evidence
    assert recent_evidence["evidence"][0]["ref_id"]
    assert recent_evidence["evidence"][0]["summary"]
    # view=full should return full evidence entries (not compacted)
    full_entry = recent_evidence["evidence"][0]
    assert "event_type" in full_entry or "layer" in full_entry or "source" in full_entry
    # view=compact should return compact entries
    compact_evidence = workspace_recent_evidence(workspace, limit=5, view="compact", budget="medium")
    compact_entry = compact_evidence["evidence"][0]
    assert compact_entry["ref_id"]
    assert compact_entry["summary"]
    # compact entries should be stripped of detail fields
    assert "event_type" not in compact_entry or "session_id" not in compact_entry
    compact_small = workspace_recent_evidence(workspace, limit=20, view="compact", budget="small")
    compact_medium = workspace_recent_evidence(workspace, limit=20, view="compact", budget="medium")
    compact_large = workspace_recent_evidence(workspace, limit=20, view="compact", budget="large")
    assert len(compact_small["evidence"]) <= 3
    assert len(compact_medium["evidence"]) <= 5
    assert len(compact_large["evidence"]) <= 10
    ref_detail = memory_ref_get(workspace, recent_evidence["evidence"][0]["ref_id"])
    assert ref_detail["found"] is True
    # ref→timeline reverse navigation: timeline_ref should be present
    assert "timeline_ref" in ref_detail
    ref_batch = memory_ref_batch(workspace, [recent_evidence["evidence"][0]["ref_id"]])
    assert ref_batch["found_count"] == 1
    model_profile = workspace_model_profile("deepseek-r1")
    assert model_profile["normalized_model"] == "deepseek"
    handoff = workspace_handoff_packet(workspace, target_model="glm-4", intent="更新团队规则", limit=5)
    assert handoff["model_profile"]["normalized_model"] == "glm"
    assert "handoff_packet" in handoff
    assert handoff["schema"]["name"] == "handoff_packet"
    handoff_eval = memory_eval_handoff(workspace, target_model="glm-4", intent="更新团队规则", limit=10)
    assert handoff_eval["quality"] in {"high", "medium", "low"}
    assert handoff_eval["schema"]["name"] == "eval_result"
    token_benchmark = memory_eval_token_benchmark(workspace, intent="更新团队规则", limit=5)
    assert "benchmark" in token_benchmark
    assert "handoff" in token_benchmark["benchmark"]
    assert set(token_benchmark["benchmark"]["handoff"].keys()) >= {"small", "medium", "large", "savings_pct"}
    freshness_eval = memory_eval_index_freshness(workspace, scope="all")
    assert freshness_eval["schema"]["name"] == "eval_result"
    adoption_eval = memory_eval_tool_adoption(workspace, limit=20)
    assert adoption_eval["schema"]["name"] == "eval_result"
    context_weight_eval = memory_eval_context_weight(workspace, intent="更新团队规则", limit=5)
    assert context_weight_eval["schema"]["name"] == "eval_result"
    agent_guidance_eval = memory_eval_agent_guidance(workspace, intent="ArticleFeignClient 调用链", limit=5)
    assert agent_guidance_eval["schema"]["name"] == "eval_result"
    assert agent_guidance_eval["agent_next_step_count"] >= 1
    assert agent_guidance_eval["invalid_search_suggestion_count"] == 0
    regression_suite = memory_eval_regression_suite(workspace, target_model="glm-4", intent="更新团队规则", limit=10)
    assert regression_suite["suite_name"] == "memory_eval_regression_suite"
    assert regression_suite["components"]["write_quality"]["schema"]["name"] == "eval_result"
    assert regression_suite["components"]["agent_guidance"]["schema"]["name"] == "eval_result"
    assert regression_suite["components"]["agent_guidance_adoption"]["schema"]["name"] == "eval_result"
    assert regression_suite["schema"]["name"] == "eval_result"
    handoff_history = workspace_handoff_history(workspace, target_model="glm-4", limit=10)
    assert handoff_history["handoffs"]
    dashboard = workspace_continuity_dashboard(workspace, intent="更新团队规则", limit=5)
    assert "resume_packet" in dashboard
    assert "recent_handoffs" in dashboard
    assert dashboard["schema"]["name"] == "workspace_continuity_dashboard"
    workspace_dash = workspace_dashboard(workspace, intent="更新团队规则", limit=5)
    assert "active_tasks" in workspace_dash
    assert "focus_dashboard" in workspace_dash
    assert "tool_usage_report" in workspace_dash
    assert "summary" in workspace_dash["tool_usage_report"]
    assert "agent_guidance" in workspace_dash
    assert workspace_dash["agent_guidance"]["quality"] in {"high", "medium", "low"}
    assert "adoption" in workspace_dash["agent_guidance"]
    assert workspace_dash["schema"]["name"] == "workspace_dashboard"
    timeline = timeline_query(str(workspace), kinds=["write_receipt", "handoff"], limit=20)
    assert timeline["timeline"]
    assert timeline["schema"]["name"] == "timeline_result"
    assert timeline["filters"]["kinds"] == ["handoff", "write_receipt"]
    filtered_timeline = timeline_query(str(workspace), kinds=["write_receipt"], layer="L3_workspace_profile", limit=20)
    assert filtered_timeline["timeline"]
    assert all(item["layer"] == "L3_workspace_profile" for item in filtered_timeline["timeline"])
    lookup_hint = workspace_lookup_hint(workspace, query="ArticleFeignClient 调用链", intent="找谁调用它", limit=5)
    assert lookup_hint["schema"]["name"] == "lookup_hint"
    assert lookup_hint["should_use_memory_center"] is True
    assert lookup_hint["preferred_tools"]
    markdown = export_workspace_dashboard_markdown(workspace, intent="更新团队规则", limit=5)
    assert "Workspace Dashboard" in markdown


def test_schema_validation_guard():
    validate_schema_payload(
        "write_receipt",
        {
            "receipt_id": "wr-001",
            "summary": "recorded case atom",
            "layer": "L1_case_atoms",
            "action": "workspace_record_case",
            "scope": "memory",
            "target": "cross-service-task-memory.jsonl",
            "target_file": "memory/cross-service-task-memory.jsonl",
        },
    )
    try:
        validate_schema_payload("timeline_result", {"timeline": [], "summary": {}})
        raised = False
    except ValueError:
        raised = True
    assert raised is True


def test_tool_usage_report_and_lookup_hint(tmp_path: Path):
    source = Path("examples/spring-cloud-demo")
    target = tmp_path / "usage-demo"
    import shutil
    shutil.copytree(source, target)
    workspace = target / ".memory-center" / "workspace.yaml"
    lines = workspace.read_text(encoding="utf-8").splitlines()
    lines = [f"root: {target.as_posix()}" if line.startswith("root:") else line for line in lines]
    workspace.write_text("\n".join(lines) + "\n", encoding="utf-8")

    session = workspace_start_session(workspace, "分析 ArticleFeignClient 调用链")
    session_id = session["session_id"]
    workspace_log_session_event(workspace, session_id, "tool_call", {"tool_name": "memory_symbol_tool", "query": "ArticleFeignClient"})
    workspace_log_session_event(workspace, session_id, "tool_call", {"tool_name": "rg", "query": "ArticleController class"})

    report = memory_tool_usage_report(workspace, limit=20)
    assert report["schema"]["name"] == "tool_usage_report"
    assert report["summary"]["total_tool_calls"] >= 2
    assert report["lookup_tool_counts"]["memory_symbol_tool"] >= 1
    assert report["suspected_bypass"]

    hint = workspace_lookup_hint(workspace, query="ArticleController 类", intent="想找调用链", limit=5)
    assert hint["recommended_path"] in {"symbol_lookup", "call_chain", "cross_service_analysis"}
    assert "memory_" in " ".join(hint["preferred_tools"]) or "workspace_" in " ".join(hint["preferred_tools"])


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_agent_guidance_adoption_matches_followup_tools(tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_agent_guidance_replay_classifies_missed_bypassed_and_unobservable(tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


def test_agent_guidance_replay_prioritizes_earlier_bypass_over_later_match(tmp_path: Path):
    workspace = _copy_demo_workspace(tmp_path, "agent-guidance-replay-order")
    session = workspace_start_session(workspace, "先绕过后补做")
    session_id = session["session_id"]
    workspace_log_session_event(
        workspace,
        session_id,
        "agent_guidance",
        {"agent_next_steps": [{"action": "switch_to_walkthrough", "command": "mc_lookup(mode=walkthrough)"}]},
    )
    workspace_log_session_event(workspace, session_id, "tool_call", {"tool_name": "rg", "query": "ArticleService"})
    workspace_log_session_event(
        workspace,
        session_id,
        "tool_call",
        {"tool_name": "memory_method_walkthrough_tool", "mode": "walkthrough"},
    )

    evaluation = memory_eval_agent_guidance_replay(workspace, session_id=session_id)

    assert evaluation["summary"]["bypassed_count"] == 1
    assert evaluation["summary"]["adopted_count"] == 0
    assert evaluation["replay_records"][0]["matched_tool"] == "rg"


def test_agent_guidance_replay_adopts_inspect_actions_with_memory_cli_aliases(tmp_path: Path):
    workspace = _copy_demo_workspace(tmp_path, "agent-guidance-replay-inspect")
    session = workspace_start_session(workspace, "按建议继续消费检索证据")
    session_id = session["session_id"]
    workspace_log_session_event(
        workspace,
        session_id,
        "agent_guidance",
        {
            "query": "SnapshotServiceImpl",
            "agent_next_steps": [
                {
                    "action": "inspect_code_hits",
                    "command": "read the top hit path/snippet, then rerun mc_lookup with a concrete symbol if needed",
                }
            ],
        },
    )
    workspace_log_session_event(workspace, session_id, "tool_call", {"tool_name": "mc_lookup", "query": "SnapshotServiceImpl"})

    evaluation = memory_eval_agent_guidance_replay(workspace, session_id=session_id)

    assert evaluation["summary"]["adopted_count"] == 1
    assert evaluation["summary"]["missed_count"] == 0
    assert evaluation["replay_records"][0]["matched_tool"] == "mc_lookup"


def test_agent_guidance_replay_does_not_match_search_tokens_inside_payload_text(tmp_path: Path):
    workspace = _copy_demo_workspace(tmp_path, "agent-guidance-replay-token")
    session = workspace_start_session(workspace, "普通工具调用")
    session_id = session["session_id"]
    workspace_log_session_event(
        workspace,
        session_id,
        "agent_guidance",
        {"agent_next_steps": [{"action": "refine_query", "command": "mc_lookup(mode=query)"}]},
    )
    workspace_log_session_event(workspace, session_id, "tool_call", {"tool_name": "git", "query": "application config"})

    evaluation = memory_eval_agent_guidance_replay(workspace, session_id=session_id)

    assert evaluation["summary"]["bypassed_count"] == 0
    assert evaluation["summary"]["missed_count"] == 1
    assert evaluation["replay_records"][0]["reason"] == "memory_tool_used_but_action_mismatch"


def test_memory_backend_sqlite_mirror(tmp_path: Path):
    source = Path("examples/spring-cloud-demo")
    target = tmp_path / "memory-backend-demo"
    import shutil
    shutil.copytree(source, target)
    workspace = target / ".memory-center" / "workspace.yaml"
    lines = workspace.read_text(encoding="utf-8").splitlines()
    lines = [f"root: {target.as_posix()}" if line.startswith("root:") else line for line in lines]
    workspace.write_text("\n".join(lines) + "\n", encoding="utf-8")

    config = load_workspace_config(workspace)
    store = WorkspaceStore(workspace)
    reindex_workspace(config, store)
    ensure_default_rules(store)

    session = workspace_start_session(workspace, "sqlite backend mirror smoke")
    sid = session["session_id"]
    workspace_log_session_event(workspace, sid, "tool_call", {"tool_name": "mc_lookup", "query": "ArticleFeignClient"})
    workspace_end_session(workspace, sid, outcome="done")
    workspace_record_case(
        workspace,
        "sqlite backend mirror smoke",
        ["task-service"],
        ["task-service/src/main/java/com/example/task/ArticleMoveService.java"],
        "query -> log -> record",
        ["Feign compatibility"],
        verified_by=["smoke"],
        source_session_id=sid,
    )
    ref = store.write_memory_ref_json("refs/sessions/test-backend.json", {"created_at": "2026-01-01T00:00:00+00:00", "note": "backend"})
    (store.memory_dir / "refs/sessions/test-backend.json").unlink()

    stats = store.memory_backend_stats()
    status = workspace_status(workspace, view="full")
    query = memory_backend_query(workspace, collection="session-events.jsonl", limit=5)
    assert stats["collections"]["session-events.jsonl"] >= 1
    assert stats["collections"]["cross-service-task-memory.jsonl"] >= 1
    assert stats["ref_count"] >= 1
    assert ref
    assert store.read_memory_ref_json(ref) == {"created_at": "2026-01-01T00:00:00+00:00", "note": "backend"}
    assert status["memory_backend"]["collections"]["session-events.jsonl"] >= 1
    assert query["records"]["count"] >= 1


def test_auto_archive_task_spaces(tmp_path: Path):
    source = Path("examples/spring-cloud-demo")
    target = tmp_path / "task-auto-archive-demo"
    import shutil
    shutil.copytree(source, target)
    workspace = target / ".memory-center" / "workspace.yaml"
    lines = workspace.read_text(encoding="utf-8").splitlines()
    lines = [f"root: {target.as_posix()}" if line.startswith("root:") else line for line in lines]
    workspace.write_text("\n".join(lines) + "\n", encoding="utf-8")

    created = create_task_space(workspace, title="历史任务")
    task_id = created["task_id"]
    assert task_id
    task_dir = Path(created["path"])
    meta_path = task_dir / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["updated_at"] = "2020-01-01T00:00:00"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    archived = auto_archive_task_spaces(workspace, retention_days=30)
    assert archived["archived_count"] == 1
    listed = list_task_spaces(workspace, include_archived=True)
    assert listed["archived_tasks"]


def test_artifact_sync_from_sniff_and_case(tmp_path: Path):
    from memory_center.core.orchestrator import (
        workspace_end_session,
        workspace_log_session_event,
        workspace_start_session,
        workspace_sync_case_to_artifacts,
        workspace_sync_sniff_to_artifacts,
    )

    source = Path("examples/spring-cloud-demo")
    target = tmp_path / "artifact-sync-demo"
    import shutil
    shutil.copytree(source, target)
    workspace = target / ".memory-center" / "workspace.yaml"
    lines = workspace.read_text(encoding="utf-8").splitlines()
    lines = [f"root: {target.as_posix()}" if line.startswith("root:") else line for line in lines]
    workspace.write_text("\n".join(lines) + "\n", encoding="utf-8")

    config = load_workspace_config(workspace)
    store = WorkspaceStore(workspace)
    ensure_default_rules(store)
    reindex_workspace(config, store)

    task = create_task_space(workspace, title="Feign DTO 兼容改造")
    synced_sniff = workspace_sync_sniff_to_artifacts(
        workspace,
        "修改 Feign DTO 并评估 MQ 影响",
        limit=5,
        task_id=task["task_id"],
        auto_sync_mode="strict",
    )
    assert synced_sniff["synced"] is True
    assert synced_sniff["task_id"] == task["task_id"]
    assert synced_sniff["auto_sync_mode"] == "strict"
    assert "auto_sync_recommendation" in synced_sniff
    context = get_task_artifact(workspace, task["task_id"], "context")
    plan = get_task_artifact(workspace, task["task_id"], "plan")
    summary_artifact = get_task_artifact(workspace, task["task_id"], "current_summary")
    assert "Sniff Context" in context["content"]
    assert "Sniff Plan" in plan["content"]
    assert "Source References" in context["content"]
    assert "Risk Level" in summary_artifact["content"] or "risk_level" in summary_artifact["content"].lower()
    # current_summary may be updated by sync; check it has some meaningful content
    task_spaces = list_task_spaces(workspace)
    task_row = next(item for item in task_spaces["active_tasks"] if item["task_id"] == task["task_id"])
    assert task_row["last_activity_source"] == "sync_sniff_artifacts"

    auto_synced_sniff = workspace_sync_sniff_to_artifacts(workspace, "继续处理 Feign DTO 兼容改造", limit=5, auto_sync_mode="balanced")
    assert auto_synced_sniff["synced"] is True
    assert auto_synced_sniff["task_id"] == task["task_id"]

    started = workspace_start_session(workspace, "修复 ArticleFeignClient 调用链")
    session_id = started["session_id"]
    workspace_log_session_event(workspace, session_id, "tool_call", {"tool_name": "mc_lookup", "query": "ArticleFeignClient", "project": "task-service"})
    workspace_end_session(workspace, session_id, outcome="完成 Feign 调用链定位", verified_by=["manual-check"])

    synced_case = workspace_sync_case_to_artifacts(
        workspace,
        session_id,
        task_id=task["task_id"],
        auto_sync_mode="strict",
    )
    assert synced_case["synced"] is True
    assert synced_case["auto_sync_mode"] == "strict"
    assert "auto_sync_recommendation" in synced_case
    design = get_task_artifact(workspace, task["task_id"], "design")
    change_log = get_task_artifact(workspace, task["task_id"], "change_log")
    current_summary = get_task_artifact(workspace, task["task_id"], "current_summary")
    assert "Case Design" in design["content"]
    assert "Source References" in design["content"]
    assert "Case synced" in change_log["content"] or "Source session" in change_log["content"]
    assert "Source Session" in current_summary["content"]
    task_spaces_after = list_task_spaces(workspace)
    task_row_after = next(item for item in task_spaces_after["active_tasks"] if item["task_id"] == task["task_id"])
    assert task_row_after["last_activity_source"] == "sync_case_artifacts"

    auto_synced_case = workspace_sync_case_to_artifacts(workspace, session_id, auto_sync_mode="aggressive")
    assert auto_synced_case["synced"] is True
    assert auto_synced_case["auto_sync_mode"] == "aggressive"
    # Auto-resolve picks the best-matching task; any existing task_id is acceptable.
    assert auto_synced_case["task_id"]
    all_tasks = list_task_spaces(workspace)
    all_ids = {t["task_id"] for t in all_tasks["active_tasks"]}
    assert auto_synced_case["task_id"] in all_ids


def test_session_memory_flow(tmp_path: Path):
    from memory_center.core.orchestrator import (
        workspace_end_session,
        workspace_log_session_event,
        workspace_recent_sessions,
        workspace_resume_context,
        workspace_session_summary,
        workspace_start_session,
        workspace_suggest_case,
    )

    source = Path("examples/spring-cloud-demo")
    target = tmp_path / "session-memory-demo"
    import shutil
    shutil.copytree(source, target)
    workspace = target / ".memory-center" / "workspace.yaml"
    lines = workspace.read_text(encoding="utf-8").splitlines()
    lines = [f"root: {target.as_posix()}" if line.startswith("root:") else line for line in lines]
    workspace.write_text("\n".join(lines) + "\n", encoding="utf-8")

    config = load_workspace_config(workspace)
    store = WorkspaceStore(workspace)
    ensure_default_rules(store)
    reindex_workspace(config, store)

    started = workspace_start_session(workspace, "修复 ArticleFeignClient 调用链")
    session_id = started["session_id"]
    workspace_log_session_event(workspace, session_id, "user_prompt", {"intent": "修复 ArticleFeignClient 调用链"})
    workspace_log_session_event(workspace, session_id, "tool_call", {"tool_name": "mc_lookup", "query": "ArticleFeignClient"})
    workspace_log_session_event(workspace, session_id, "tool_result", {"project": "task-service", "file_path": "task-service/src/main/java/com/example/task/ArticleMoveService.java"})
    large_payload = {"tool_name": "memory_context_tool", "query": "ArticleFeignClient", "project": "task-service", "blob": "X" * 6000}
    offloaded = workspace_log_session_event(workspace, session_id, "tool_result", large_payload)
    ended = workspace_end_session(workspace, session_id, outcome="完成 Feign 调用链定位", verified_by=["manual-check"])

    assert ended["ended"] is True
    assert ended["summary"]["tool_calls"] == ["mc_lookup"]
    assert offloaded["payload_ref"]

    summary = workspace_session_summary(workspace, session_id)
    assert summary["found"] is True
    assert summary["summary"]["outcome"] == "完成 Feign 调用链定位"
    assert summary["events"]
    assert any(event.get("payload_ref") for event in summary["events"])
    assert summary["session_overview"]["memory_layer"] == "L0_session_events"
    assert summary["session_overview"]["payload_ref_count"] >= 1

    recent = workspace_recent_sessions(workspace, limit=5)
    assert recent["recent_sessions"]
    assert recent["recent_sessions"][0]["session_id"] == session_id

    resume = workspace_resume_context(workspace, "ArticleFeignClient 调用链", limit=3)
    assert resume["related_sessions"]
    assert resume["suggested_context"]

    draft = workspace_suggest_case(workspace, session_id)
    assert draft["found"] is True
    assert draft["draft_case"]["task"]
    assert "risk_points" in draft["draft_case"]
    assert draft["draft_case"]["evidence_refs"]
    assert draft["draft_case"]["source_session_id"] == session_id
    assert draft["draft_case"]["source_refs"]


def test_resume_context_uses_cjk_bigram_fallback_for_long_intent(tmp_path: Path):
    from memory_center.core.orchestrator.resume import workspace_resume_context
    from memory_center.core.orchestrator.write import workspace_record_case
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    workspace_record_case(
        workspace,
        "实现多次接单任务的数据自动隔离",
        ["task-service"],
        ["TaskIsolation.java"],
        source_session_id="session-cjk-fallback",
    )

    resume = workspace_resume_context(workspace, "任务自动隔离", limit=5)

    assert resume["related_case_match_mode"] == "cjk_bigram"
    assert [item["source_session_id"] for item in resume["related_cases"]] == ["session-cjk-fallback"]


def test_graph_query_context_and_impact(tmp_path):
    from memory_center.core.governance.rules import ensure_default_rules
    from memory_center.core.indexing.reindex import reindex_workspace
    from memory_center.core.orchestrator import (
        memory_callees,
        memory_callers,
        memory_context,
        memory_impact,
        memory_plan_change,
        memory_query_hybrid,
        memory_search_code,
        memory_symbol,
        memory_verify_checklist,
        workspace_status,
    )
    from memory_center.core.storage.workspace import WorkspaceStore
    from memory_center.core.workspace.config import load_workspace_config

    workspace = str(_copy_root_demo_workspace(tmp_path))
    config = load_workspace_config(workspace)
    store = WorkspaceStore(workspace)
    ensure_default_rules(store)
    counts = reindex_workspace(config, store)

    assert counts["graph_nodes"] > 0
    assert counts["graph_edges"] > 0
    assert counts["semantic_docs"] > 0
    query_result = memory_query_hybrid(workspace, "oldPubTime ArticleFeignClient", 5)
    assert query_result["results"]
    assert query_result["knowledge_state"]["state"] == "FOUND"
    code_search = memory_search_code(workspace, "ArticleFeignClient", scope="task-service", limit=5)
    assert code_search["hits"]
    assert code_search["progressive"]["summary"]["top_hit_count"] >= 1
    exact_query = memory_query_hybrid(workspace, "ArticleFeignClient", 5)
    assert exact_query["results"][0]["node"]["type"] == "Class"
    assert exact_query["results"][0]["node"]["name"] == "ArticleFeignClient"
    symbol = memory_symbol(workspace, "ArticleFeignClient", limit=5)
    assert symbol["found"] is True
    assert symbol["best_match"]["type"] == "Class"
    assert symbol["best_match"]["name"] == "ArticleFeignClient"
    assert symbol["best_match"]["line"] > 0
    assert symbol["matches"][0]["node"]["type"] == "Class"
    symbol_compact = memory_symbol(workspace, "ArticleFeignClient", limit=5, view="compact", budget="small")
    assert symbol_compact["found"] is True
    assert symbol_compact["best_match"]["type"] == "Class"
    assert symbol_compact["matches"]
    assert symbol_compact["summary_lines"]
    assert symbol_compact["summary_lines"][0].startswith("Best Class ArticleFeignClient")
    assert "lookup" in symbol_compact
    callers = memory_callers(workspace, "ArticleFeignClient", depth=2, limit=20)
    assert callers["found"] is True
    assert callers["chain_summary"]["items"]
    assert "--" in callers["chain_summary"]["items"][0]["text"]
    callers_compact = memory_callers(workspace, "ArticleFeignClient", depth=2, limit=20, view="compact", budget="small")
    assert callers_compact["found"] is True
    assert callers_compact["direction"] == "callers"
    assert "callers" not in callers_compact
    assert callers_compact["chain_summary"]["items"]
    assert callers_compact["summary_lines"]
    assert callers_compact["summary_lines"][0].startswith("Target Class ArticleFeignClient")
    callees = memory_callees(workspace, "ArticleFeignClient", depth=2, limit=20)
    assert callees["found"] is True
    assert callees["chain_summary"]["items"]
    assert "--" in callees["chain_summary"]["items"][0]["text"]
    callees_compact = memory_callees(workspace, "ArticleFeignClient", depth=2, limit=20, view="compact", budget="small")
    assert callees_compact["found"] is True
    assert callees_compact["direction"] == "callees"
    assert "callees" not in callees_compact
    assert callees_compact["chain_summary"]["items"]
    assert callees_compact["summary_lines"]
    assert callees_compact["summary_lines"][0].startswith("Target Class ArticleFeignClient")
    status = workspace_status(workspace)
    assert status["semantic_index"]["ready"] is True
    assert status["semantic_index"]["backend"] == "sparse"
    assert status["index_counts"]["semantic_docs"] > 0
    assert "memory_layers" in status
    assert status["memory_layers"]["L0_session_events"]["event_count"] >= 0
    assert status["memory_layers"]["L3_workspace_profile"]["instruction_files"] >= 0
    assert "core_memory_blocks" in status
    assert status["core_memory_blocks"]["block_count"] >= 4
    assert "memory_overview" in status
    assert status["memory_overview"]["layer_order"][0] == "L0_session_events"
    assert "active_task_spaces" in status
    assert "current_focus_task" in status
    context = memory_context(workspace, "ArticleFeignClient")
    assert context["found"] is True
    assert context["lookup"]["retrieval_summary"]["exact_matches"] >= 1
    assert context["lookup"]["entrypoints"]
    assert "INJECTS_BEAN" in context["evidence_summary"]["edge_types"]
    assert context["progressive"]["summary"]["node"]
    context_compact = memory_context(workspace, "ArticleFeignClient", view="compact", budget="small")
    assert context_compact["found"] is True
    assert context_compact["incoming_summary"]["items"] or context_compact["outgoing_summary"]["items"]
    assert "incoming" not in context_compact
    assert "outgoing" not in context_compact
    assert context_compact["summary_lines"]
    assert context_compact["summary_lines"][0].startswith("Node Class ArticleFeignClient")

    callers_project_compact = memory_callers(workspace, "ArticleFeignClient", depth=2, limit=20, project="task-service", view="compact", budget="small")
    assert callers_project_compact["project_scope"]["uses_cross_project_anchor"] is True
    assert callers_project_compact["project_evidence"]
    assert any(line.startswith("Project evidence: ") for line in callers_project_compact["summary_lines"])

    context_project_compact = memory_context(workspace, "ArticleFeignClient", project="task-service", view="compact", budget="small")
    assert context_project_compact["project_scope"]["uses_cross_project_anchor"] is True
    assert context_project_compact["project_evidence"]
    assert any(line.startswith("Project evidence: ") for line in context_project_compact["summary_lines"])
    context_project_full = memory_context(workspace, "ArticleFeignClient", project="task-service")
    assert context_project_full["lookup"]["entrypoints"][0]["role"] == "anchor"
    assert any(item.get("role") == "project_evidence" for item in context_project_full["lookup"]["entrypoints"])
    impact = memory_impact(workspace, "MoveArticleRequest")
    assert impact["found"] is True
    assert impact["lookup"]["retrieval_summary"]["exact_matches"] >= 1
    assert impact["evidence_summary"]["confirmed_count"] >= 0
    assert impact["progressive"]["summary"]["target"]
    assert impact["candidate_paths"]
    assert impact["recommended_path"]["candidate_type"]
    impact_compact = memory_impact(workspace, "MoveArticleRequest", view="compact", budget="small")
    assert impact_compact["found"] is True
    assert "confirmed_impacts" not in impact_compact
    assert "confirmed_summary" in impact_compact
    assert "candidate_paths" in impact_compact
    assert impact_compact["summary_lines"]
    assert impact_compact["summary_lines"][0].startswith("Target")
    impact_project_compact = memory_impact(workspace, "ArticleFeignClient", direction="upstream", max_depth=2, project="task-service", view="compact", budget="small")
    assert impact_project_compact["project_scope"]["uses_cross_project_anchor"] is True
    assert impact_project_compact["project_evidence"]
    assert any(line.startswith("Project evidence: ") for line in impact_project_compact["summary_lines"])
    assert impact_project_compact["lookup"]["entrypoints"][0]["role"] == "anchor"
    plan = memory_plan_change(workspace, "MoveArticleRequest")
    assert plan["found"] is True
    assert plan["plan"]
    assert plan["candidate_paths"]
    checklist = memory_verify_checklist(workspace, "MoveArticleRequest")
    assert checklist["checklist"]


def test_trusted_graph_edges_and_evidence_based_impact(tmp_path: Path):
    import shutil

    from memory_center.core.indexing.reindex import reindex_workspace
    from memory_center.core.orchestrator import memory_impact, memory_query_hybrid
    from memory_center.core.storage.runtime import RuntimeStore
    from memory_center.core.storage.workspace import WorkspaceStore
    from memory_center.core.workspace.config import load_workspace_config

    source = Path("examples/spring-cloud-demo")
    target = tmp_path / "trusted-demo"
    shutil.copytree(source, target)
    workspace = target / ".memory-center" / "workspace.yaml"
    lines = workspace.read_text(encoding="utf-8").splitlines()
    lines = [f"root: {target.as_posix()}" if line.startswith("root:") else line for line in lines]
    workspace.write_text("\n".join(lines) + "\n", encoding="utf-8")

    config = load_workspace_config(workspace)
    store = WorkspaceStore(workspace)
    reindex_workspace(config, store)
    graph = RuntimeStore(store.graph_db_path)

    field = graph.find_nodes("newPubTime", types=["Field"], limit=5)[0]
    upstream = graph.traverse_edges(field["id"], direction="upstream", max_depth=3, limit=100)
    assert any(edge["type"] == "READS_FIELD" for edge in upstream)
    assert any(edge["evidence"] for edge in upstream)
    assert any(edge["source"]["name"] == "ArticleMoveConsumer.consume" for edge in upstream)
    assert any(edge["type"] == "READS_FIELD" and edge["evidence"].get("receiver_type") == "MoveArticleRequest" for edge in upstream)

    urlmd5 = graph.find_nodes("urlmd5", types=["Field"], limit=5)[0]
    urlmd5_upstream = graph.traverse_edges(urlmd5["id"], direction="upstream", max_depth=3, limit=100)
    assert any(edge["type"] == "READS_FIELD" and edge["source"]["name"] == "ArticleMoveService.move" for edge in urlmd5_upstream)

    consumer = graph.find_nodes("ArticleMoveConsumer", types=["Class"], limit=5)[0]
    consumer_outgoing = graph.traverse_edges(consumer["id"], direction="downstream", max_depth=1, limit=50)
    assert any(edge["type"] == "INJECTS_BEAN" and edge["target"]["name"] == "ArticleMoveService" for edge in consumer_outgoing)
    assert consumer["metadata"].get("package") == "com.example.task"
    assert consumer["line"] > 0

    mq_index = store.read_json("mq-index.json", [])
    assert any(item["class_name"] == "ArticleMoveConsumer" and item["method_name"] == "consume" for item in mq_index)

    move_service = graph.find_nodes("ArticleMoveService", types=["Class"], limit=5)[0]
    service_outgoing = graph.traverse_edges(move_service["id"], direction="downstream", max_depth=1, limit=50)
    assert any(edge["type"] == "INJECTS_BEAN" and edge["target"]["name"] == "ArticleFeignClient" for edge in service_outgoing)
    assert move_service["metadata"].get("package")
    assert "field_name" not in move_service["metadata"]
    assert move_service["line"] > 0

    impact = memory_impact(workspace, "newPubTime", direction="upstream")
    assert impact["found"] is True
    assert "confirmed_impacts" in impact
    assert "probable_impacts" in impact
    assert "possible_impacts" in impact
    assert impact["candidate_paths"]
    assert impact["candidate_paths"][0]["target"]
    assert "unknown_risks" in impact

    report = doctor(workspace, self_test=True, query_probe=lambda path, text: memory_query_hybrid(path, text, limit=5))
    assert report["ok"] is True
    assert report["self_test"]["query_matches"] > 0
    assert any(item["name"] == "semantic:docs" and item["ok"] for item in report["checks"])


def test_group_query_and_status(tmp_path: Path):
    from memory_center.core.orchestrator import group_impact, group_query, group_status

    workspace_a = _copy_demo_workspace(tmp_path, "group-demo-a")
    workspace_b = _copy_demo_workspace(tmp_path, "group-demo-b")
    for workspace in [workspace_a, workspace_b]:
        config = load_workspace_config(workspace)
        store = WorkspaceStore(workspace)
        ensure_default_rules(store)
        reindex_workspace(config, store)

    home = tmp_path / "home" / ".memory-center"
    register_workspace("demo-a", workspace_a, home=home)
    register_workspace("demo-b", workspace_b, home=home)
    create_group("backend-platform", home=home)
    add_to_group("backend-platform", "demo-a", home=home)
    add_to_group("backend-platform", "demo-b", home=home)

    status = group_status("backend-platform", home=home)
    assert status["workspace_count"] == 2
    assert status["index_totals"]["files"] >= 10
    assert status["semantic_index"]["ready"] is True
    assert status["semantic_index"]["ready_workspace_count"] == 2
    assert status["semantic_index"]["doc_count"] >= 2
    assert status["semantic_index"]["backends"]["sparse"] == 2
    assert status["bridge_counts"]["FEIGN_SERVICE"] >= 2
    assert status["bridge_counts"]["FEIGN_ENDPOINT"] >= 2
    assert status["bridge_counts"]["MQ_TOPIC_CONFIG"] >= 2

    result = group_query("backend-platform", "ArticleFeignClient", limit=5, home=home)
    assert result["workspace_count"] == 2
    assert result["merged_matches"]
    assert any(item["node"]["name"] == "ArticleFeignClient" for item in result["merged_matches"])
    assert result["target_types"][0] == "FeignClient"
    assert result["merged_matches"][0]["node"]["type"] == "FeignClient"
    assert result["retrieval_summary"]["exact_matches"] >= 1
    assert result["retrieval_summary"]["returned_matches"] == len(result["merged_matches"])
    assert any("graph" in item["retrieval_sources"] or "exact" in item["retrieval_sources"] for item in result["merged_matches"])
    assert result["progressive"]["summary"]["top_nodes"]
    assert result["progressive"]["evidence"]["entrypoints"]
    assert any(bridge["type"] in {"FEIGN_SERVICE", "FEIGN_ENDPOINT"} for bridge in result["related_bridges"])

    mq_result = group_query("backend-platform", "article-pubtime-change", limit=10, home=home)
    assert any(bridge["type"] == "MQ_TOPIC_CONFIG" for bridge in mq_result["related_bridges"])
    assert mq_result["progressive"]["evidence"]["bridge_preview"]

    impact = group_impact("backend-platform", "ArticleFeignClient", home=home)
    assert impact["found"] is True
    assert impact["risk_level"] in {"high", "medium"}
    assert impact["impacted_workspaces"] == ["demo-a", "demo-b"]
    assert "FeignClient" in impact["target_types"]
    assert "entrypoints" in impact["lookup"]
    assert impact["lookup"]["entrypoints"]
    assert impact["evidence_summary"]["bridge_evidence_count"] >= 1
    assert "FEIGN_ENDPOINT" in impact["evidence_summary"]["bridge_types"]
    assert impact["progressive"]["summary"]["impacted_workspace_count"] >= 1
    assert impact["progressive"]["evidence"]["top_bridges"]
    assert impact["confirmed_impacts"] or impact["probable_impacts"]
    assert all(bridge["type"] in {"FEIGN_SERVICE", "FEIGN_ENDPOINT"} for bridge in impact["related_bridges"])
    assert impact["related_bridges"][0]["type"] == "FEIGN_ENDPOINT"
    assert all(
        item["impact"]["type"] not in {"CONTAINS", "DECLARES"}
        for item in impact["confirmed_impacts"] + impact["probable_impacts"] + impact["possible_impacts"]
        if item.get("kind") == "graph"
    )
    graph_types = [item["impact"]["type"] for item in impact["confirmed_impacts"] + impact["probable_impacts"] if item.get("kind") == "graph"]
    assert "INJECTS_BEAN" in graph_types
    assert "IMPORTS" in graph_types
    assert graph_types.index("INJECTS_BEAN") < graph_types.index("IMPORTS")

    topic_impact = group_impact("backend-platform", "article-pubtime-change", home=home)
    assert topic_impact["found"] is True
    assert any(bridge["type"] in {"MQ_TOPIC_CONFIG", "MQ_TOPIC_SHARED"} for bridge in topic_impact["related_bridges"])
    assert topic_impact["related_bridges"][0]["type"] == "MQ_TOPIC_CONFIG"
    assert topic_impact["progressive"]["detail"]["impacted_workspaces"]


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_http_bridge_routes(tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


def test_local_embedding_backend_is_optional_and_selectable(tmp_path: Path):
    import shutil

    import memory_center.core.retrieval.semantic as semantic

    source = Path("examples/spring-cloud-demo")
    target = tmp_path / "semantic-backend-demo"
    shutil.copytree(source, target)
    workspace = target / ".memory-center" / "workspace.yaml"
    lines = workspace.read_text(encoding="utf-8").splitlines()
    lines = [f"root: {target.as_posix()}" if line.startswith("root:") else line for line in lines]
    workspace.write_text("\n".join(lines) + "\n", encoding="utf-8")

    config = load_workspace_config(workspace)
    store = WorkspaceStore(workspace)
    ensure_default_rules(store)

    old_backend = os.environ.get("MEMORY_CENTER_SEMANTIC_BACKEND")
    old_model = os.environ.get("MEMORY_CENTER_EMBEDDING_MODEL")
    old_loader = semantic._load_sentence_transformer_model

    class FakeSentenceTransformer:
        def encode(self, texts, normalize_embeddings=True):
            vectors = []
            for text in texts:
                length = float(len(text) or 1)
                vowels = float(sum(1 for ch in text.lower() if ch in "aeiou") or 1)
                vectors.append([length, vowels])
            return vectors

    try:
        os.environ["MEMORY_CENTER_SEMANTIC_BACKEND"] = "sentence-transformers"
        os.environ["MEMORY_CENTER_EMBEDDING_MODEL"] = "fake-local-model"
        semantic._load_sentence_transformer_model = lambda model_name: FakeSentenceTransformer()
        counts = reindex_workspace(config, store)
        assert counts["semantic_docs"] > 0
        assert counts["semantic_backend"] == "sentence-transformers"
        assert counts["requested_semantic_backend"] == "sentence-transformers"
        assert counts["vector_scope"] == "selective"
        assert counts["vector_candidate_count"] > 0
        assert counts["dense_doc_count"] == counts["vector_embeddings"]
        assert counts["vector_status"] == "ready"
        assert counts["vector_disabled_reason"] is None

        stats = semantic.semantic_index_stats(workspace)
        assert stats["backend"] == "sentence-transformers"
        assert stats["requested_backend"] == "sentence-transformers"
        assert stats["model"] == "fake-local-model"

        hits = semantic.semantic_query(workspace, "ArticleFeignClient", limit=3)
        assert hits
        assert all(item["backend"] == "sentence-transformers-ann" for item in hits)
    finally:
        semantic._load_sentence_transformer_model = old_loader
        if old_backend is None:
            os.environ.pop("MEMORY_CENTER_SEMANTIC_BACKEND", None)
        else:
            os.environ["MEMORY_CENTER_SEMANTIC_BACKEND"] = old_backend
        if old_model is None:
            os.environ.pop("MEMORY_CENTER_EMBEDDING_MODEL", None)
        else:
            os.environ["MEMORY_CENTER_EMBEDDING_MODEL"] = old_model


def test_resolve_task_score_threshold(tmp_path: Path):
    """Resolve respects score_threshold AND the strong-evidence gate.

    P0 修复后语义：plan 正文命中只是 fuzzy，status 加分需强证据前置——
    因此 threshold=1 时 score=1 且 strong=False，不自动写入（更保守）；
    标题强命中（title_exact）不受影响。
    """
    workspace = _copy_demo_workspace(tmp_path, "resolve-threshold")

    created = create_task_space(workspace, title="站点连通性告警治理")
    task_id = created["task_id"]
    update_task_artifact(workspace, task_id, "plan", "# Plan\n\n处理站点连通性告警")

    # Plan-content signature overlap gives strong evidence — matches above threshold
    resolved_overlap = resolve_task_space(workspace, intent="继续处理站点告警连通性问题", create_if_missing=False, score_threshold=1)
    assert resolved_overlap["resolved"] is True
    assert resolved_overlap["task_id"] == task_id
    assert resolved_overlap["score_threshold"] == 1

    # Threshold above actual score — must not match even with strong evidence
    resolved_high = resolve_task_space(workspace, intent="继续处理站点告警连通性问题", create_if_missing=False, score_threshold=8)
    assert resolved_high["resolved"] is False
    assert resolved_high["task_id"] == ""
    assert resolved_high["score_threshold"] == 8

    # Title exact hit — strong evidence, auto-matches regardless of threshold
    resolved_title = resolve_task_space(workspace, intent="站点连通性告警治理", create_if_missing=False, score_threshold=5)
    assert resolved_title["resolved"] is True
    assert resolved_title["task_id"] == task_id
    assert resolved_title["resolution_confidence"] == "high"


def test_resolve_task_space_returns_ambiguous_for_equal_candidates(tmp_path: Path):
    workspace = _copy_demo_workspace(tmp_path, "resolve-ambiguous")

    first = create_task_space(workspace, title="alpha Feign DTO 兼容治理", intent="处理 Feign DTO 兼容治理")
    second = create_task_space(workspace, title="beta Feign DTO 兼容治理", intent="处理 Feign DTO 兼容治理")
    update_task_artifact(workspace, first["task_id"], "plan", "# Plan\n\n处理 Feign DTO 兼容治理")
    update_task_artifact(workspace, second["task_id"], "plan", "# Plan\n\n处理 Feign DTO 兼容治理")

    resolved = resolve_task_space(
        workspace,
        intent="继续处理 Feign DTO 兼容治理",
        create_if_missing=False,
        score_threshold=1,
        limit_candidates=5,
    )

    assert resolved["resolved"] is False
    assert resolved["resolution_status"] == "ambiguous"
    assert len(resolved["candidates"]) >= 2
    assert "task_signature" in resolved
    assert "task_signature" in resolved["candidates"][0]


def test_current_summary_snapshot_replaces_and_archives_history(tmp_path: Path):
    workspace = _copy_demo_workspace(tmp_path, "summary-snapshot")
    task = create_task_space(workspace, title="摘要快照任务")
    task_id = task["task_id"]

    first = update_task_current_summary_snapshot(workspace, task_id, "# Current Summary\n\n第一版摘要", source="test")
    second = update_task_current_summary_snapshot(workspace, task_id, "# Current Summary\n\n第二版摘要", source="test")

    current = get_task_artifact(workspace, task_id, "current_summary")
    history = get_task_artifact(workspace, task_id, "summary_history")
    assert first["write_mode"] == "replace_snapshot"
    assert second["write_mode"] == "replace_snapshot"
    assert "第二版摘要" in current["content"]
    assert "第一版摘要" not in current["content"]
    assert "第一版摘要" in history["content"]


def test_resume_packet_includes_readiness_fields(tmp_path: Path):
    workspace = _copy_demo_workspace(tmp_path, "resume-readiness")
    task = create_task_space(workspace, title="恢复包质量任务")
    workspace_sync_sniff_to_artifacts(workspace, "ArticleFeignClient 调用链恢复", task_id=task["task_id"], limit=5)

    packet = workspace_resume_packet(workspace, task_id=task["task_id"], view="full", limit=5)
    compact = workspace_resume_packet(workspace, task_id=task["task_id"], view="compact", limit=5)

    assert packet["resume_readiness"] in {"ready", "partial", "blocked"}
    assert "missing_context" in packet
    assert "stale_artifacts" in packet
    assert "must_read_refs" in packet
    assert 0 <= packet["confidence"] <= 1
    assert packet["task_health"]["available"] is True
    assert packet["task_health"]["health"] in {"good", "warning", "bad"}
    assert "issue_count" in packet["task_health"]
    assert "repair_plan_hint" in packet
    assert "resume_readiness" in compact
    assert "confidence" in compact
    assert "task_health" in compact
    assert "repair_plan_hint" in compact


def test_resume_packet_recommends_repair_plan_for_unhealthy_task(tmp_path: Path):
    workspace = _copy_demo_workspace(tmp_path, "resume-health-repair")
    task = create_task_space(workspace, title="恢复包健康检查任务")

    packet = workspace_resume_packet(workspace, task_id=task["task_id"], view="full", limit=5)
    compact = workspace_resume_packet(workspace, task_id=task["task_id"], view="compact", limit=5)

    assert packet["task_health"]["available"] is True
    assert packet["task_health"]["issue_count"] >= 1
    assert packet["repair_plan_hint"]["available"] is True
    assert "task_repair_plan" in packet["repair_plan_hint"]["recommended_action"]
    assert compact["task_health"]["issue_count"] >= 1
    assert compact["repair_plan_hint"]["available"] is True


def test_workspace_task_resume_check_for_ready_and_repair_states(tmp_path: Path):
    workspace = _copy_demo_workspace(tmp_path, "task-resume-check")
    empty = create_task_space(workspace, title="接手检查未同步任务")
    synced = create_task_space(workspace, title="接手检查已同步任务")
    workspace_sync_sniff_to_artifacts(workspace, "ArticleFeignClient 接手检查", task_id=synced["task_id"], limit=5)

    needs_repair = workspace_task_resume_check(workspace, task_id=empty["task_id"], limit=5)
    ready = workspace_task_resume_check(workspace, task_id=synced["task_id"], limit=5)

    assert needs_repair["workflow"] == "task-resume-check"
    assert needs_repair["status"] == "needs_repair"
    assert needs_repair["repair_plan"]
    assert needs_repair["recommended_next_step"]["action"] == "repair_plan"
    assert ready["status"] == "ready"
    assert ready["can_resume"] is True
    assert ready["repair_plan"] == []
    assert ready["recommended_next_step"]["action"] == "resume"


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_work_resume_check_cli(tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_work_resume_check_cli_mcp_http_core_contract_consistency(tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


def test_task_space_health_reports_issues_and_suggestions(tmp_path: Path):
    workspace = _copy_demo_workspace(tmp_path, "task-health")
    task = create_task_space(workspace, title="任务空间健康检查")

    health = task_space_health(workspace, task["task_id"])

    assert health["task_id"] == task["task_id"]
    assert health["health"] in {"good", "warning", "bad"}
    assert 0 <= health["score"] <= 100
    assert health["issues"]
    assert health["repair_suggestions"]
    assert "artifact_summary" in health
    assert "write_receipts" in health


def test_task_space_health_detects_similar_tasks(tmp_path: Path):
    workspace = _copy_demo_workspace(tmp_path, "task-health-similar")
    first = create_task_space(workspace, title="alpha ArticleFeignClient DTO 兼容治理")
    second = create_task_space(workspace, title="beta ArticleFeignClient DTO 兼容治理")
    update_task_artifact(workspace, first["task_id"], "plan", "# Plan\n\nArticleFeignClient DTO 兼容治理")
    update_task_artifact(workspace, second["task_id"], "plan", "# Plan\n\nArticleFeignClient DTO 兼容治理")

    health = task_space_health(workspace, first["task_id"])

    assert any(issue["code"] == "similar_task_spaces" for issue in health["issues"])
    similar = next(issue for issue in health["issues"] if issue["code"] == "similar_task_spaces")
    assert similar["evidence"]


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_task_spaces_health_and_cli(tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


def test_task_space_repair_plan_for_unhealthy_task(tmp_path: Path):
    workspace = _copy_demo_workspace(tmp_path, "task-repair-plan")
    task = create_task_space(workspace, title="修复计划任务")

    plan = task_space_repair_plan(workspace, task["task_id"])

    assert plan["task_id"] == task["task_id"]
    assert plan["apply_supported"] is False
    assert plan["reason"] == "repair_plan_is_read_only"
    assert plan["issue_count"] >= 1
    assert plan["repair_plan"]
    assert any(item["issue_code"] == "empty_current_summary" for item in plan["repair_plan"])
    assert all("command" in item for item in plan["repair_plan"])
    assert plan["safe_to_auto_apply"] is False


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_task_space_repair_plan_cli_for_synced_task(tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


def test_task_space_repair_execute_dry_run_and_apply(tmp_path: Path):
    workspace = _copy_demo_workspace(tmp_path, "task-repair-execute")
    task = create_task_space(workspace, title="执行修复任务")
    task_id = task["task_id"]

    dry_run = task_space_repair_execute(workspace, task_id)
    assert dry_run["dry_run"] is True
    assert dry_run["applied"] is False
    assert dry_run["supported_count"] >= 1
    assert any(item["target"] == "current_summary" for item in dry_run["execution_plan"])

    blocked = task_space_repair_execute(workspace, task_id, apply=True)
    assert blocked["dry_run"] is False
    assert blocked["blocked_count"] >= 1
    assert any(item.get("reason") == "intent_required" for item in blocked["results"])

    applied = task_space_repair_execute(workspace, task_id, apply=True, intent="ArticleFeignClient 执行修复任务")
    assert applied["applied"] is True
    assert applied["executed_count"] >= 1
    assert applied["remaining_health"]["issue_count"] < dry_run["source_repair_plan"]["issue_count"]


def test_task_space_repair_execute_preserves_safety_boundaries(tmp_path: Path):
    workspace = _copy_demo_workspace(tmp_path, "task-repair-safety")
    task = create_task_space(workspace, title="安全边界修复任务")
    task_id = task["task_id"]

    update_task_artifact(workspace, task_id, "context", "# Context\n\n已有人工上下文，不能被 dry-run 或 current-summary 修复覆盖。")
    update_task_artifact(workspace, task_id, "plan", "# Plan\n\n## Next Actions / 下一步\n\n- 保留已有人工计划。")
    before_context = get_task_artifact(workspace, task_id, "context")["content"]
    before_plan = get_task_artifact(workspace, task_id, "plan")["content"]
    before_summary = get_task_artifact(workspace, task_id, "current_summary")["content"]

    dry_run = task_space_repair_execute(workspace, task_id)
    assert dry_run["dry_run"] is True
    assert dry_run["applied"] is False
    assert get_task_artifact(workspace, task_id, "context")["content"] == before_context
    assert get_task_artifact(workspace, task_id, "plan")["content"] == before_plan

    blocked = task_space_repair_execute(workspace, task_id, apply=True)
    assert blocked["blocked_count"] >= 1
    assert any(item.get("target") == "current_summary" and item.get("reason") == "intent_required" for item in blocked["results"])
    assert get_task_artifact(workspace, task_id, "current_summary")["content"] == before_summary
    assert before_context in get_task_artifact(workspace, task_id, "context")["content"]
    assert before_plan in get_task_artifact(workspace, task_id, "plan")["content"]


def test_task_space_repair_execute_does_not_fake_missing_write_receipts(tmp_path: Path):
    workspace = _copy_demo_workspace(tmp_path, "task-repair-no-fake-receipts")
    task = create_task_space(workspace, title="缺少凭证修复任务")
    task_id = task["task_id"]
    task_dir = Path(str(task["path"]))
    (task_dir / "current-summary.md").write_text("# Current Summary\n\n目标：验证缺失凭证不会被伪造。\n\n下一步：执行检查。", encoding="utf-8")
    (task_dir / "context.md").write_text("# Context\n\n直接写入的历史上下文，没有经过 write receipt。", encoding="utf-8")
    (task_dir / "plan.md").write_text("# Plan\n\n## Next Actions / 下一步\n\n- 检查 missing_write_receipts。", encoding="utf-8")

    plan = task_space_repair_plan(workspace, task_id)
    assert any(item["issue_code"] == "missing_write_receipts" for item in plan["repair_plan"])

    applied = task_space_repair_execute(workspace, task_id, apply=True, intent="ArticleFeignClient 缺失凭证检查")
    receipt_steps = [item for item in applied["results"] if item.get("issue_code") == "missing_write_receipts"]
    assert receipt_steps
    assert all(item.get("status") == "skipped" for item in receipt_steps)
    assert all(item.get("applied") is not True for item in receipt_steps)


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_task_space_repair_execute_cli(tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


def test_touch_task_activity(tmp_path: Path):
    """touch_task_activity updates last_activity_source and updated_at."""
    workspace = _copy_demo_workspace(tmp_path, "touch-activity")
    created = create_task_space(workspace, title="touch 测试任务", intent="测试 last_activity_source")
    task_id = created["task_id"]

    # Initial source set by create_task_space
    listed = list_task_spaces(workspace)
    task_entry = next(t for t in listed["active_tasks"] if t["task_id"] == task_id)
    assert task_entry["last_activity_source"] == "create_task_space"

    # Update via touch_task_activity
    result = touch_task_activity(workspace, task_id, "sync-sniff")
    assert result["last_activity_source"] == "sync-sniff"
    assert result["task_id"] == task_id

    # Confirm persisted
    listed2 = list_task_spaces(workspace)
    task_entry2 = next(t for t in listed2["active_tasks"] if t["task_id"] == task_id)
    assert task_entry2["last_activity_source"] == "sync-sniff"


def test_write_paths_record_last_activity_source(tmp_path: Path):
    """update_task_artifact and append_task_change_log write last_activity_source."""
    workspace = _copy_demo_workspace(tmp_path, "activity-source-write")
    created = create_task_space(workspace, title="write path 源追踪")
    task_id = created["task_id"]

    update_task_artifact(workspace, task_id, "plan", "# Plan\n\n第一步", source="sync-sniff")
    listed = list_task_spaces(workspace)
    task_entry = next(t for t in listed["active_tasks"] if t["task_id"] == task_id)
    assert task_entry["last_activity_source"] == "sync-sniff"

    append_task_change_log(workspace, task_id, "完成第一步", source="mcp")
    listed2 = list_task_spaces(workspace)
    task_entry2 = next(t for t in listed2["active_tasks"] if t["task_id"] == task_id)
    assert task_entry2["last_activity_source"] == "mcp"

    update_task_status(workspace, task_id, "blocked")
    listed3 = list_task_spaces(workspace)
    task_entry3 = next(t for t in listed3["active_tasks"] if t["task_id"] == task_id)
    assert task_entry3["last_activity_source"] == "update_task_status"


def test_append_only_artifact_guards_against_overwrite(tmp_path: Path):
    workspace = _copy_demo_workspace(tmp_path, "append-only-guards")

    original = get_artifact(workspace, "context")["content"]
    updated = update_artifact(workspace, "context", "# Context\n\n模型想整篇覆盖")
    guarded = get_artifact(workspace, "context")["content"]
    assert updated["write_mode"] == "append_guarded"
    assert original in guarded
    assert "模型想整篇覆盖" in guarded

    task = create_task_space(workspace, title="append only task")
    original_task_plan = get_task_artifact(workspace, task["task_id"], "plan")["content"]
    task_update = update_task_artifact(workspace, task["task_id"], "plan", "# Plan\n\n模型想覆盖任务计划")
    guarded_task_plan = get_task_artifact(workspace, task["task_id"], "plan")["content"]
    assert task_update["write_mode"] == "append_guarded"
    assert original_task_plan in guarded_task_plan
    assert "模型想覆盖任务计划" in guarded_task_plan

    store = WorkspaceStore(workspace)
    audit_rows = store.read_jsonl(ARTIFACT_WRITE_AUDIT_FILE, limit=20)
    assert audit_rows
    assert any(row["scope"] == "workspace" and row["write_mode"] == "append_guarded" for row in audit_rows)
    assert any(row["scope"] == "task_space" and row["write_mode"] == "append_guarded" for row in audit_rows)


def test_sniff_auto_sync_mode_strategies():
    from memory_center.core.orchestrator import _build_sniff_auto_sync_recommendation

    task_resolution = {
        "resolved": True,
        "task_id": "task-1",
        "score": 3,
        "score_threshold": 3,
        "candidates": [{"task_id": "task-1"}],
    }

    strict = _build_sniff_auto_sync_recommendation(task_resolution, "medium", auto_sync_mode="strict")
    balanced = _build_sniff_auto_sync_recommendation(task_resolution, "medium", auto_sync_mode="balanced")
    aggressive = _build_sniff_auto_sync_recommendation(task_resolution, "high", auto_sync_mode="aggressive")
    fallback = _build_sniff_auto_sync_recommendation(task_resolution, "medium", auto_sync_mode="unknown-mode")

    assert strict["mode"] == "strict"
    assert strict["recommended"] is False
    assert balanced["mode"] == "balanced"
    assert balanced["recommended"] is True
    assert aggressive["mode"] == "aggressive"
    assert aggressive["recommended"] is True
    assert fallback["mode"] == "balanced"


def test_case_risk_level_with_evidence_refs():
    from memory_center.core.orchestrator import _case_risk_level

    low_case = {
        "risk_points": [],
        "evidence_refs": [{"event_type": "tool_call", "tool_name": "memory_symbol_tool", "query": "ArticleMoveService"}],
    }
    medium_case = {
        "risk_points": ["字段兼容待验证"],
        "evidence_refs": [{"event_type": "tool_call", "tool_name": "memory_impact_tool", "target": "MoveArticleRequest"}],
    }
    high_case = {
        "risk_points": ["Feign contract 兼容风险", "MQ topic 变更风险"],
        "evidence_refs": [
            {"event_type": "tool_call", "tool_name": "workspace_check_contract_tool", "query": "ArticleFeignClient"},
            {"event_type": "tool_call", "tool_name": "mc_lookup", "query": "article-pubtime-change topic kafka"},
        ],
    }

    assert _case_risk_level(low_case) == "low"
    assert _case_risk_level(medium_case) in {"medium", "high"}
    assert _case_risk_level(high_case) == "high"


def test_partial_reindex_only_touches_changed_project(tmp_path: Path):
    """Partial reindex with --project only rebuilds graph nodes for that project."""
    from memory_center.core.storage.runtime import RuntimeStore
    from memory_center.core.workspace.config import load_workspace_config

    workspace = _copy_demo_workspace(tmp_path, "partial-reindex")
    config = load_workspace_config(workspace)
    store = WorkspaceStore(workspace)
    ensure_default_rules(store)

    full_counts = reindex_workspace(config, store)
    assert full_counts["mode"] == "full"
    assert full_counts["graph_nodes"] > 0

    graph = RuntimeStore(store.graph_db_path)
    full_nodes_before = graph.counts()["nodes"]

    partial_counts = reindex_workspace(config, store, projects=["user-service"])
    assert partial_counts["mode"] == "partial"
    assert partial_counts["graph_nodes"] > 0
    assert partial_counts["graph_nodes"] == full_nodes_before


def test_index_mirror_on_write_and_prefer_backend(tmp_path: Path):
    """write_json mirrors to SQLite; read_json_prefer_backend returns same data."""
    from memory_center.core.workspace.config import load_workspace_config

    workspace = _copy_demo_workspace(tmp_path, "index-mirror")
    config = load_workspace_config(workspace)
    store = WorkspaceStore(workspace)
    ensure_default_rules(store)
    reindex_workspace(config, store)

    file_index_from_file = store.read_json("file-index.json", [])
    file_index_from_backend = store.read_json_prefer_backend("file-index.json", [])
    assert file_index_from_file == file_index_from_backend
    assert len(file_index_from_backend) > 0


def test_backend_query_with_project_and_type(tmp_path: Path):
    """memory_backend_query supports project and payload_type filtering."""
    workspace = _copy_demo_workspace(tmp_path, "backend-query-filter")
    config = load_workspace_config(workspace)
    store = WorkspaceStore(workspace)
    ensure_default_rules(store)
    reindex_workspace(config, store)

    from memory_center.core.orchestrator import workspace_log_session_event, workspace_start_session

    session = workspace_start_session(workspace, "backend query test")
    workspace_log_session_event(workspace, session["session_id"], "tool_call", {"tool_name": "mc_lookup", "project": "task-service", "query": "ArticleFeignClient"})
    workspace_log_session_event(workspace, session["session_id"], "tool_call", {"tool_name": "memory_symbol_tool", "project": "article-service", "query": "ArticleService"})

    result_all = memory_backend_query(workspace, collection="session-events.jsonl", limit=50)
    assert result_all["records"]["count"] >= 2

    result_by_project = memory_backend_query(workspace, collection="session-events.jsonl", project="task-service", limit=50)
    assert result_by_project["records"]["count"] >= 1



def test_token_benchmark_save_and_compare(tmp_path: Path):
    workspace = _copy_demo_workspace(tmp_path, "benchmark-baseline")
    config = load_workspace_config(workspace)
    store = WorkspaceStore(workspace)
    reindex_workspace(config, store)

    # Save baseline
    from memory_center.core.orchestrator import memory_eval_token_benchmark_compare, memory_eval_token_benchmark_save
    save_result = memory_eval_token_benchmark_save(str(workspace), intent="benchmark test", limit=5)
    assert save_result["saved"] is True
    baseline_path = Path(save_result["path"])
    assert baseline_path.exists()

    # Compare against clean baseline — use generous threshold for run-to-run variation
    compare_result = memory_eval_token_benchmark_compare(str(workspace), intent="benchmark test", limit=5, regression_threshold=50)
    assert compare_result.get("baseline_status") != "no_baseline"
    assert len(compare_result.get("regressions", [])) == 0

    # Corrupt baseline: artificially inflate a token count
    import json as json_mod
    baseline = json_mod.loads(baseline_path.read_text(encoding="utf-8"))
    first_func = list(baseline["functions"].keys())[0]
    baseline["functions"][first_func]["small"]["tokens"] *= 5
    baseline_path.write_text(json_mod.dumps(baseline, ensure_ascii=False, indent=2), encoding="utf-8")

    # Compare again — should detect regression
    compare_result = memory_eval_token_benchmark_compare(str(workspace), intent="benchmark test", limit=5, regression_threshold=10)
    assert len(compare_result.get("regressions", [])) > 0


def test_agent_guidance_trend_records_and_alerts(tmp_path: Path):
    workspace = _copy_demo_workspace(tmp_path, "agent-guidance-trend")
    from memory_center.core.benchmark.trending import (
        check_regression_alerts,
        generate_benchmark_report,
        get_agent_guidance_trends,
        record_agent_guidance_trend,
    )
    from memory_center.core.orchestrator import memory_eval_agent_guidance_trend

    for idx in range(5):
        record_agent_guidance_trend(
            workspace,
            intent=f"stable-{idx}",
            agent_next_step_count=3,
            invalid_search_suggestion_count=0,
            invalid_search_reduction_rate=1.0,
            score=95,
            quality="high",
            passed=True,
            agent_next_step_actions=["inspect_top_result"],
        )
    record_agent_guidance_trend(
        workspace,
        intent="regressed",
        agent_next_step_count=0,
        invalid_search_suggestion_count=2,
        invalid_search_reduction_rate=0.0,
        score=45,
        quality="low",
        passed=False,
        agent_next_step_actions=[],
    )

    trends = get_agent_guidance_trends(workspace, limit=20)
    assert trends["summary"]["total_trend_points"] == 6
    assert trends["summary"]["latest_invalid_search_suggestion_count"] == 2
    assert trends["regressions"]

    alerts = check_regression_alerts(workspace)
    assert alerts["agent_guidance"]["total_regressions"] >= 1
    assert any(alert["type"] == "agent_guidance" for alert in alerts["alerts"])
    report = generate_benchmark_report(workspace)
    assert report["agent_guidance_trends"]["summary"]["total_trend_points"] == 6

    sampled = memory_eval_agent_guidance_trend(workspace, intent="ArticleFeignClient 调用链", limit=5)
    assert sampled["recorded"] is True
    assert sampled["trend_point"]["agent_next_step_count"] >= 1


def test_agent_guidance_adoption_trend_records_and_alerts(tmp_path: Path):
    workspace = _copy_demo_workspace(tmp_path, "agent-guidance-adoption-trend")
    from memory_center.core.benchmark.trending import (
        check_regression_alerts,
        generate_benchmark_report,
        get_agent_guidance_adoption_trends,
        record_agent_guidance_adoption_trend,
    )
    from memory_center.core.orchestrator import memory_eval_agent_guidance_adoption_trend

    for idx in range(5):
        record_agent_guidance_adoption_trend(
            workspace,
            total_guidance_events=10,
            adopted_count=9,
            missed_count=1,
            adoption_rate=0.9,
            score=95,
            quality="high",
            session_id=f"stable-{idx}",
            missed_action_counts={"inspect_top_result": 1},
        )
    record_agent_guidance_adoption_trend(
        workspace,
        total_guidance_events=10,
        adopted_count=2,
        missed_count=8,
        adoption_rate=0.2,
        score=45,
        quality="low",
        session_id="regressed",
        missed_action_counts={"inspect_top_result": 8},
    )

    trends = get_agent_guidance_adoption_trends(workspace, limit=20)
    assert trends["summary"]["total_trend_points"] == 6
    assert trends["summary"]["latest_adoption_rate"] == 0.2
    assert trends["summary"]["latest_missed_action_counts"]["inspect_top_result"] == 8
    assert trends["regressions"]

    alerts = check_regression_alerts(workspace)
    assert alerts["agent_guidance_adoption"]["total_regressions"] >= 1
    assert any(alert["type"] == "agent_guidance_adoption" for alert in alerts["alerts"])
    report = generate_benchmark_report(workspace)
    assert report["agent_guidance_adoption_trends"]["summary"]["total_trend_points"] == 6

    session = workspace_start_session(workspace, "adoption trend sample")
    sid = session["session_id"]
    workspace_log_session_event(
        workspace,
        sid,
        "agent_guidance",
        {"agent_next_steps": [{"action": "refine_query", "command": "mc_lookup(mode=query)"}]},
    )
    workspace_log_session_event(workspace, sid, "tool_call", {"tool_name": "mc_lookup", "query": "ArticleFeignClient"})
    sampled = memory_eval_agent_guidance_adoption_trend(workspace, session_id=sid, limit=20)
    assert sampled["recorded"] is True
    assert sampled["trend_point"]["adoption_rate"] == 1.0
    assert sampled["trend_point"]["missed_action_counts"] == {}


def test_agent_guidance_replay_trend_records_and_alerts(tmp_path: Path):
    workspace = _copy_demo_workspace(tmp_path, "agent-guidance-replay-trend")
    from memory_center.core.benchmark.trending import (
        check_regression_alerts,
        generate_benchmark_report,
        get_agent_guidance_replay_trends,
        record_agent_guidance_replay_trend,
    )
    from memory_center.core.orchestrator import memory_eval_agent_guidance_replay_trend

    for idx in range(5):
        record_agent_guidance_replay_trend(
            workspace,
            total_guidance_events=10,
            adopted_count=9,
            missed_count=1,
            bypassed_count=0,
            unobservable_count=0,
            adoption_rate=0.9,
            bypass_rate=0.0,
            unobservable_rate=0.0,
            score=95,
            quality="high",
            session_id=f"stable-{idx}",
            reason_counts={"matched_expected_tool": 9},
        )
    record_agent_guidance_replay_trend(
        workspace,
        total_guidance_events=10,
        adopted_count=2,
        missed_count=1,
        bypassed_count=6,
        unobservable_count=1,
        adoption_rate=0.2,
        bypass_rate=0.6,
        unobservable_rate=0.1,
        score=45,
        quality="low",
        session_id="regressed",
        reason_counts={"local_search_or_non_memory_tool_used": 6},
    )

    trends = get_agent_guidance_replay_trends(workspace, limit=20)
    assert trends["summary"]["total_trend_points"] == 6
    assert trends["summary"]["latest_bypass_rate"] == 0.6
    assert trends["summary"]["reason_counts"]["local_search_or_non_memory_tool_used"] == 6
    assert trends["regressions"]

    alerts = check_regression_alerts(workspace)
    assert alerts["agent_guidance_replay"]["total_regressions"] >= 1
    assert any(alert["type"] == "agent_guidance_replay" for alert in alerts["alerts"])
    report = generate_benchmark_report(workspace)
    assert report["agent_guidance_replay_trends"]["summary"]["total_trend_points"] == 6

    session = workspace_start_session(workspace, "replay trend sample")
    sid = session["session_id"]
    workspace_log_session_event(
        workspace,
        sid,
        "agent_guidance",
        {"agent_next_steps": [{"action": "refine_query", "command": "mc_lookup(mode=query)"}]},
    )
    workspace_log_session_event(workspace, sid, "tool_call", {"tool_name": "mc_lookup", "query": "ArticleFeignClient"})
    sampled = memory_eval_agent_guidance_replay_trend(workspace, session_id=sid, limit=20)
    assert sampled["recorded"] is True
    assert sampled["trend_point"]["adoption_rate"] == 1.0
    assert sampled["trend_point"]["reason_counts"] == {"matched_expected_tool": 1}


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_eval_agent_guidance_trend_available_from_cli_and_http(tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_eval_agent_guidance_adoption_trend_available_from_cli_and_http(tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_eval_agent_guidance_replay_trend_available_from_cli_and_http(tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


def test_bm25_scoring_returns_results(tmp_path: Path):
    workspace = _copy_demo_workspace(tmp_path, "bm25-test")
    config = load_workspace_config(workspace)
    store = WorkspaceStore(workspace)
    reindex_workspace(config, store)

    from memory_center.core.retrieval.semantic import semantic_query
    results = semantic_query(str(workspace), "ArticleFeignClient", limit=5)
    assert len(results) > 0
    # BM25 results should have score and backend field
    assert "score" in results[0]
    assert results[0].get("backend") in ("bm25", "sparse")



def _copy_demo_workspace(tmp_path: Path, name: str) -> Path:
    import shutil

    source = Path("examples/spring-cloud-demo")
    target = tmp_path / name
    shutil.copytree(source, target)
    workspace = target / ".memory-center" / "workspace.yaml"
    lines = workspace.read_text(encoding="utf-8").splitlines()
    lines = [f"root: {target.as_posix()}" if line.startswith("root:") else line for line in lines]
    workspace.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return workspace


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_http_mutations_require_post_and_remote_binding_requires_token(tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
