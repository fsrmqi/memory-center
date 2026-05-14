from pathlib import Path
import json
import socket
import threading
import os
from urllib.request import urlopen

from typer.testing import CliRunner

from memory_center.cli.main import app
from memory_center.core.artifacts import (
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
    update_task_status,
    update_artifact,
    update_task_artifact,
)
from memory_center.core.config import load_workspace_config
from memory_center.core.exporters import export_mermaid
from memory_center.core.indexer import reindex_workspace
from memory_center.core.orchestrator import workspace_sniff, workspace_trace
from memory_center.core.registry import add_to_group, create_group, register_workspace
from memory_center.core.rules import ensure_default_rules
from memory_center.core.store import WorkspaceStore
from memory_center.core.validators import doctor
from memory_center.http.server import create_handler


def test_demo_workspace_indexes_spring_cloud_patterns(tmp_path: Path):
    source = Path("examples/spring-cloud-demo")
    target = tmp_path / "demo"
    import shutil
    shutil.copytree(source, target)
    workspace = target / ".memory-center" / "workspace.yaml"

    # Force an absolute fixture root after copying.
    lines = workspace.read_text(encoding="utf-8").splitlines()
    lines = [f"root: {target.as_posix()}" if line.startswith("root:") else line for line in lines]
    workspace.write_text("\n".join(lines) + "\n", encoding="utf-8")

    config = load_workspace_config(workspace)
    store = WorkspaceStore(workspace)
    counts = reindex_workspace(config, store)
    ensure_default_rules(store)

    assert counts["files"] >= 5
    assert counts["apis"] >= 1
    assert counts["feigns"] >= 1
    assert counts["mq"] >= 1
    assert counts["semantic_docs"] > 0

    sniffed = workspace_sniff(workspace, "oldPubTime newPubTime Kafka ArticleFeignClient move")
    assert sniffed["candidate_files"]
    assert sniffed["related_rules"]
    assert sniffed["risk_level"] == "high"
    assert "symbolic_context" in sniffed
    assert "mermaid" in sniffed["symbolic_context"]
    assert "entities_mermaid" in sniffed["symbolic_context"]
    assert "flow_mermaid" in sniffed["symbolic_context"]
    assert "memory_search_code" in sniffed["symbolic_context"]["flow_mermaid"]
    assert "memory_impact" in sniffed["symbolic_context"]["flow_mermaid"]
    assert sniffed["symbolic_context"]["flow_flags"]["has_contract"] is True
    assert sniffed["symbolic_context"]["flow_flags"]["has_mq"] is True
    assert sniffed["symbolic_context"]["flow_flags"]["risk_level"] == "high"
    assert "resolved_task" in sniffed
    assert "task_candidates" in sniffed
    assert "workspace_check_contract (Feign/API)" in sniffed["symbolic_context"]["flow_mermaid"]
    assert "MQ compatibility review" in sniffed["symbolic_context"]["flow_mermaid"]

    traced = workspace_trace(workspace, "article-pubtime-change")
    assert traced["matched_mq"]

    diagram = export_mermaid(workspace)
    assert "flowchart LR" in diagram
    assert "article-service" in diagram

    report = doctor(workspace)
    assert report["ok"] is True


def test_record_case_cli_writes_history(tmp_path: Path):
    source = Path("examples/spring-cloud-demo")
    target = tmp_path / "record-case-demo"
    import shutil
    shutil.copytree(source, target)
    workspace = target / ".memory-center" / "workspace.yaml"
    lines = workspace.read_text(encoding="utf-8").splitlines()
    lines = [f"root: {target.as_posix()}" if line.startswith("root:") else line for line in lines]
    workspace.write_text("\n".join(lines) + "\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "record-case",
            "--workspace",
            str(workspace),
            "--task",
            "验证 ArticleFeignClient 影响面",
            "--project",
            "task-service",
            "--file",
            "task-service/src/main/java/com/example/task/ArticleMoveService.java",
            "--flow",
            "query -> context -> impact",
            "--risk-point",
            "Feign 契约兼容",
            "--verified-by",
            "unit-test",
        ],
    )
    assert result.exit_code == 0
    store = WorkspaceStore(workspace)
    rows = store.read_jsonl("cross-service-task-memory.jsonl", limit=10)
    assert rows
    assert rows[-1]["task"] == "验证 ArticleFeignClient 影响面"
    assert rows[-1]["risk_points"] == ["Feign 契约兼容"]


def test_cli_version_flag():
    runner = CliRunner()
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "memory-center" in result.stdout
    assert "1.2.0" in result.stdout


def test_workspace_service_maintenance_commands(tmp_path: Path):
    source = Path("examples/spring-cloud-demo")
    target = tmp_path / "workspace-maintenance-demo"
    import shutil
    shutil.copytree(source, target)
    workspace = target / ".memory-center" / "workspace.yaml"
    lines = workspace.read_text(encoding="utf-8").splitlines()
    lines = [f"root: {target.as_posix()}" if line.startswith("root:") else line for line in lines]
    workspace.write_text("\n".join(lines) + "\n", encoding="utf-8")

    runner = CliRunner()

    add_result = runner.invoke(
        app,
        [
            "workspace",
            "add-service",
            "--workspace",
            str(workspace),
            "--name",
            "ucap-cloud-open-api",
            "--path",
            "ucap-cloud-open-api",
            "--type",
            "spring-boot-service",
            "--service-name",
            "ucap-cloud-open-api",
        ],
    )
    assert add_result.exit_code == 0
    config = load_workspace_config(workspace)
    assert any(item.name == "ucap-cloud-open-api" and item.path == "ucap-cloud-open-api" for item in config.services)

    list_result = runner.invoke(app, ["workspace", "list-services", "--workspace", str(workspace)])
    assert list_result.exit_code == 0
    assert "ucap-cloud-open-api" in list_result.stdout

    remove_result = runner.invoke(
        app,
        [
            "workspace",
            "remove-service",
            "--workspace",
            str(workspace),
            "--name",
            "ucap-cloud-open-api",
        ],
    )
    assert remove_result.exit_code == 0
    config_after = load_workspace_config(workspace)
    assert all(item.name != "ucap-cloud-open-api" for item in config_after.services)


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
    artifact = get_artifact(workspace, "context")
    assert "共享上下文" in artifact["content"]

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
    task_context = get_task_artifact(workspace, task_id, "context")
    assert "修复 Feign DTO 兼容" in task_context["content"]
    task_summary = get_task_artifact(workspace, task_id, "current_summary")
    assert "Current Summary / 当前最短上下文" in task_summary["content"]
    updated_task = update_task_artifact(workspace, task_id, "plan", "# Plan\n\n先做影响分析")
    assert updated_task["updated"] is True
    changed_task = append_task_change_log(workspace, task_id, "完成第一轮分析", keep_recent=5)
    assert changed_task["appended"] is True
    archived_task = archive_task_space(workspace, task_id, reason="done")
    assert archived_task["archived"] is True
    listed = list_task_spaces(workspace, include_archived=True)
    assert listed["archived_tasks"]

    active_task = create_task_space(workspace, title="站点连通性告警治理")
    update_task_artifact(workspace, active_task["task_id"], "plan", "# Plan\n\n处理站点连通性告警与告警链路")
    resolved = resolve_task_space(workspace, intent="继续处理站点告警连通性问题", create_if_missing=False, limit_candidates=3)
    assert resolved["resolved"] is True
    assert resolved["task_id"] == active_task["task_id"]
    assert resolved["candidates"]
    status_updated = update_task_status(workspace, active_task["task_id"], "blocked")
    assert status_updated["status"] == "blocked"


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
    synced_sniff = workspace_sync_sniff_to_artifacts(workspace, "修改 Feign DTO 并评估 MQ 影响", limit=5, task_id=task["task_id"])
    assert synced_sniff["synced"] is True
    assert synced_sniff["task_id"] == task["task_id"]
    context = get_task_artifact(workspace, task["task_id"], "context")
    plan = get_task_artifact(workspace, task["task_id"], "plan")
    summary_artifact = get_task_artifact(workspace, task["task_id"], "current_summary")
    assert "Current Task Context / 当前任务上下文" in context["content"]
    assert "Suggested Plan / 建议执行计划" in plan["content"]
    assert "Risk level" in summary_artifact["content"]

    auto_synced_sniff = workspace_sync_sniff_to_artifacts(workspace, "继续处理 Feign DTO 兼容改造", limit=5)
    assert auto_synced_sniff["synced"] is True
    assert auto_synced_sniff["task_id"] == task["task_id"]

    started = workspace_start_session(workspace, "修复 ArticleFeignClient 调用链")
    session_id = started["session_id"]
    workspace_log_session_event(workspace, session_id, "tool_call", {"tool_name": "memory_query_tool", "query": "ArticleFeignClient", "project": "task-service"})
    workspace_end_session(workspace, session_id, outcome="完成 Feign 调用链定位", verified_by=["manual-check"])

    synced_case = workspace_sync_case_to_artifacts(workspace, session_id, task_id=task["task_id"])
    assert synced_case["synced"] is True
    design = get_task_artifact(workspace, task["task_id"], "design")
    change_log = get_task_artifact(workspace, task["task_id"], "change_log")
    current_summary = get_task_artifact(workspace, task["task_id"], "current_summary")
    assert "Session Learnings / 会话沉淀" in design["content"]
    assert "Session `" in change_log["content"]
    assert "Session:" in current_summary["content"]

    auto_synced_case = workspace_sync_case_to_artifacts(workspace, session_id)
    assert auto_synced_case["synced"] is True
    assert auto_synced_case["task_id"] == task["task_id"]


def test_session_memory_flow(tmp_path: Path):
    from memory_center.core.orchestrator import (
        workspace_suggest_case,
        workspace_end_session,
        workspace_log_session_event,
        workspace_recent_sessions,
        workspace_resume_context,
        workspace_session_summary,
        workspace_start_session,
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
    workspace_log_session_event(workspace, session_id, "tool_call", {"tool_name": "memory_query_tool", "query": "ArticleFeignClient"})
    workspace_log_session_event(workspace, session_id, "tool_result", {"project": "task-service", "file_path": "task-service/src/main/java/com/example/task/ArticleMoveService.java"})
    ended = workspace_end_session(workspace, session_id, outcome="完成 Feign 调用链定位", verified_by=["manual-check"])

    assert ended["ended"] is True
    assert ended["summary"]["tool_calls"] == ["memory_query_tool"]

    summary = workspace_session_summary(workspace, session_id)
    assert summary["found"] is True
    assert summary["summary"]["outcome"] == "完成 Feign 调用链定位"
    assert summary["events"]

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


def test_graph_query_context_and_impact(tmp_path):
    from memory_center.core.config import load_workspace_config
    from memory_center.core.indexer import reindex_workspace
    from memory_center.core.orchestrator import (
        memory_callers,
        memory_callees,
        memory_context,
        memory_impact,
        memory_plan_change,
        memory_query,
        memory_search_code,
        memory_symbol,
        memory_verify_checklist,
        workspace_status,
    )
    from memory_center.core.rules import ensure_default_rules
    from memory_center.core.store import WorkspaceStore

    workspace = "examples/spring-cloud-demo/.memory-center/workspace.yaml"
    config = load_workspace_config(workspace)
    store = WorkspaceStore(workspace)
    ensure_default_rules(store)
    counts = reindex_workspace(config, store)

    assert counts["graph_nodes"] > 0
    assert counts["graph_edges"] > 0
    assert counts["semantic_docs"] > 0
    query_result = memory_query(workspace, "oldPubTime ArticleFeignClient", 5)
    assert query_result["matches"]
    assert query_result["semantic_hits"]
    assert query_result["retrieval_summary"]["exact_matches"] >= 1
    assert query_result["retrieval_summary"]["semantic_matches"] >= 1
    assert query_result["retrieval_summary"]["returned_matches"] == len(query_result["matches"])
    assert any("semantic" in item["retrieval_sources"] for item in query_result["matches"])
    assert query_result["progressive"]["summary"]["top_nodes"]
    code_search = memory_search_code(workspace, "ArticleFeignClient", scope="task-service", limit=5)
    assert code_search["hits"]
    assert code_search["progressive"]["summary"]["top_hit_count"] >= 1
    symbol = memory_symbol(workspace, "ArticleMoveService", limit=5)
    assert symbol["found"] is True
    callers = memory_callers(workspace, "ArticleMoveService", depth=2, limit=20)
    assert callers["found"] is True
    callees = memory_callees(workspace, "ArticleMoveService", depth=2, limit=20)
    assert callees["found"] is True
    status = workspace_status(workspace)
    assert status["semantic_index"]["ready"] is True
    assert status["semantic_index"]["backend"] == "sparse"
    assert status["index_counts"]["semantic_docs"] > 0
    assert "active_task_spaces" in status
    context = memory_context(workspace, "ArticleFeignClient")
    assert context["found"] is True
    assert context["lookup"]["retrieval_summary"]["exact_matches"] >= 1
    assert context["lookup"]["entrypoints"]
    assert "INJECTS_BEAN" in context["evidence_summary"]["edge_types"]
    assert context["progressive"]["summary"]["node"]
    impact = memory_impact(workspace, "MoveArticleRequest")
    assert impact["found"] is True
    assert impact["lookup"]["retrieval_summary"]["semantic_matches"] >= 1
    assert impact["evidence_summary"]["confirmed_count"] >= 0
    assert impact["progressive"]["summary"]["target"]
    plan = memory_plan_change(workspace, "MoveArticleRequest")
    assert plan["found"] is True
    assert plan["plan"]
    checklist = memory_verify_checklist(workspace, "MoveArticleRequest")
    assert checklist["checklist"]


def test_trusted_graph_edges_and_evidence_based_impact(tmp_path: Path):
    import shutil
    from memory_center.core.config import load_workspace_config
    from memory_center.core.graph import GraphStore
    from memory_center.core.indexer import reindex_workspace
    from memory_center.core.orchestrator import memory_impact
    from memory_center.core.store import WorkspaceStore

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
    graph = GraphStore(store.graph_db_path)

    field = graph.find_nodes("newPubTime", types=["Field"], limit=5)[0]
    upstream = graph.neighbors(field["id"], direction="upstream", max_depth=3, limit=100)
    assert any(edge["type"] == "READS_FIELD" for edge in upstream)
    assert any(edge["evidence"] for edge in upstream)
    assert any(edge["source"]["name"] == "ArticleMoveConsumer.consume" for edge in upstream)
    assert any(edge["type"] == "READS_FIELD" and edge["evidence"].get("receiver_type") == "MoveArticleRequest" for edge in upstream)

    urlmd5 = graph.find_nodes("urlmd5", types=["Field"], limit=5)[0]
    urlmd5_upstream = graph.neighbors(urlmd5["id"], direction="upstream", max_depth=3, limit=100)
    assert any(edge["type"] == "READS_FIELD" and edge["source"]["name"] == "ArticleMoveService.move" for edge in urlmd5_upstream)

    consumer = graph.find_nodes("ArticleMoveConsumer", types=["Class"], limit=5)[0]
    consumer_outgoing = graph.neighbors(consumer["id"], direction="downstream", max_depth=1, limit=50)
    assert any(edge["type"] == "INJECTS_BEAN" and edge["target"]["name"] == "ArticleMoveService" for edge in consumer_outgoing)

    mq_index = store.read_json("mq-index.json", [])
    assert any(item["class_name"] == "ArticleMoveConsumer" and item["method_name"] == "consume" for item in mq_index)

    move_service = graph.find_nodes("ArticleMoveService", types=["Class"], limit=5)[0]
    service_outgoing = graph.neighbors(move_service["id"], direction="downstream", max_depth=1, limit=50)
    assert any(edge["type"] == "INJECTS_BEAN" and edge["target"]["name"] == "ArticleFeignClient" for edge in service_outgoing)

    impact = memory_impact(workspace, "newPubTime", direction="upstream")
    assert impact["found"] is True
    assert "confirmed_impacts" in impact
    assert "probable_impacts" in impact
    assert "possible_impacts" in impact
    assert "unknown_risks" in impact

    report = doctor(workspace, self_test=True)
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
    assert result["retrieval_summary"]["semantic_matches"] >= 1
    assert result["retrieval_summary"]["returned_matches"] == len(result["merged_matches"])
    assert any("semantic" in item["retrieval_sources"] for item in result["merged_matches"])
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
    assert impact["lookup"]["retrieval_summary"]["exact_matches"] >= 1
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
    assert all(bridge["type"] in {"MQ_TOPIC_CONFIG", "MQ_TOPIC_SHARED"} for bridge in topic_impact["related_bridges"])
    assert topic_impact["related_bridges"][0]["type"] == "MQ_TOPIC_CONFIG"
    assert topic_impact["progressive"]["detail"]["impacted_workspaces"]


def test_http_bridge_routes(tmp_path: Path):
    from http.server import ThreadingHTTPServer
    from memory_center.core.orchestrator import workspace_end_session, workspace_log_session_event, workspace_start_session

    workspace = _copy_demo_workspace(tmp_path, "http-demo")
    config = load_workspace_config(workspace)
    store = WorkspaceStore(workspace)
    ensure_default_rules(store)
    reindex_workspace(config, store)
    session = workspace_start_session(workspace, "HTTP bridge route test")
    session_id = session["session_id"]
    workspace_log_session_event(workspace, session_id, "tool_call", {"tool_name": "memory_query_tool", "query": "ArticleFeignClient", "project": "task-service"})
    workspace_end_session(workspace, session_id, outcome="HTTP route validation", verified_by=["test"])

    home = tmp_path / "home" / ".memory-center"
    register_workspace("http-demo", workspace, home=home)
    create_group("http-group", home=home)
    add_to_group("http-group", "http-demo", home=home)

    # Route closures use the default registry home, so point HOME at the temp registry.
    import os
    old_home = os.environ.get("HOME")
    os.environ["HOME"] = str(home.parent)
    try:
        server = ThreadingHTTPServer(("127.0.0.1", _free_port()), create_handler(workspace))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"

        health = json.loads(urlopen(f"{base}/health").read().decode("utf-8"))
        assert health["ok"] is True

        status = json.loads(urlopen(f"{base}/group/status?group=http-group").read().decode("utf-8"))
        assert status["workspace_count"] == 1
        assert "bridge_counts" in status
        assert status["semantic_index"]["ready"] is True
        assert status["semantic_index"]["backends"]["sparse"] == 1

        artifacts = json.loads(urlopen(f"{base}/workspace/artifacts").read().decode("utf-8"))
        assert artifacts["artifacts"]
        context_artifact = json.loads(urlopen(f"{base}/workspace/artifact?name=context").read().decode("utf-8"))
        assert context_artifact["name"] == "context"
        context_outline = json.loads(urlopen(f"{base}/workspace/artifact/outline?name=context").read().decode("utf-8"))
        assert context_outline["sections"]
        context_search = json.loads(urlopen(f"{base}/workspace/artifact/context?intent=shared%20context&limit=3").read().decode("utf-8"))
        assert "summary" in context_search
        updated_artifact = json.loads(urlopen(f"{base}/workspace/artifact/update?name=context&content=HTTP-shared-context").read().decode("utf-8"))
        assert updated_artifact["updated"] is True
        changed_artifact = json.loads(urlopen(f"{base}/workspace/change-log/append?entry=HTTP-change-log-entry").read().decode("utf-8"))
        assert changed_artifact["appended"] is True
        compacted_log = json.loads(urlopen(f"{base}/workspace/change-log/compact?keep_recent=5").read().decode("utf-8"))
        assert "compacted" in compacted_log
        task_space = json.loads(urlopen(f"{base}/workspace/task-space/create?title=HTTP%20Feign%20Task").read().decode("utf-8"))
        assert task_space["created"] is True
        task_id = task_space["task_id"]
        task_spaces = json.loads(urlopen(f"{base}/workspace/task-spaces").read().decode("utf-8"))
        assert task_spaces["active_tasks"]
        sniff_sync = json.loads(urlopen(f"{base}/workspace/artifacts/sync-sniff?intent=HTTP%20Feign%20task&limit=5&task_id={task_id}").read().decode("utf-8"))
        assert sniff_sync["synced"] is True

        query = json.loads(urlopen(f"{base}/workspace/query?text=ArticleFeignClient").read().decode("utf-8"))
        assert query["matches"]
        assert query["retrieval_summary"]["exact_matches"] >= 1
        assert query["retrieval_summary"]["semantic_matches"] >= 1
        search = json.loads(urlopen(f"{base}/workspace/search-code?text=ArticleFeignClient&scope=task-service").read().decode("utf-8"))
        assert search["hits"]
        symbol = json.loads(urlopen(f"{base}/workspace/symbol?name=ArticleMoveService").read().decode("utf-8"))
        assert symbol["found"] is True
        callers = json.loads(urlopen(f"{base}/workspace/callers?symbol=ArticleMoveService&depth=2").read().decode("utf-8"))
        assert callers["found"] is True
        callees = json.loads(urlopen(f"{base}/workspace/callees?symbol=ArticleMoveService&depth=2").read().decode("utf-8"))
        assert callees["found"] is True
        plan = json.loads(urlopen(f"{base}/workspace/plan-change?target=MoveArticleRequest").read().decode("utf-8"))
        assert plan["found"] is True
        checklist = json.loads(urlopen(f"{base}/workspace/verify-checklist?target=MoveArticleRequest").read().decode("utf-8"))
        assert checklist["checklist"]

        session_recent = json.loads(urlopen(f"{base}/workspace/sessions/recent?limit=5").read().decode("utf-8"))
        assert "recent_sessions" in session_recent
        assert session_recent["recent_sessions"]
        suggested_case = json.loads(urlopen(f"{base}/workspace/suggest-case?session_id={session_id}").read().decode("utf-8"))
        assert suggested_case["found"] is True
        assert suggested_case["draft_case"]["task"]
        case_sync = json.loads(urlopen(f"{base}/workspace/artifacts/sync-case?session_id={session_id}&task_id={task_id}").read().decode("utf-8"))
        assert case_sync["synced"] is True
        task_context = json.loads(urlopen(f"{base}/workspace/task-artifact?task_id={task_id}&name=context").read().decode("utf-8"))
        assert task_context["task_id"] == task_id

        group_query_payload = json.loads(urlopen(f"{base}/group/query?group=http-group&text=article-pubtime-change").read().decode("utf-8"))
        assert group_query_payload["related_bridges"]
        assert group_query_payload["retrieval_summary"]["semantic_matches"] >= 1
        assert group_query_payload["progressive"]["summary"]["workspace_count"] == 1

        group_impact_payload = json.loads(urlopen(f"{base}/group/impact?group=http-group&target=ArticleFeignClient").read().decode("utf-8"))
        assert group_impact_payload["found"] is True
        assert "FeignClient" in group_impact_payload["target_types"]
        assert group_impact_payload["lookup"]["entrypoints"]
        assert group_impact_payload["evidence_summary"]["bridge_evidence_count"] >= 1
        assert group_impact_payload["progressive"]["evidence"]["top_bridges"]
    finally:
        server.shutdown()
        server.server_close()
        if old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = old_home


def test_local_embedding_backend_is_optional_and_selectable(tmp_path: Path):
    import shutil
    import memory_center.core.semantic as semantic

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

        stats = semantic.semantic_index_stats(workspace)
        assert stats["backend"] == "sentence-transformers"
        assert stats["requested_backend"] == "sentence-transformers"
        assert stats["model"] == "fake-local-model"

        hits = semantic.semantic_query(workspace, "ArticleFeignClient", limit=3)
        assert hits
        assert all(item["backend"] == "sentence-transformers" for item in hits)
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


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
