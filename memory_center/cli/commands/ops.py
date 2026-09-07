"""Ops 命令族:按业务域从 cli/main.py 拆出的命令组(ADR-0002)。"""
from __future__ import annotations

# Typer evaluates command annotations at runtime in Python 3.9 environments.
# ruff: noqa: UP006,UP035,UP045
import json
from typing import List, Optional

import typer
from rich import print

from memory_center.application.external_capabilities import audit_external_capabilities, snapshot_external_capabilities
from memory_center.application.performance import record_workspace_performance_snapshot
from memory_center.application.runtime_governance import workspace_runtime_governance
from memory_center.core.retrieval.planner import (
    scoped_refresh_performance_status,
    workspace_performance_snapshot_status,
)
from memory_center.core.workspace.jobs import workspace_job_status
from memory_center.core.knowledge.candidates import wiki_knowledge_candidates
from memory_center.core.knowledge.wiki_bridge import (
    attach_knowledge_link_to_task,
    list_knowledge_links,
    mark_knowledge_link_status,
    sync_personal_wiki_assets,
)
from memory_center.core.knowledge.wiki_drift import knowledge_link_drift, knowledge_link_metrics
from memory_center.core.knowledge.wiki_promotion import confirm_wiki_promotion, wiki_promotion_preview
from memory_center.http.route_dispatch import audit_http_route_contract
from memory_center.http.server import serve_http, validate_http_binding


def register_ops_commands(app: typer.Typer) -> None:
    @app.command("wiki-promotion-preview")
    def wiki_promotion_preview_cmd(
        workspace: str = typer.Option(...), session_id: str = typer.Option(...), wiki_root: str = typer.Option(...),
    ):
        """Preview a DSH delivery-summary promotion; does not write Personal Wiki."""
        typer.echo(json.dumps(wiki_promotion_preview(workspace, session_id, wiki_root=wiki_root), ensure_ascii=False))

    @app.command("wiki-promotion-confirm")
    def wiki_promotion_confirm_cmd(
        workspace: str = typer.Option(...), session_id: str = typer.Option(...), wiki_root: str = typer.Option(...), owner: str = typer.Option(...),
        binding_mode: str = typer.Option("", help="Session binding mode; shadow_only forbids task-scoped KnowledgeLinks."),
    ):
        """Explicitly promote one previewed DSH delivery summary into Personal Wiki."""
        typer.echo(json.dumps(confirm_wiki_promotion(workspace, session_id, wiki_root=wiki_root, owner=owner, binding_mode=binding_mode), ensure_ascii=False))

    @app.command("knowledge-links")
    def knowledge_links_cmd(
        workspace: str = typer.Option(..., help="Path to .memory-center/workspace.yaml"),
        task_id: str = typer.Option("", help="Filter by bound task id."),
        scope: str = typer.Option("", help="Filter by scope tag."),
        status: str = typer.Option("", help="Filter by link_status: active|stale|revoked."),
        limit: int = typer.Option(50, min=1, max=500, help="Maximum links to return."),
    ):
        """List KnowledgeLinks (kind=wiki reverse links); read-only."""
        typer.echo(json.dumps(list_knowledge_links(workspace, task_id=task_id, scope=scope, status=status, limit=limit), ensure_ascii=False))

    @app.command("knowledge-candidates")
    def knowledge_candidates_cmd(
        workspace: str = typer.Option(..., help="Path to .memory-center/workspace.yaml"),
        task: str = typer.Option(..., help="Anchored task description; empty anchors are rejected."),
        wiki_root: str = typer.Option(..., help="Personal Assistant Wiki root directory."),
        scope: str = typer.Option("", help="Bounded scope label forwarded to the Wiki bridge."),
        task_id: str = typer.Option("", help="Optional confirmed task id recorded on exposure events."),
        limit: int = typer.Option(3, min=1, max=3, help="Hard contract cap is 3 candidates."),
        min_score: float = typer.Option(0.0, help="Minimum Wiki relevance score; lower scores are excluded."),
    ):
        """Anchored Wiki candidates (bounded read path); fails closed to empty."""
        typer.echo(json.dumps(wiki_knowledge_candidates(workspace, task=task, wiki_root=wiki_root, scope=scope, task_id=task_id, limit=limit, min_score=min_score), ensure_ascii=False))

    @app.command("knowledge-link-attach")
    def knowledge_link_attach_cmd(
        workspace: str = typer.Option(..., help="Path to .memory-center/workspace.yaml"),
        knowledge_id: str = typer.Option(..., help="KnowledgeLink knowledge_id."),
        task_id: str = typer.Option(..., help="Explicitly chosen task id."),
        evidence_refs: List[str] = typer.Option(..., help="Evidence references; repeat the option."),
        actor: str = typer.Option(..., help="Operator recorded on the manual attachment event."),
        reason: str = typer.Option("", help="Optional note kept on the event payload."),
    ):
        """Manually attach a KnowledgeLink to an explicitly chosen task."""
        typer.echo(json.dumps(attach_knowledge_link_to_task(workspace, knowledge_id, task_id=task_id, evidence_refs=list(evidence_refs), actor=actor, reason=reason), ensure_ascii=False))

    @app.command("knowledge-link-mark")
    def knowledge_link_mark_cmd(
        workspace: str = typer.Option(..., help="Path to .memory-center/workspace.yaml"),
        knowledge_id: str = typer.Option(..., help="KnowledgeLink knowledge_id."),
        status: str = typer.Option(..., help="Target link_status: active|stale|revoked."),
        reason: str = typer.Option(..., help="Human-readable transition reason kept in status history."),
        actor: str = typer.Option(..., help="Operator recorded on the transition."),
    ):
        """Explicitly transition link_status; the only producer of revoked."""
        typer.echo(json.dumps(mark_knowledge_link_status(workspace, knowledge_id, status=status, reason=reason, actor=actor), ensure_ascii=False))

    @app.command("knowledge-link-drift")
    def knowledge_link_drift_cmd(
        workspace: str = typer.Option(..., help="Path to .memory-center/workspace.yaml"),
        wiki_root: str = typer.Option("", help="Wiki root override; links without a recorded root need this."),
        scope: str = typer.Option("", help="Expected scope for mismatch findings."),
        mark_stale: bool = typer.Option(False, help="Mark drifted active links stale; default is read-only dry-run."),
        actor: str = typer.Option("workspace-system", help="Operator recorded on stale transitions."),
    ):
        """Detect KnowledgeLink drift; repair actions are advisory and read-only."""
        typer.echo(json.dumps(knowledge_link_drift(workspace, wiki_root=wiki_root, scope=scope, actor=actor, mark_stale=mark_stale), ensure_ascii=False))

    @app.command("knowledge-link-metrics")
    def knowledge_link_metrics_cmd(
        workspace: str = typer.Option(..., help="Path to .memory-center/workspace.yaml"),
    ):
        """Aggregate KnowledgeLink observability metrics; read-only."""
        typer.echo(json.dumps(knowledge_link_metrics(workspace), ensure_ascii=False))

    @app.command("wiki-assets-sync")
    def wiki_assets_sync(
        workspace: str = typer.Option(..., help="Path to .memory-center/workspace.yaml"),
        wiki_root: str = typer.Option(..., help="Personal Assistant Wiki root directory."),
        owner: str = typer.Option(..., help="Owner recorded on private Wiki assets."),
        scope: str = typer.Option("kaipuyun", help="Bounded business scope tag."),
    ):
        """Register selected Personal Wiki entries as governed reverse links."""
        print(sync_personal_wiki_assets(workspace, wiki_root=wiki_root, owner=owner, scope=scope))

    @app.command("job-status")
    def job_status(
        workspace: str = typer.Option(..., help="Path to .memory-center/workspace.yaml"),
        job_id: str = typer.Option("", help="Optional background job id; omit to list recent jobs."),
        limit: int = typer.Option(20, min=1, max=100, help="Maximum jobs to return when job-id is omitted."),
    ):
        """Show persisted background-job progress."""
        typer.echo(json.dumps(workspace_job_status(workspace, job_id, limit=limit), ensure_ascii=False, indent=2))

    @app.command("job-cancel")
    def job_cancel(
        workspace: str = typer.Option(..., help="Path to .memory-center/workspace.yaml"),
        job_id: str = typer.Option(..., help="Background or reindex coordinator job id."),
    ):
        """Request cooperative cancellation; the worker stops at the next stage boundary and publishing cannot be interrupted mid-way."""
        from memory_center.core.workspace.jobs import cancel_workspace_job

        typer.echo(json.dumps(cancel_workspace_job(workspace, job_id), ensure_ascii=False, indent=2))

    @app.command("performance-snapshot")
    def performance_snapshot(
        workspace: str = typer.Option(..., help="Path to .memory-center/workspace.yaml"),
        samples: int = typer.Option(5, min=1, max=20, help="Bounded probe count; never runs automatically."),
        tier: str = typer.Option("fast", help="fast|standard|deep"),
    ):
        """显式采样当前工作区查询 P95，并仅保存聚合指标。"""
        typer.echo(
            json.dumps(
                record_workspace_performance_snapshot(workspace, samples=samples, tier=tier), ensure_ascii=False, indent=2
            )
        )

    @app.command("performance-status")
    def performance_status(
        workspace: str = typer.Option(..., help="Path to .memory-center/workspace.yaml"),
        limit: int = typer.Option(20, min=1, max=100),
    ):
        """查看真实工作区 P95 快照趋势与下一步动作。"""
        typer.echo(json.dumps(workspace_performance_snapshot_status(workspace, limit=limit), ensure_ascii=False, indent=2))

    @app.command("scoped-refresh-performance")
    def scoped_refresh_performance(
        workspace: str = typer.Option(..., help="Path to .memory-center/workspace.yaml"),
        limit: int = typer.Option(20, min=1, max=100),
    ):
        """查看局部刷新 P50/P95、最慢阶段和预算状态。"""
        typer.echo(json.dumps(scoped_refresh_performance_status(workspace, limit=limit), ensure_ascii=False, indent=2))

    @app.command("runtime-governance")
    def runtime_governance(
        workspace: str = typer.Option(..., help="Path to .memory-center/workspace.yaml"),
        warning_gib: int = typer.Option(8, min=1, max=1024),
    ):
        """汇总真实工作区性能、空间、ANN、generation 与后台任务，不执行维护。"""
        typer.echo(
            json.dumps(workspace_runtime_governance(workspace, warning_gib=warning_gib), ensure_ascii=False, indent=2)
        )

    @app.command("external-capability-audit")
    def external_capability_audit(workspace: str = typer.Option(...)):
        """只读盘点宿主 Skill、插件和 MCP 配置元数据，并比较已保存基线。"""
        typer.echo(json.dumps(audit_external_capabilities(workspace), ensure_ascii=False, indent=2))

    @app.command("external-capability-snapshot")
    def external_capability_snapshot(workspace: str = typer.Option(...)):
        """显式保存外部能力元数据基线，不安装、启用或删除任何能力。"""
        typer.echo(json.dumps(snapshot_external_capabilities(workspace), ensure_ascii=False, indent=2))

    @app.command("http-route-contract-audit")
    def http_route_contract_audit():
        """校验所有 HTTP 路由都有明确的读写传输契约。"""
        result = audit_http_route_contract()
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
        if not result["passed"]:
            raise typer.Exit(code=1)

    @app.command("serve-http")
    def serve_http_cmd(
        workspace: Optional[str] = typer.Option(None, help="Default workspace.yaml for workspace routes."),
        host: str = typer.Option("127.0.0.1"),
        port: int = typer.Option(8765),
        access_token: str = typer.Option("", envvar="MEMORY_CENTER_HTTP_TOKEN", help="Required for non-loopback binding."),
    ):
        """Serve a lightweight local HTTP bridge for workspace and group queries."""
        validate_http_binding(host, access_token)
        print(
            {"http": "starting", "host": host, "port": port, "workspace": workspace, "authentication": bool(access_token)}
        )
        serve_http(workspace, host=host, port=port, access_token=access_token)
