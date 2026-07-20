import json
import os
import socket
import threading
from pathlib import Path
from urllib.parse import quote
from urllib.request import urlopen

from typer.testing import CliRunner

from memory_center import __version__
from memory_center.application.presentation import (
    export_mermaid,
    export_workspace_dashboard_html,
    export_workspace_dashboard_markdown,
)
from memory_center.application.tasks import execute_task_repair as task_space_repair_execute
from memory_center.cli.main import app
from memory_center.core.foundation.schemas import validate_schema_payload
from memory_center.core.governance.instructions import write_agent_instructions
from memory_center.core.governance.registry import add_to_group, create_group, register_workspace
from memory_center.core.governance.rules import ensure_default_rules
from memory_center.core.indexing.reindex import reindex_workspace
from memory_center.core.orchestrator import (
    memory_backend_query,
    memory_eval_agent_guidance,
    memory_eval_agent_guidance_adoption,
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
    memory_query_hybrid,
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
    task_spaces_health,
    touch_task_activity,
    update_artifact,
    update_task_artifact,
    update_task_current_summary_snapshot,
    update_task_status,
)
from memory_center.core.tasks.timeline import timeline_query
from memory_center.core.workspace.config import load_workspace_config
from memory_center.core.workspace.doctor import doctor
from memory_center.http.server import create_handler


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
            "--source-session-id",
            "session-demo-1",
            "--source-task-id",
            "task-demo-1",
        ],
    )
    assert result.exit_code == 0
    store = WorkspaceStore(workspace)
    rows = store.read_jsonl("cross-service-task-memory.jsonl", limit=10)
    receipt_rows = store.read_jsonl("write-receipts.jsonl", limit=20)
    assert rows
    assert receipt_rows
    assert rows[-1]["task"] == "验证 ArticleFeignClient 影响面"
    assert rows[-1]["risk_points"] == ["Feign 契约兼容"]
    assert rows[-1]["memory_layer"] == "L1_case_atom"
    assert rows[-1]["source_session_id"] == "session-demo-1"
    assert rows[-1]["source_task_id"] == "task-demo-1"
    assert rows[-1]["current_truth"] is True


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


def test_reindex_cli_defaults_to_parallel(monkeypatch, tmp_path: Path):
    workspace = _cli_project_workspace(tmp_path)
    observed: dict[str, object] = {}

    class _FakeConfig:
        root_path = Path(workspace).parent.parent

    monkeypatch.setattr("memory_center.cli.main.load_workspace_config", lambda wf: _FakeConfig())
    monkeypatch.setattr("memory_center.cli.main.WorkspaceStore", lambda wf: object())

    def _fake_reindex(config, store, *, projects=None, paths=None, parallel=False):
        observed["projects"] = projects
        observed["paths"] = paths
        observed["parallel"] = parallel
        return {"mode": "full"}

    monkeypatch.setattr("memory_center.cli.main.reindex_workspace", _fake_reindex)
    monkeypatch.setattr("memory_center.cli.main.ensure_default_rules", lambda store: None)
    monkeypatch.setattr("memory_center.cli.main.ensure_default_hooks", lambda store: None)
    monkeypatch.setattr("memory_center.cli.main.ensure_default_artifacts", lambda wf: None)
    monkeypatch.setattr("memory_center.cli.main.write_agent_instructions", lambda store, root: None)

    runner = CliRunner()
    result = runner.invoke(app, ["reindex", "--workspace", workspace])
    assert result.exit_code == 0
    assert observed["parallel"] is True
    assert observed["paths"] == []


def test_reindex_cli_can_disable_parallel(monkeypatch, tmp_path: Path):
    workspace = _cli_project_workspace(tmp_path)
    observed: dict[str, object] = {}

    class _FakeConfig:
        root_path = Path(workspace).parent.parent

    monkeypatch.setattr("memory_center.cli.main.load_workspace_config", lambda wf: _FakeConfig())
    monkeypatch.setattr("memory_center.cli.main.WorkspaceStore", lambda wf: object())

    def _fake_reindex(config, store, *, projects=None, paths=None, parallel=False):
        observed["parallel"] = parallel
        return {"mode": "full"}

    monkeypatch.setattr("memory_center.cli.main.reindex_workspace", _fake_reindex)
    monkeypatch.setattr("memory_center.cli.main.ensure_default_rules", lambda store: None)
    monkeypatch.setattr("memory_center.cli.main.ensure_default_hooks", lambda store: None)
    monkeypatch.setattr("memory_center.cli.main.ensure_default_artifacts", lambda wf: None)
    monkeypatch.setattr("memory_center.cli.main.write_agent_instructions", lambda store, root: None)

    runner = CliRunner()
    result = runner.invoke(app, ["reindex", "--workspace", workspace, "--no-parallel"])
    assert result.exit_code == 0
    assert observed["parallel"] is False


def test_query_cli_forwards_vector_options(monkeypatch, tmp_path: Path):
    workspace = _cli_project_workspace(tmp_path)
    observed: dict[str, object] = {}

    def _fake_query(workspace_file, query, limit=20, node_types=None, config=None, project="", *, enable_vector=None, vector_weight=None):
        observed["workspace"] = workspace_file
        observed["query"] = query
        observed["enable_vector"] = enable_vector
        observed["vector_weight"] = vector_weight
        observed["project"] = project
        return {"query": query, "matches": [], "retrieval_summary": {}}

    monkeypatch.setattr("memory_center.cli.main.memory_query_hybrid", _fake_query)
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["query", "--workspace", workspace, "--text", "ArticleFeignClient", "--vector", "--vector-weight", "0.35"],
    )
    assert result.exit_code == 0
    assert observed["enable_vector"] is True
    assert observed["vector_weight"] == 0.35


def test_cli_query_project_filter(tmp_path: Path):
    import ast
    ws = _cli_project_workspace(tmp_path)
    runner = CliRunner()
    result = runner.invoke(app, ["query", "--workspace", ws, "--text", "ArticleFeignClient", "--project", "task-service", "--limit", "10"])
    assert result.exit_code == 0
    data = ast.literal_eval(result.output)
    assert data["matches"] == []
    assert data["knowledge_state"]["state"] == "NOT_INDEXED"
    assert data["agent_next_steps"]
    assert data["agent_next_steps"][0]["command"]


def test_query_agent_next_steps_consistent_across_core_cli_http(tmp_path: Path):
    import ast
    from http.server import ThreadingHTTPServer

    workspace = _copy_demo_workspace(tmp_path, "query-agent-next-steps-consistency")
    core = memory_query_hybrid(workspace, "ArticleFeignClient", limit=10, project="task-service")

    runner = CliRunner()
    cli_result = runner.invoke(app, ["query", "--workspace", str(workspace), "--text", "ArticleFeignClient", "--project", "task-service", "--limit", "10"])
    assert cli_result.exit_code == 0
    cli = ast.literal_eval(cli_result.output)

    server = ThreadingHTTPServer(("127.0.0.1", _free_port()), create_handler(workspace))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        http = json.loads(urlopen(f"{base}/workspace/query?text=ArticleFeignClient&project=task-service&limit=10").read().decode("utf-8"))
    finally:
        server.shutdown()
        thread.join(timeout=2)

    def first_step(payload: dict[str, object]) -> dict[str, object]:
        steps = payload.get("agent_next_steps", []) if isinstance(payload.get("agent_next_steps", []), list) else []
        assert steps
        first = steps[0]
        assert isinstance(first, dict)
        assert first.get("command")
        assert first.get("priority") in {"high", "medium"}
        assert isinstance(first.get("uses_existing_evidence"), bool)
        assert first.get("action") in {
            "refresh_or_read_live_files",
            "switch_to_walkthrough",
            "validate_semantic_hit",
            "inspect_top_result",
            "refine_query",
        }
        return first

    assert first_step(core)
    assert first_step(cli)
    assert first_step(http)


def test_query_with_session_id_records_agent_guidance_for_cli_and_http(tmp_path: Path):
    import ast
    from http.server import ThreadingHTTPServer

    workspace = _copy_demo_workspace(tmp_path, "query-agent-guidance-session")
    runner = CliRunner()

    cli_session = workspace_start_session(workspace, "CLI query guidance")
    cli_result = runner.invoke(
        app,
        [
            "query",
            "--workspace",
            str(workspace),
            "--text",
            "ArticleFeignClient",
            "--project",
            "task-service",
            "--session-id",
            cli_session["session_id"],
            "--limit",
            "10",
        ],
    )
    assert cli_result.exit_code == 0
    cli = ast.literal_eval(cli_result.output)
    assert cli["agent_next_steps"]
    cli_adoption = memory_eval_agent_guidance_adoption(workspace, session_id=cli_session["session_id"], limit=20)
    assert cli_adoption["summary"]["total_guidance_events"] == 1
    assert cli_adoption["adoption_records"][0]["expected_action"] == cli["agent_next_steps"][0]["action"]

    http_session = workspace_start_session(workspace, "HTTP query guidance")
    server = ThreadingHTTPServer(("127.0.0.1", _free_port()), create_handler(workspace))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        http = json.loads(urlopen(f"{base}/workspace/query?text=ArticleFeignClient&project=task-service&session_id={http_session['session_id']}&limit=10").read().decode("utf-8"))
    finally:
        server.shutdown()
        thread.join(timeout=2)

    assert http["agent_next_steps"]
    http_adoption = memory_eval_agent_guidance_adoption(workspace, session_id=http_session["session_id"], limit=20)
    assert http_adoption["summary"]["total_guidance_events"] == 1
    assert http_adoption["adoption_records"][0]["expected_action"] == http["agent_next_steps"][0]["action"]


def test_eval_agent_guidance_available_from_cli_and_http(tmp_path: Path):
    import ast
    from http.server import ThreadingHTTPServer

    workspace = _copy_demo_workspace(tmp_path, "eval-agent-guidance-entries")
    runner = CliRunner()
    cli_result = runner.invoke(
        app,
        [
            "eval-agent-guidance",
            "--workspace",
            str(workspace),
            "--intent",
            "ArticleFeignClient 调用链",
            "--limit",
            "10",
        ],
    )
    assert cli_result.exit_code == 0
    cli = ast.literal_eval(cli_result.output)
    assert cli["schema"]["name"] == "eval_result"
    assert cli["agent_next_step_count"] >= 1

    server = ThreadingHTTPServer(("127.0.0.1", _free_port()), create_handler(workspace))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        intent = quote("ArticleFeignClient 调用链")
        http = json.loads(urlopen(f"{base}/workspace/eval-agent-guidance?intent={intent}&limit=10").read().decode("utf-8"))
    finally:
        server.shutdown()
        thread.join(timeout=2)

    assert http["schema"]["name"] == "eval_result"
    assert http["agent_next_step_count"] >= 1
    assert http["invalid_search_suggestion_count"] == 0


def test_cli_symbol_project_filter(tmp_path: Path):
    import ast
    ws = _cli_project_workspace(tmp_path)
    runner = CliRunner()
    result = runner.invoke(app, ["symbol", "--workspace", ws, "--name", "ArticleFeignClient", "--project", "task-service", "--limit", "10"])
    assert result.exit_code == 0
    data = ast.literal_eval(result.output)
    assert data["found"] is True
    assert data["best_match"]["type"] == "Class"
    assert data["best_match"]["name"] == "ArticleFeignClient"
    assert data["lookup"]["entrypoints"][0]["role"] == "anchor"
    assert all("task-service" in ((item.get("node") or {}).get("project") or "") for item in data.get("matches", []))


def test_cli_callers_project_filter(tmp_path: Path):
    ws = _cli_project_workspace(tmp_path)
    runner = CliRunner()
    result = runner.invoke(app, ["callers", "--workspace", ws, "--symbol", "ArticleFeignClient", "--project", "task-service", "--depth", "2"])
    assert result.exit_code == 0
    assert "found" in result.output
    assert "True" in result.output
    assert "project_scope" in result.output


def test_cli_callees_project_filter(tmp_path: Path):
    ws = _cli_project_workspace(tmp_path)
    runner = CliRunner()
    result = runner.invoke(app, ["callees", "--workspace", ws, "--symbol", "ArticleFeignClient", "--project", "task-service", "--depth", "2"])
    assert result.exit_code == 0
    assert "found" in result.output
    assert "True" in result.output


def test_cli_context_project_filter(tmp_path: Path):
    ws = _cli_project_workspace(tmp_path)
    runner = CliRunner()
    result = runner.invoke(app, ["context", "--workspace", ws, "--name", "ArticleFeignClient", "--project", "task-service"])
    assert result.exit_code == 0
    assert "project_scope" in result.output


def test_cli_impact_project_filter(tmp_path: Path):
    ws = _cli_project_workspace(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["impact", "--workspace", ws, "--target", "ArticleFeignClient", "--project", "task-service", "--direction", "upstream", "--max-depth", "2", "--view", "compact", "--budget", "small"],
    )
    assert result.exit_code == 0
    assert "project_scope" in result.output
    assert "uses_cross_project_anchor" in result.output
    assert "project_evidence" in result.output
    assert "'role': 'anchor'" in result.output


def test_export_workspace_dashboard_cli(tmp_path: Path):
    source = Path("examples/spring-cloud-demo")
    target = tmp_path / "dashboard-export-demo"
    import shutil
    shutil.copytree(source, target)
    workspace = target / ".memory-center" / "workspace.yaml"
    lines = workspace.read_text(encoding="utf-8").splitlines()
    lines = [f"root: {target.as_posix()}" if line.startswith("root:") else line for line in lines]
    workspace.write_text("\n".join(lines) + "\n", encoding="utf-8")

    runner = CliRunner()
    html_output = tmp_path / "dashboard.html"
    md_output = tmp_path / "dashboard.md"
    html_result = runner.invoke(
        app,
        [
            "export-workspace-dashboard",
            "--workspace",
            str(workspace),
            "--output",
            str(html_output),
            "--format",
            "html",
            "--intent",
            "更新团队规则",
        ],
    )
    md_result = runner.invoke(
        app,
        [
            "export-workspace-dashboard",
            "--workspace",
            str(workspace),
            "--output",
            str(md_output),
            "--format",
            "markdown",
            "--intent",
            "更新团队规则",
        ],
    )
    assert html_result.exit_code == 0
    assert md_result.exit_code == 0
    assert html_output.exists()
    assert md_output.exists()
    assert "Workspace Dashboard" in md_output.read_text(encoding="utf-8")
    assert "<!doctype html>" in html_output.read_text(encoding="utf-8").lower()


def test_cli_version_flag():
    runner = CliRunner()
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "memory-center" in result.stdout
    assert __version__ in result.stdout


def test_write_agent_instructions_includes_sync_workflow(tmp_path: Path):
    workspace_root = tmp_path / "workspace-root"
    workspace_root.mkdir()
    store = WorkspaceStore(tmp_path / ".memory-center" / "workspace.yaml")

    write_agent_instructions(store, workspace_root)

    agents = (workspace_root / "AGENTS.md").read_text(encoding="utf-8")
    claude = (workspace_root / "CLAUDE.md").read_text(encoding="utf-8")

    for content in [agents, claude]:
        assert "<!-- memory-center:start -->" in content
        assert "mc_start" in content
        assert "mc_lookup" in content
        assert "mc_analyze" in content
        assert "mc_sync" in content
        assert "mc_close" in content
        assert "mc_admin" in content
        assert "write_judge" in content
        assert "write_plan" in content
        assert "只允许尾部追加" in content


def test_write_agent_instructions_are_mirrored_to_service_roots(tmp_path: Path):
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    store = WorkspaceStore(workspace)
    workspace_root = workspace.parent.parent

    write_agent_instructions(store, workspace_root)

    service_agents = (workspace_root / "task-service" / "AGENTS.md").read_text(encoding="utf-8")
    cursor_rules = (workspace_root / "task-service" / ".cursor" / "rules" / "memory-center.mdc").read_text(encoding="utf-8")

    assert "当前目录是聚合 workspace 下的子项目" in service_agents
    assert str(workspace.resolve()) in service_agents
    assert "复用上层 workspace" in service_agents
    assert "Current directory is a service root under the aggregate workspace." in service_agents
    assert "mc_start" in service_agents
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
        assert server["command"].endswith("memory-center-mcp")
        assert server["args"] == ["--workspace", str(workspace.resolve())]


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
    assert merged["mcpServers"]["memory-center"]["args"] == ["--workspace", str(workspace.resolve())]


def test_mcp_workspace_context_exposes_startup_diagnostics_for_service_root(tmp_path: Path):
    from memory_center.mcp.runtime import WorkspaceContext
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    service_root = workspace.parent.parent / "task-service"

    ctx = WorkspaceContext(str(service_root))

    assert ctx.workspace_file == str(workspace.resolve())
    assert ctx.startup_diagnostics["workspace_file"] == str(workspace.resolve())
    assert "mcp_bindings" in ctx.startup_diagnostics
    assert ctx.startup_diagnostics["checks"]


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
    html = export_workspace_dashboard_html(workspace, intent="更新团队规则", limit=5)
    assert "Workspace Dashboard" in markdown
    assert "<!doctype html>" in html.lower()


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


def test_agent_guidance_adoption_matches_followup_tools(tmp_path: Path):
    workspace = _copy_demo_workspace(tmp_path, "agent-guidance-adoption")
    from memory_center.core.orchestrator import memory_eval_agent_guidance_adoption

    adopted_session = workspace_start_session(workspace, "按建议追踪 ArticleFeignClient 调用链")
    adopted_id = adopted_session["session_id"]
    workspace_log_session_event(
        workspace,
        adopted_id,
        "agent_guidance",
        {
            "query": "ArticleFeignClient#move",
            "agent_next_steps": [
                {
                    "action": "switch_to_walkthrough",
                    "priority": "high",
                    "command": "mc_lookup(mode=\"walkthrough\")",
                }
            ],
        },
    )
    workspace_log_session_event(
        workspace,
        adopted_id,
        "tool_call",
        {"tool_name": "memory_method_walkthrough_tool", "mode": "walkthrough", "query": "ArticleFeignClient#move"},
    )

    missed_session = workspace_start_session(workspace, "忽略建议重新搜索 ArticleController")
    missed_id = missed_session["session_id"]
    workspace_log_session_event(
        workspace,
        missed_id,
        "agent_guidance",
        {
            "query": "ArticleController",
            "agent_next_steps": [
                {
                    "action": "inspect_top_result",
                    "priority": "medium",
                    "command": "read the top result file",
                }
            ],
        },
    )
    workspace_log_session_event(
        workspace,
        missed_id,
        "tool_call",
        {"tool_name": "rg", "query": "ArticleController class"},
    )

    evaluation = memory_eval_agent_guidance_adoption(workspace, limit=20)
    assert evaluation["schema"]["name"] == "eval_result"
    assert evaluation["summary"]["total_guidance_events"] == 2
    assert evaluation["summary"]["adopted_count"] == 1
    assert evaluation["summary"]["missed_count"] == 1
    assert evaluation["summary"]["adoption_rate"] == 0.5
    assert evaluation["adoption_records"][0]["status"] in {"adopted", "missed"}
    assert any(record["expected_action"] == "switch_to_walkthrough" and record["status"] == "adopted" for record in evaluation["adoption_records"])
    assert any(record["expected_action"] == "inspect_top_result" and record["status"] == "missed" for record in evaluation["adoption_records"])
    assert any(finding["code"] == "agent_guidance_not_adopted" for finding in evaluation["findings"])

    import ast
    runner = CliRunner()
    cli_result = runner.invoke(app, ["eval-agent-guidance-adoption", "--workspace", str(workspace), "--limit", "20"])
    assert cli_result.exit_code == 0
    cli = ast.literal_eval(cli_result.output)
    assert cli["summary"]["total_guidance_events"] == 2

    from http.server import ThreadingHTTPServer
    server = ThreadingHTTPServer(("127.0.0.1", _free_port()), create_handler(workspace))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        http = json.loads(urlopen(f"{base}/workspace/eval-agent-guidance-adoption?limit=20").read().decode("utf-8"))
    finally:
        server.shutdown()
        thread.join(timeout=2)
    assert http["summary"]["adopted_count"] == 1


def test_agent_guidance_replay_classifies_missed_bypassed_and_unobservable(tmp_path: Path):
    workspace = _copy_demo_workspace(tmp_path, "agent-guidance-replay")

    adopted = workspace_start_session(workspace, "按建议执行 walkthrough")
    adopted_id = adopted["session_id"]
    workspace_log_session_event(
        workspace,
        adopted_id,
        "agent_guidance",
        {
            "query": "ArticleFeignClient#move",
            "agent_next_steps": [
                {
                    "action": "switch_to_walkthrough",
                    "priority": "high",
                    "command": "mc_lookup(mode=\"walkthrough\")",
                }
            ],
        },
    )
    workspace_log_session_event(
        workspace,
        adopted_id,
        "tool_call",
        {"tool_name": "memory_method_walkthrough_tool", "mode": "walkthrough", "query": "ArticleFeignClient#move"},
    )

    bypassed = workspace_start_session(workspace, "绕过建议直接 rg")
    bypassed_id = bypassed["session_id"]
    workspace_log_session_event(
        workspace,
        bypassed_id,
        "agent_guidance",
        {
            "query": "ArticleController",
            "agent_next_steps": [
                {"action": "inspect_top_result", "command": "read the top result file", "read_targets": ["src/ArticleController.java"]}
            ],
        },
    )
    workspace_log_session_event(workspace, bypassed_id, "tool_call", {"tool_name": "rg", "query": "ArticleController class"})

    missed = workspace_start_session(workspace, "用了 Memory Center 但没按建议动作")
    missed_id = missed["session_id"]
    workspace_log_session_event(
        workspace,
        missed_id,
        "agent_guidance",
        {
            "query": "ArticleService",
            "agent_next_steps": [
                {"action": "use_read_targets", "command": "open referenced read target"}
            ],
        },
    )
    workspace_log_session_event(workspace, missed_id, "tool_call", {"tool_name": "memory_query_tool", "query": "ArticleService"})

    unobservable = workspace_start_session(workspace, "没有后续工具事件")
    unobservable_id = unobservable["session_id"]
    workspace_log_session_event(
        workspace,
        unobservable_id,
        "agent_guidance",
        {
            "query": "ArticleMapper",
            "agent_next_steps": [
                {"action": "refine_query", "command": "mc_lookup(mode=\"query\")"}
            ],
        },
    )

    evaluation = memory_eval_agent_guidance_replay(workspace, limit=50)
    assert evaluation["schema"]["name"] == "eval_result"
    assert evaluation["summary"]["total_guidance_events"] == 4
    assert evaluation["summary"]["adopted_count"] == 1
    assert evaluation["summary"]["bypassed_count"] == 1
    assert evaluation["summary"]["missed_count"] == 1
    assert evaluation["summary"]["unobservable_count"] == 1
    assert evaluation["summary"]["reason_counts"]["matched_expected_tool"] == 1
    assert evaluation["summary"]["reason_counts"]["local_search_or_non_memory_tool_used"] == 1
    assert evaluation["summary"]["reason_counts"]["guidance_missing_target_hint"] == 1
    assert evaluation["summary"]["reason_counts"]["no_followup_tool_call"] == 1
    assert any(record["status"] == "bypassed" and record["matched_tool"] == "rg" for record in evaluation["replay_records"])
    assert any(finding["code"] == "agent_guidance_bypassed" for finding in evaluation["findings"])

    import ast
    runner = CliRunner()
    cli_result = runner.invoke(app, ["eval-agent-guidance-replay", "--workspace", str(workspace), "--limit", "50"])
    assert cli_result.exit_code == 0
    cli = ast.literal_eval(cli_result.output)
    assert cli["summary"]["bypassed_count"] == 1

    from http.server import ThreadingHTTPServer
    server = ThreadingHTTPServer(("127.0.0.1", _free_port()), create_handler(workspace))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        http = json.loads(urlopen(f"{base}/workspace/eval-agent-guidance-replay?limit=50").read().decode("utf-8"))
    finally:
        server.shutdown()
        thread.join(timeout=2)
    assert http["summary"]["unobservable_count"] == 1


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
    workspace_log_session_event(workspace, sid, "tool_call", {"tool_name": "memory_query_tool", "query": "ArticleFeignClient"})
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

    stats = store.memory_backend_stats()
    status = workspace_status(workspace, view="full")
    query = memory_backend_query(workspace, collection="session-events.jsonl", limit=5)
    assert stats["collections"]["session-events.jsonl"] >= 1
    assert stats["collections"]["cross-service-task-memory.jsonl"] >= 1
    assert stats["ref_count"] >= 1
    assert ref
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
    workspace_log_session_event(workspace, session_id, "tool_call", {"tool_name": "memory_query_tool", "query": "ArticleFeignClient", "project": "task-service"})
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
    workspace_log_session_event(workspace, session_id, "tool_call", {"tool_name": "memory_query_tool", "query": "ArticleFeignClient"})
    workspace_log_session_event(workspace, session_id, "tool_result", {"project": "task-service", "file_path": "task-service/src/main/java/com/example/task/ArticleMoveService.java"})
    large_payload = {"tool_name": "memory_context_tool", "query": "ArticleFeignClient", "project": "task-service", "blob": "X" * 6000}
    offloaded = workspace_log_session_event(workspace, session_id, "tool_result", large_payload)
    ended = workspace_end_session(workspace, session_id, outcome="完成 Feign 调用链定位", verified_by=["manual-check"])

    assert ended["ended"] is True
    assert ended["summary"]["tool_calls"] == ["memory_query_tool"]
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
    assert impact["lookup"]["retrieval_summary"]["semantic_matches"] >= 1
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
    from memory_center.core.storage.graph import GraphStore
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
    assert consumer["metadata"].get("package") == "com.example.task"
    assert consumer["line"] > 0

    mq_index = store.read_json("mq-index.json", [])
    assert any(item["class_name"] == "ArticleMoveConsumer" and item["method_name"] == "consume" for item in mq_index)

    move_service = graph.find_nodes("ArticleMoveService", types=["Class"], limit=5)[0]
    service_outgoing = graph.neighbors(move_service["id"], direction="downstream", max_depth=1, limit=50)
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


def test_http_bridge_routes(tmp_path: Path):
    from http.server import ThreadingHTTPServer

    from memory_center.core.orchestrator import (
        workspace_end_session,
        workspace_log_session_event,
        workspace_start_session,
    )

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

        workspace_status_payload = json.loads(urlopen(f"{base}/workspace/status").read().decode("utf-8"))
        assert workspace_status_payload["reindex"]["status"] == "succeeded"
        assert workspace_status_payload["reindex"]["lock_held"] is False

        artifacts = json.loads(urlopen(f"{base}/workspace/artifacts").read().decode("utf-8"))
        assert artifacts["artifacts"]
        assert artifacts["core_memory_blocks"]
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
        sniff_sync = json.loads(
            urlopen(
                f"{base}/workspace/artifacts/sync-sniff?intent=HTTP%20Feign%20task&limit=5&task_id={task_id}&auto_sync_mode=aggressive"
            )
            .read()
            .decode("utf-8")
        )
        assert sniff_sync["synced"] is True
        assert sniff_sync["auto_sync_mode"] == "aggressive"

        query = json.loads(urlopen(f"{base}/workspace/query?text=ArticleFeignClient&project=task-service&enable_vector=true&vector_weight=0.25").read().decode("utf-8"))
        assert query["matches"]
        assert query["retrieval_summary"]["exact_matches"] >= 1
        assert query["retrieval_summary"]["semantic_matches"] >= 1
        assert query["retrieval_diagnostics"]["policy"]["enable_vector"] is True
        assert query["agent_next_steps"]
        assert query["agent_next_steps"][0]["action"]
        assert all("task-service" in (item.get("node", {}).get("project") or "") for item in query["matches"])
        walkthrough_symbol = quote("com.example.task.ArticleMoveService#move")
        walkthrough = json.loads(urlopen(f"{base}/workspace/method-walkthrough?symbol={walkthrough_symbol}&report_level=summary").read().decode("utf-8"))
        assert walkthrough["found"] is True
        assert walkthrough["summary_lines"]
        assert walkthrough["read_targets"]
        walkthrough_eval = json.loads(urlopen(f"{base}/workspace/walkthrough-eval?symbol={walkthrough_symbol}&report_level=standard").read().decode("utf-8"))
        assert walkthrough_eval["grade"] in {"pass", "warn", "fail"}
        walkthrough_export = json.loads(urlopen(f"{base}/workspace/walkthrough-export?symbol={walkthrough_symbol}&report_level=deep").read().decode("utf-8"))
        assert walkthrough_export["exported"] is True
        assert walkthrough_export["artifact"].startswith("walkthroughs/")
        search = json.loads(urlopen(f"{base}/workspace/search-code?text=ArticleFeignClient&scope=task-service&project=task-service").read().decode("utf-8"))
        assert search["hits"]
        assert all("task-service" in (item.get("project") or "") for item in search["hits"])
        symbol = json.loads(urlopen(f"{base}/workspace/symbol?name=ArticleFeignClient&project=task-service").read().decode("utf-8"))
        assert symbol["found"] is True
        assert symbol["summary_lines"]
        assert symbol["summary_lines"][0].startswith("Best Class ArticleFeignClient")
        assert all("task-service" in (item.get("project") or "") for item in symbol.get("matches", []))
        callers = json.loads(urlopen(f"{base}/workspace/callers?symbol=ArticleFeignClient&depth=2&project=task-service").read().decode("utf-8"))
        assert callers["found"] is True
        assert callers["summary_lines"]
        callees = json.loads(urlopen(f"{base}/workspace/callees?symbol=ArticleFeignClient&depth=2&project=task-service").read().decode("utf-8"))
        assert callees["found"] is True
        assert callees["summary_lines"]
        plan = json.loads(urlopen(f"{base}/workspace/plan-change?target=MoveArticleRequest").read().decode("utf-8"))
        assert plan["found"] is True
        checklist = json.loads(urlopen(f"{base}/workspace/verify-checklist?target=MoveArticleRequest").read().decode("utf-8"))
        assert checklist["checklist"]
        judge = json.loads(urlopen(f"{base}/workspace/memory-write-judge?text={quote('团队规范：DTO变更需向后兼容')}&source=note&intent={quote('更新团队规则')}").read().decode("utf-8"))
        assert judge["decision"]["selected_layer"] == "L3_workspace_profile"
        plan_write = json.loads(urlopen(f"{base}/workspace/memory-plan-write?text=HTTP%20task%20context&source=note&intent=HTTP%20task").read().decode("utf-8"))
        assert plan_write["memory_layer"] == "L2_task_spaces"
        execute_write = json.loads(urlopen(f"{base}/workspace/memory-execute-write?text=HTTP%20team%20rule&source=note&intent=update%20rule").read().decode("utf-8"))
        assert execute_write["executed"]
        assert execute_write["write_receipts"]
        write_receipts = json.loads(urlopen(f"{base}/workspace/write-receipts?limit=10").read().decode("utf-8"))
        assert write_receipts["receipts"]
        replay_chain = json.loads(urlopen(f"{base}/workspace/replay-write-chain?limit=10").read().decode("utf-8"))
        assert "timeline" in replay_chain
        eval_quality = json.loads(urlopen(f"{base}/workspace/eval-write-quality?intent=update%20rule&limit=10").read().decode("utf-8"))
        assert "quality" in eval_quality
        eval_resume = json.loads(urlopen(f"{base}/workspace/eval-resume?intent=update%20rule&limit=10").read().decode("utf-8"))
        assert "quality" in eval_resume
        eval_handoff = json.loads(urlopen(f"{base}/workspace/eval-handoff?target_model=glm-4&intent=update%20rule&limit=10").read().decode("utf-8"))
        assert "quality" in eval_handoff
        recent_evidence = json.loads(urlopen(f"{base}/workspace/recent-evidence?limit=10").read().decode("utf-8"))
        assert "evidence" in recent_evidence
        unresolved_items = json.loads(urlopen(f"{base}/workspace/unresolved-items?intent=update%20rule&limit=10").read().decode("utf-8"))
        assert "items" in unresolved_items
        next_actions = json.loads(urlopen(f"{base}/workspace/next-actions?intent=update%20rule&limit=10").read().decode("utf-8"))
        assert "actions" in next_actions
        resume_packet = json.loads(urlopen(f"{base}/workspace/resume-packet?intent=update%20rule&limit=10").read().decode("utf-8"))
        assert "next_recommended_actions" in resume_packet
        assert "resume_rule_profile" in resume_packet
        resume_check = json.loads(urlopen(f"{base}/workspace/work-resume-check?task_id={quote(task_id)}&limit=5").read().decode("utf-8"))
        assert resume_check["workflow"] == "task-resume-check"
        assert "recommended_next_step" in resume_check
        model_profile = json.loads(urlopen(f"{base}/workspace/model-profile?model_name=deepseek-r1").read().decode("utf-8"))
        assert model_profile["normalized_model"] == "deepseek"
        handoff_packet = json.loads(urlopen(f"{base}/workspace/handoff-packet?target_model=glm-4&intent=update%20rule&limit=10").read().decode("utf-8"))
        assert "handoff_packet" in handoff_packet
        handoff_history = json.loads(urlopen(f"{base}/workspace/handoff-history?target_model=glm-4&limit=10").read().decode("utf-8"))
        assert handoff_history["handoffs"]
        continuity_dashboard = json.loads(urlopen(f"{base}/workspace/continuity-dashboard?intent=update%20rule&limit=10").read().decode("utf-8"))
        assert "resume_packet" in continuity_dashboard
        workspace_dashboard_payload = json.loads(urlopen(f"{base}/workspace/dashboard?intent=update%20rule&limit=10").read().decode("utf-8"))
        assert "active_tasks" in workspace_dashboard_payload
        assert "focus_resume_eval" in workspace_dashboard_payload
        quality_gates = json.loads(urlopen(f"{base}/workspace/quality-gates-summary").read().decode("utf-8"))
        assert quality_gates["schema_version"] == 1
        assert quality_gates["health"] in {"healthy", "warning", "critical", "unknown"}
        assert set(quality_gates["benchmark"]) == {"score", "quality", "recommendations"}
        assert set(quality_gates["regression_alerts"]) == {"total", "critical", "warning", "items"}
        assert set(quality_gates["replay_campaign"]) == {"passed", "total_guidance_events", "missing_intents"}
        assert set(quality_gates["java_call_resolution"]) == {
            "call_edge_count", "unresolved_call_edge_count", "unresolved_rate", "top_categories",
        }
        assert "task-service" not in json.dumps(quality_gates)
        ui_index = urlopen(f"{base}/ui?workspace={workspace}").read().decode("utf-8")
        assert "Memory Center Workbench" in ui_index
        ui_dashboard = urlopen(f"{base}/ui/dashboard?workspace={workspace}&intent=update%20rule").read().decode("utf-8")
        assert "Workspace Dashboard" in ui_dashboard
        ui_task = urlopen(f"{base}/ui/task?workspace={workspace}").read().decode("utf-8")
        assert "Next Actions" in ui_task
        ui_task_specific = urlopen(f"{base}/ui/task?workspace={workspace}&task_id={task_id}").read().decode("utf-8")
        assert task_id in ui_task_specific or "Current Summary" in ui_task_specific
        ui_timeline = urlopen(f"{base}/ui/timeline?workspace={workspace}").read().decode("utf-8")
        assert "Timeline" in ui_timeline
        ui_receipts = urlopen(f"{base}/ui/receipts?workspace={workspace}").read().decode("utf-8")
        assert "Receipts" in ui_receipts
        ui_usage = urlopen(f"{base}/ui/usage?workspace={workspace}").read().decode("utf-8")
        assert "Usage Report" in ui_usage
        ui_backend = urlopen(f"{base}/ui/backend?workspace={workspace}").read().decode("utf-8")
        assert "Memory Backend" in ui_backend
        ui_index_freshness = urlopen(f"{base}/ui/index-freshness?workspace={workspace}").read().decode("utf-8")
        assert "Index Freshness" in ui_index_freshness
        first_ref_id = recent_evidence["evidence"][0]["ref_id"]
        ui_ref = urlopen(f"{base}/ui/ref?workspace={workspace}&ref_id={first_ref_id}").read().decode("utf-8")
        assert first_ref_id in ui_ref
        eval_resume = json.loads(urlopen(f"{base}/workspace/eval-resume?intent=update%20rule&limit=10").read().decode("utf-8"))
        assert "quality" in eval_resume
        eval_handoff = json.loads(urlopen(f"{base}/workspace/eval-handoff?target_model=glm-4&intent=update%20rule&limit=10").read().decode("utf-8"))
        assert "quality" in eval_handoff

        session_recent = json.loads(urlopen(f"{base}/workspace/sessions/recent?limit=5").read().decode("utf-8"))
        assert "recent_sessions" in session_recent
        assert session_recent["recent_sessions"]
        suggested_case = json.loads(urlopen(f"{base}/workspace/suggest-case?session_id={session_id}").read().decode("utf-8"))
        assert suggested_case["found"] is True
        assert suggested_case["draft_case"]["task"]
        case_sync = json.loads(
            urlopen(
                f"{base}/workspace/artifacts/sync-case?session_id={session_id}&task_id={task_id}&auto_sync_mode=strict"
            )
            .read()
            .decode("utf-8")
        )
        assert case_sync["synced"] is True
        assert case_sync["auto_sync_mode"] == "strict"
        task_context = json.loads(urlopen(f"{base}/workspace/task-artifact?task_id={task_id}&name=context").read().decode("utf-8"))
        assert task_context["task_id"] == task_id

        group_query_payload = json.loads(urlopen(f"{base}/group/query?group=http-group&text=article-pubtime-change").read().decode("utf-8"))
        assert group_query_payload["related_bridges"]
        assert group_query_payload["retrieval_summary"]["returned_matches"] >= 1
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


def test_resolve_task_score_threshold(tmp_path: Path):
    """Resolve respects score_threshold: below threshold does not auto-match, above does."""
    workspace = _copy_demo_workspace(tmp_path, "resolve-threshold")

    created = create_task_space(workspace, title="站点连通性告警治理")
    task_id = created["task_id"]
    update_task_artifact(workspace, task_id, "plan", "# Plan\n\n处理站点连通性告警")

    # Threshold above actual score (score=2 from status=active) — should NOT match
    resolved_high = resolve_task_space(workspace, intent="继续处理站点告警连通性问题", create_if_missing=False, score_threshold=3)
    assert resolved_high["resolved"] is False
    assert resolved_high["task_id"] == ""
    assert resolved_high["score_threshold"] == 3

    # Threshold at or below actual score — SHOULD match
    resolved_low = resolve_task_space(workspace, intent="继续处理站点告警连通性问题", create_if_missing=False, score_threshold=1)
    assert resolved_low["resolved"] is True
    assert resolved_low["task_id"] == task_id
    assert resolved_low["score_threshold"] == 1


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


def test_work_resume_check_cli(tmp_path: Path):
    workspace = _copy_demo_workspace(tmp_path, "task-resume-check-cli")
    task = create_task_space(workspace, title="CLI 接手检查任务")

    runner = CliRunner()
    result = runner.invoke(app, ["work-resume-check", "--workspace", str(workspace), "--task-id", task["task_id"], "--limit", "5"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["workflow"] == "task-resume-check"
    assert payload["task_id"] == task["task_id"]
    assert "recommended_next_step" in payload


def test_work_resume_check_cli_mcp_http_core_contract_consistency(tmp_path: Path):
    from http.server import ThreadingHTTPServer

    from memory_center.application.admin import build_admin_registry

    workspace = _copy_demo_workspace(tmp_path, "task-resume-check-consistency")
    task = create_task_space(workspace, title="三入口接手检查任务")
    task_id = task["task_id"]

    core = workspace_task_resume_check(workspace, task_id=task_id, limit=5)

    runner = CliRunner()
    cli_result = runner.invoke(app, ["work-resume-check", "--workspace", str(workspace), "--task-id", task_id, "--limit", "5"])
    assert cli_result.exit_code == 0
    cli = json.loads(cli_result.output)

    mcp = build_admin_registry(workspace_file=str(workspace), task_id=task_id, limit=5).dispatch("task_resume_check")

    server = ThreadingHTTPServer(("127.0.0.1", _free_port()), create_handler(workspace))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        http_payload = json.loads(urlopen(f"{base}/workspace/work-resume-check?task_id={quote(task_id)}&limit=5").read().decode("utf-8"))
    finally:
        server.shutdown()
        thread.join(timeout=2)

    def comparable(payload: dict[str, object]) -> dict[str, object]:
        health = payload.get("health", {}) if isinstance(payload.get("health", {}), dict) else {}
        repair_summary = payload.get("repair_plan_summary", {}) if isinstance(payload.get("repair_plan_summary", {}), dict) else {}
        next_step = payload.get("recommended_next_step", {}) if isinstance(payload.get("recommended_next_step", {}), dict) else {}
        return {
            "workflow": payload.get("workflow"),
            "task_id": payload.get("task_id"),
            "status": payload.get("status"),
            "can_resume": payload.get("can_resume"),
            "health": health.get("health"),
            "health_issue_count": health.get("issue_count"),
            "repair_issue_count": repair_summary.get("issue_count"),
            "next_action": next_step.get("action"),
        }

    expected = comparable(core)
    assert comparable(cli) == expected
    assert comparable(mcp) == expected
    assert comparable(http_payload) == expected


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


def test_task_spaces_health_and_cli(tmp_path: Path):
    workspace = _copy_demo_workspace(tmp_path, "task-health-cli")
    task = create_task_space(workspace, title="CLI 健康检查任务")
    workspace_sync_sniff_to_artifacts(workspace, "ArticleFeignClient CLI 健康检查", task_id=task["task_id"], limit=5)

    overview = task_spaces_health(workspace)
    assert overview["checked"] >= 1
    assert overview["tasks"]
    assert "health_counts" in overview
    assert "top_issues" in overview

    runner = CliRunner()
    single = runner.invoke(app, ["artifact", "health-task", "--workspace", str(workspace), "--task-id", task["task_id"]])
    assert single.exit_code == 0
    assert "health" in single.output
    assert "repair_suggestions" in single.output

    all_tasks = runner.invoke(app, ["artifact", "health-tasks", "--workspace", str(workspace), "--limit", "5"])
    assert all_tasks.exit_code == 0
    assert "health_counts" in all_tasks.output


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


def test_task_space_repair_plan_cli_for_synced_task(tmp_path: Path):
    workspace = _copy_demo_workspace(tmp_path, "task-repair-plan-cli")
    task = create_task_space(workspace, title="CLI 修复计划任务")
    workspace_sync_sniff_to_artifacts(workspace, "ArticleFeignClient CLI 修复计划", task_id=task["task_id"], limit=5)

    plan = task_space_repair_plan(workspace, task["task_id"])
    assert plan["repair_plan"] == []
    assert plan["issue_count"] == 0

    runner = CliRunner()
    result = runner.invoke(app, ["artifact", "repair-plan-task", "--workspace", str(workspace), "--task-id", task["task_id"]])
    assert result.exit_code == 0
    assert "repair_plan" in result.output
    assert "apply_supported" in result.output


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


def test_task_space_repair_execute_cli(tmp_path: Path):
    workspace = _copy_demo_workspace(tmp_path, "task-repair-execute-cli")
    task = create_task_space(workspace, title="CLI 执行修复任务")

    runner = CliRunner()
    dry_run = runner.invoke(app, ["artifact", "repair-task", "--workspace", str(workspace), "--task-id", task["task_id"]])
    assert dry_run.exit_code == 0
    assert "execution_plan" in dry_run.output
    assert "dry_run" in dry_run.output

    applied = runner.invoke(
        app,
        [
            "artifact",
            "repair-task",
            "--workspace",
            str(workspace),
            "--task-id",
            task["task_id"],
            "--apply",
            "--intent",
            "ArticleFeignClient CLI 执行修复任务",
        ],
    )
    assert applied.exit_code == 0
    assert "remaining_health" in applied.output


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
            {"event_type": "tool_call", "tool_name": "memory_query_tool", "query": "article-pubtime-change topic kafka"},
        ],
    }

    assert _case_risk_level(low_case) == "low"
    assert _case_risk_level(medium_case) in {"medium", "high"}
    assert _case_risk_level(high_case) == "high"


def test_partial_reindex_only_touches_changed_project(tmp_path: Path):
    """Partial reindex with --project only rebuilds graph nodes for that project."""
    from memory_center.core.storage.graph import GraphStore
    from memory_center.core.workspace.config import load_workspace_config

    workspace = _copy_demo_workspace(tmp_path, "partial-reindex")
    config = load_workspace_config(workspace)
    store = WorkspaceStore(workspace)
    ensure_default_rules(store)

    full_counts = reindex_workspace(config, store)
    assert full_counts["mode"] == "full"
    assert full_counts["graph_nodes"] > 0

    graph = GraphStore(store.graph_db_path)
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
    workspace_log_session_event(workspace, session["session_id"], "tool_call", {"tool_name": "memory_query_tool", "project": "task-service", "query": "ArticleFeignClient"})
    workspace_log_session_event(workspace, session["session_id"], "tool_call", {"tool_name": "memory_symbol_tool", "project": "article-service", "query": "ArticleService"})

    result_all = memory_backend_query(workspace, collection="session-events.jsonl", limit=50)
    assert result_all["records"]["count"] >= 2

    result_by_project = memory_backend_query(workspace, collection="session-events.jsonl", project="task-service", limit=50)
    assert result_by_project["records"]["count"] >= 1


def test_export_html_contains_sidebar(tmp_path: Path):
    """UI pages contain navigation sidebar with links to all pages."""
    workspace = _copy_demo_workspace(tmp_path, "ui-sidebar")
    config = load_workspace_config(workspace)
    store = WorkspaceStore(workspace)
    ensure_default_rules(store)
    reindex_workspace(config, store)

    html_output = export_workspace_dashboard_html(workspace, intent="sidebar test", limit=5)
    assert "<nav" in html_output
    assert "/ui/dashboard" in html_output
    assert "/ui/timeline" in html_output
    assert "/ui/backend" in html_output
    assert "工作台" in html_output


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
    workspace_log_session_event(workspace, sid, "tool_call", {"tool_name": "memory_query_tool", "query": "ArticleFeignClient"})
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
    workspace_log_session_event(workspace, sid, "tool_call", {"tool_name": "memory_query_tool", "query": "ArticleFeignClient"})
    sampled = memory_eval_agent_guidance_replay_trend(workspace, session_id=sid, limit=20)
    assert sampled["recorded"] is True
    assert sampled["trend_point"]["adoption_rate"] == 1.0
    assert sampled["trend_point"]["reason_counts"] == {"matched_expected_tool": 1}


def test_eval_agent_guidance_trend_available_from_cli_and_http(tmp_path: Path):
    import ast
    from http.server import ThreadingHTTPServer

    workspace = _copy_demo_workspace(tmp_path, "agent-guidance-trend-entrypoints")
    runner = CliRunner()
    cli_result = runner.invoke(
        app,
        [
            "eval-agent-guidance-trend",
            "--workspace",
            str(workspace),
            "--intent",
            "ArticleFeignClient 调用链",
            "--limit",
            "5",
        ],
    )
    assert cli_result.exit_code == 0
    cli = ast.literal_eval(cli_result.output)
    assert cli["recorded"] is True
    assert cli["trend_point"]["agent_next_step_count"] >= 1

    server = ThreadingHTTPServer(("127.0.0.1", _free_port()), create_handler(workspace))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        intent = quote("ArticleFeignClient 调用链")
        http = json.loads(urlopen(f"{base}/workspace/eval-agent-guidance-trend?intent={intent}&limit=5").read().decode("utf-8"))
    finally:
        server.shutdown()
        thread.join(timeout=2)

    assert http["recorded"] is True
    assert http["trend_point"]["agent_next_step_count"] >= 1


def test_eval_agent_guidance_adoption_trend_available_from_cli_and_http(tmp_path: Path):
    import ast
    from http.server import ThreadingHTTPServer

    workspace = _copy_demo_workspace(tmp_path, "agent-guidance-adoption-trend-entrypoints")
    session = workspace_start_session(workspace, "adoption trend entrypoint")
    sid = session["session_id"]
    workspace_log_session_event(
        workspace,
        sid,
        "agent_guidance",
        {"agent_next_steps": [{"action": "refine_query", "command": "mc_lookup(mode=query)"}]},
    )
    workspace_log_session_event(workspace, sid, "tool_call", {"tool_name": "memory_query_tool", "query": "ArticleFeignClient"})

    runner = CliRunner()
    cli_result = runner.invoke(
        app,
        [
            "eval-agent-guidance-adoption-trend",
            "--workspace",
            str(workspace),
            "--session-id",
            sid,
            "--limit",
            "20",
        ],
    )
    assert cli_result.exit_code == 0
    cli = ast.literal_eval(cli_result.output)
    assert cli["recorded"] is True
    assert cli["trend_point"]["adoption_rate"] == 1.0

    server = ThreadingHTTPServer(("127.0.0.1", _free_port()), create_handler(workspace))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        http = json.loads(urlopen(f"{base}/workspace/eval-agent-guidance-adoption-trend?session_id={sid}&limit=20").read().decode("utf-8"))
    finally:
        server.shutdown()
        thread.join(timeout=2)

    assert http["recorded"] is True
    assert http["trend_point"]["adoption_rate"] == 1.0


def test_eval_agent_guidance_replay_trend_available_from_cli_and_http(tmp_path: Path):
    import ast
    from http.server import ThreadingHTTPServer

    workspace = _copy_demo_workspace(tmp_path, "agent-guidance-replay-trend-entrypoints")
    session = workspace_start_session(workspace, "replay trend entrypoint")
    sid = session["session_id"]
    workspace_log_session_event(
        workspace,
        sid,
        "agent_guidance",
        {"agent_next_steps": [{"action": "refine_query", "command": "mc_lookup(mode=query)"}]},
    )
    workspace_log_session_event(workspace, sid, "tool_call", {"tool_name": "memory_query_tool", "query": "ArticleFeignClient"})

    runner = CliRunner()
    cli_result = runner.invoke(
        app,
        [
            "eval-agent-guidance-replay-trend",
            "--workspace",
            str(workspace),
            "--session-id",
            sid,
            "--limit",
            "20",
        ],
    )
    assert cli_result.exit_code == 0
    cli = ast.literal_eval(cli_result.output)
    assert cli["recorded"] is True
    assert cli["trend_point"]["adoption_rate"] == 1.0

    server = ThreadingHTTPServer(("127.0.0.1", _free_port()), create_handler(workspace))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        http = json.loads(urlopen(f"{base}/workspace/eval-agent-guidance-replay-trend?session_id={sid}&limit=20").read().decode("utf-8"))
    finally:
        server.shutdown()
        thread.join(timeout=2)

    assert http["recorded"] is True
    assert http["trend_point"]["adoption_rate"] == 1.0


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


def test_export_dashboard_contains_filters(tmp_path: Path):
    """Dashboard HTML contains interactive filter form."""
    workspace = _copy_demo_workspace(tmp_path, "ui-filter")
    config = load_workspace_config(workspace)
    store = WorkspaceStore(workspace)
    ensure_default_rules(store)
    reindex_workspace(config, store)

    html_output = export_workspace_dashboard_html(workspace, intent="filter test", limit=5, view="compact", budget="medium")
    assert "<form" in html_output
    assert "intent" in html_output
    assert "limit" in html_output
    assert "view" in html_output
    assert "budget" in html_output


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
