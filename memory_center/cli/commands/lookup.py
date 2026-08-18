"""Lookup 命令族:按业务域从 cli/main.py 拆出的命令组(ADR-0002)。"""
from __future__ import annotations

# Typer evaluates command annotations at runtime in Python 3.9 environments.
# ruff: noqa: UP006,UP035,UP045
import pprint
from typing import List

import typer
from rich import print

from memory_center.core.orchestrator import (
    memory_backend_query,
    memory_callees,
    memory_callers,
    memory_context,
    memory_contracts,
    memory_detect_changes,
    memory_impact,
    memory_plan_change,
    memory_query_hybrid,
    memory_ref_batch,
    memory_ref_get,
    memory_search_code,
    memory_symbol,
    memory_tool_usage_report,
    memory_verify_checklist,
    workspace_lookup_hint,
    workspace_record_agent_guidance,
    workspace_trace,
)

from ._options import REQUIRED_REF_IDS


def register_lookup_commands(app: typer.Typer) -> None:
    @app.command()
    def trace(workspace: str = typer.Option(...), entry: str = typer.Option(...)):
        """Trace cross-service candidates by class, Feign client, endpoint or topic."""
        print(workspace_trace(workspace, entry))

    @app.command("query")
    def query_cmd(
        workspace: str = typer.Option(...),
        text: str = typer.Option(...),
        limit: int = typer.Option(20),
        project: str = typer.Option("", help="Filter by project name for disambiguation."),
        session_id: str = typer.Option("", help="Record returned agent_next_steps into this session."),
        vector: bool = typer.Option(
            False, "--vector/--no-vector", help="Enable ANN vector retrieval when dense embeddings are available."
        ),
        vector_weight: float = typer.Option(0.15, help="Fusion weight for vector retrieval when --vector is enabled."),
        rerank: bool = typer.Option(
            False, "--rerank/--no-rerank", help="Rerank a bounded top-K candidate set with the optional cross-encoder."
        ),
    ):
        """Graph-aware query across services, files, symbols, contracts and memory."""
        query_kwargs = {
            "project": project,
            "enable_vector": vector,
            "vector_weight": vector_weight,
        }
        if rerank:
            query_kwargs["enable_reranker"] = True
        result = memory_query_hybrid(workspace, text, limit, **query_kwargs)
        if session_id.strip():
            workspace_record_agent_guidance(
                workspace, session_id, query=text, mode="query", source="cli.query", payload=result
            )
        typer.echo(
            pprint.pformat(
                result,
                width=240,
                sort_dicts=False,
            ),
        )

    @app.command("search-code")
    def search_code_cmd(
        workspace: str = typer.Option(...),
        text: str = typer.Option(...),
        scope: str = typer.Option(""),
        limit: int = typer.Option(20),
        project: str = typer.Option("", help="Filter by project name."),
    ):
        """Keyword search over indexed files/symbol hints."""
        print(memory_search_code(workspace, text, scope=scope, limit=limit, project=project))

    @app.command("symbol")
    def symbol_cmd(
        workspace: str = typer.Option(...),
        name: str = typer.Option(...),
        limit: int = typer.Option(10),
        project: str = typer.Option("", help="Filter by project name for disambiguation."),
        view: str = typer.Option("full", help="full|compact"),
        budget: str = typer.Option("medium", help="small|medium|large"),
    ):
        """Resolve one symbol and return best match candidates."""
        print(memory_symbol(workspace, name, limit=limit, project=project, view=view, budget=budget))

    @app.command("callers")
    def callers_cmd(
        workspace: str = typer.Option(...),
        symbol: str = typer.Option(...),
        depth: int = typer.Option(2),
        limit: int = typer.Option(80),
        project: str = typer.Option("", help="Filter by project name for disambiguation."),
        view: str = typer.Option("full", help="full|compact"),
        budget: str = typer.Option("medium", help="small|medium|large"),
        min_confidence: float = typer.Option(0.85, help="Minimum edge confidence; use 0 to include unresolved calls."),
    ):
        """Find upstream callers for one symbol."""
        print(
            memory_callers(
                workspace,
                symbol,
                depth=depth,
                limit=limit,
                project=project,
                view=view,
                budget=budget,
                min_confidence=min_confidence,
            )
        )

    @app.command("callees")
    def callees_cmd(
        workspace: str = typer.Option(...),
        symbol: str = typer.Option(...),
        depth: int = typer.Option(2),
        limit: int = typer.Option(80),
        project: str = typer.Option("", help="Filter by project name for disambiguation."),
        view: str = typer.Option("full", help="full|compact"),
        budget: str = typer.Option("medium", help="small|medium|large"),
        min_confidence: float = typer.Option(0.85, help="Minimum edge confidence; use 0 to include unresolved calls."),
    ):
        """Find downstream callees for one symbol."""
        print(
            memory_callees(
                workspace,
                symbol,
                depth=depth,
                limit=limit,
                project=project,
                view=view,
                budget=budget,
                min_confidence=min_confidence,
            )
        )

    @app.command("context")
    def context_cmd(
        workspace: str = typer.Option(...),
        name: str = typer.Option(...),
        max_depth: int = typer.Option(2),
        project: str = typer.Option("", help="Filter by project name for disambiguation."),
        view: str = typer.Option("full", help="full|compact"),
        budget: str = typer.Option("medium", help="small|medium|large"),
    ):
        """Return 360-degree context for a symbol, endpoint, topic, service or file."""
        print(memory_context(workspace, name, max_depth, project=project, view=view, budget=budget))

    @app.command("impact")
    def impact_cmd(
        workspace: str = typer.Option(...),
        target: str = typer.Option(...),
        direction: str = typer.Option("upstream"),
        max_depth: int = typer.Option(3),
        project: str = typer.Option("", help="Filter by project name for local evidence while keeping declaration anchor."),
        view: str = typer.Option("full", help="full|compact"),
        budget: str = typer.Option("medium", help="small|medium|large"),
    ):
        """Analyze upstream/downstream impact for a changed symbol or contract."""
        print(memory_impact(workspace, target, direction, max_depth, project=project, view=view, budget=budget))

    @app.command("detect-changes")
    def detect_changes_cmd(workspace: str = typer.Option(...), scope: str = typer.Option("staged")):
        """Map local git changes to affected projects, rules and risk level."""
        print(memory_detect_changes(workspace, scope))

    @app.command("contracts")
    def contracts_cmd(workspace: str = typer.Option(...)):
        """List Feign/API/MQ contracts discovered in the workspace."""
        print(memory_contracts(workspace))

    @app.command("plan-change")
    def plan_change_cmd(
        workspace: str = typer.Option(...),
        target: str = typer.Option(...),
        direction: str = typer.Option("upstream"),
        max_depth: int = typer.Option(3),
    ):
        """Generate one actionable change plan from impact evidence."""
        print(memory_plan_change(workspace, target, direction=direction, max_depth=max_depth))

    @app.command("verify-checklist")
    def verify_checklist_cmd(
        workspace: str = typer.Option(...),
        target: str = typer.Option(...),
    ):
        """Generate one verification checklist for a target change."""
        print(memory_verify_checklist(workspace, target))

    @app.command("lookup-hint")
    def lookup_hint_cmd(
        workspace: str = typer.Option(...),
        query: str = typer.Option(...),
        intent: str = typer.Option(""),
        limit: int = typer.Option(8),
    ):
        """Suggest whether to use Memory Center lookup tools or local search first."""
        print(workspace_lookup_hint(workspace, query=query, intent=intent, limit=limit))

    @app.command("tool-usage-report")
    def tool_usage_report_cmd(
        workspace: str = typer.Option(...),
        limit: int = typer.Option(200),
    ):
        """Summarize recent Memory Center vs external tool usage and lookup adoption."""
        print(memory_tool_usage_report(workspace, limit=limit))

    @app.command("ref-get")
    def ref_get_cmd(
        workspace: str = typer.Option(...),
        ref_id: str = typer.Option(...),
    ):
        """Resolve one short memory reference id into full raw content."""
        print(memory_ref_get(workspace, ref_id=ref_id))

    @app.command("ref-batch")
    def ref_batch_cmd(
        workspace: str = typer.Option(...),
        ref_id: List[str] = REQUIRED_REF_IDS,
    ):
        """Resolve multiple short memory reference ids."""
        print(memory_ref_batch(workspace, ref_ids=ref_id))

    @app.command("memory-backend-query")
    def memory_backend_query_cmd(
        workspace: str = typer.Option(...),
        collection: str = typer.Option(""),
        record_id: str = typer.Option(""),
        created_after: str = typer.Option(""),
        ref_path: str = typer.Option(""),
        project: str = typer.Option("", help="Filter records by project name."),
        payload_type: str = typer.Option("", help="Filter records by payload type."),
        limit: int = typer.Option(50),
    ):
        """Query mirrored SQLite memory backend records and refs."""
        print(
            memory_backend_query(
                workspace,
                collection=collection,
                record_id=record_id,
                created_after=created_after,
                ref_path=ref_path,
                project=project,
                payload_type=payload_type,
                limit=limit,
            )
        )

