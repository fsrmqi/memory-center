"""Tooling 命令族:按业务域从 cli/main.py 拆出的命令组(ADR-0002)。"""
from __future__ import annotations

# Typer evaluates command annotations at runtime in Python 3.9 environments.
# ruff: noqa: UP006,UP035,UP045
import json
from pathlib import Path
from typing import Optional

import typer
from rich import print

from memory_center.application.presentation import export_mermaid
from memory_center.core.knowledge.communities import analyze_architecture_communities
from memory_center.core.knowledge.wiki import generate_skills, generate_wiki
from memory_center.core.presentation.evidence_subgraph import export_evidence_subgraph
from memory_center.hooks.adapters.claude_code import generate_claude_code_hooks, write_claude_code_settings
from memory_center.hooks.adapters.codex import generate_codex_scripts
from memory_center.hooks.adapters.cursor import generate_cursor_rules
from memory_center.hooks.runner import run_hook_cli
from memory_center.hooks.spec import load_hooks_config


def register_tooling_commands(app: typer.Typer) -> None:
    @app.command("export-mermaid")
    def export_mermaid_cmd(workspace: str = typer.Option(...), output: Optional[str] = typer.Option(None)):
        """Export service topology as a Mermaid flowchart."""
        diagram = export_mermaid(workspace)
        if output:
            Path(output).write_text(diagram, encoding="utf-8")
            print(f"[green]Wrote:[/green] {output}")
        else:
            print(diagram)

    @app.command("export-evidence-subgraph")
    def export_evidence_subgraph_cmd(
        workspace: str = typer.Option(...),
        target: str = typer.Option(..., help="Graph node id or bounded symbol query."),
        direction: str = typer.Option("both"),
        max_depth: int = typer.Option(2, min=1, max=3),
        max_edges: int = typer.Option(60, min=1, max=120),
        output_format: str = typer.Option("json", "--format"),
        output: Optional[str] = typer.Option(None),
    ):
        """Export a bounded evidence subgraph; it never scans the full graph."""
        result = export_evidence_subgraph(
            workspace, target, direction=direction, max_depth=max_depth, max_edges=max_edges, output_format=output_format
        )
        content = result.get("content", json.dumps(result, ensure_ascii=False, indent=2))
        if output:
            Path(output).write_text(content, encoding="utf-8")
            print(f"[green]Wrote:[/green] {output}")
        else:
            print(content)

    @app.command("architecture-communities")
    def architecture_communities_cmd(
        workspace: str = typer.Option(...),
        limit: int = typer.Option(20, min=1, max=50),
    ):
        """Explicitly aggregate project communities and central graph nodes."""
        print(analyze_architecture_communities(workspace, limit=limit))

    @app.command("generate-wiki")
    def generate_wiki_cmd(workspace: str = typer.Option(...), output: Optional[str] = typer.Option(None)):
        """Generate bilingual Markdown architecture wiki from indexes and memory."""
        print(generate_wiki(workspace, output))

    @app.command("generate-skills")
    def generate_skills_cmd(workspace: str = typer.Option(...), output: Optional[str] = typer.Option(None)):
        """Generate Claude/agent skills from historical task memory."""
        print(generate_skills(workspace, output))

    @app.command("run-hook")
    def run_hook_cmd(
        workspace: str = typer.Option(..., help="Path to .memory-center/workspace.yaml"),
        hook: str = typer.Option(..., help="Hook event name: session_start, pre_edit, session_stop, user_prompt_submit"),
    ):
        """Execute a hook defined in hooks.yaml. Host-agnostic lifecycle event runner.

    Reads stdin JSON from the host, resolves parameters, dispatches to
    the appropriate Memory Center facade, and outputs a structured result.
    Process exit code: 0=allow, 2=block (guard mode), 1=error.
    """
        exit_code = run_hook_cli(workspace, hook)
        raise typer.Exit(code=exit_code)

    @app.command("generate-hooks")
    def generate_hooks_cmd(
        workspace: str = typer.Option(..., help="Path to .memory-center/workspace.yaml"),
        host: str = typer.Option("claude-code", help="Target host: claude-code, codex, cursor"),
        output: str = typer.Option("", help="Output path. Default: auto-detect based on host."),
    ):
        """Generate host-specific hook configuration from hooks.yaml.

    For claude-code: writes .claude/settings.local.json with hooks section.
    For codex: generates shell wrapper scripts in .codex-hooks/.
    For cursor: generates .cursorrules additions.
    """
        config = load_hooks_config(workspace)
        if host == "claude-code":
            result = write_claude_code_settings(workspace, output_path=output or None, hooks_config=config)
            print(
                {"host": "claude-code", "output_path": str(result), "hooks": generate_claude_code_hooks(workspace, config)}
            )
        elif host == "codex":
            scripts = generate_codex_scripts(workspace, output_dir=output or None, hooks_config=config)
            print({"host": "codex", "generated_scripts": [str(s) for s in scripts]})
        elif host == "cursor":
            rules_path = generate_cursor_rules(workspace, output_path=output or None, hooks_config=config)
            print({"host": "cursor", "output_path": str(rules_path)})
        else:
            print({"error": f"Unknown host: {host}. Valid hosts: claude-code, codex, cursor"})
            raise typer.Exit(code=1)

    @app.command("verification-loop")
    def verification_loop_cmd(
        workspace: str = typer.Option(..., help="Path to .memory-center/workspace.yaml"),
        task_type: str = typer.Option("general", help="Task type: code_change, feature, bugfix, general"),
        task_id: str = typer.Option("default", help="Task identifier"),
    ):
        """Generate verification checklist for a task."""
        from memory_center.core.verification.loop import VerificationLoop

        vl = VerificationLoop(workspace)
        analysis = {"task_type": task_type, "workspace": workspace}
        checklist = vl.generate_checklist(analysis)
        status = vl.get_status(task_id)
        print(json.dumps({"checklist": checklist, "status": status}, indent=2, default=str))

    @app.command("pattern-promotion")
    def pattern_promotion_cmd(
        workspace: str = typer.Option(..., help="Path to .memory-center/workspace.yaml"),
        action: str = typer.Option("list", help="Action: propose, list, promote"),
        text: str = typer.Option("", help="Pattern text for propose/promote"),
    ):
        """Manage pattern promotion pipeline."""
        from memory_center.core.verification.pattern_promotion import PatternPromotion

        pp = PatternPromotion(workspace)
        if action == "propose":
            result = pp.propose({"rule_text": text, "source": "cli"})
        elif action == "list":
            result = {"proposals": pp.list_proposals()}
        elif action == "promote":
            result = pp.promote(text)
        else:
            result = {"error": f"Unknown action: {action}"}
        print(json.dumps(result, indent=2, default=str, ensure_ascii=False))

    @app.command("heuristics")
    def heuristics_cmd(
        workspace: str = typer.Option(..., help="Path to .memory-center/workspace.yaml"),
        action: str = typer.Option("query", help="Action: query, record, feedback, explain"),
        text: str = typer.Option("", help="Query text or JSON record data"),
    ):
        """Query or record learned heuristics."""
        import json as _json

        from memory_center.core.verification.heuristics import HeuristicsRegister

        hr = HeuristicsRegister(workspace)
        if action == "query":
            result = {"heuristics": hr.query(text)}
        elif action in {"record", "feedback", "explain"}:
            try:
                data = _json.loads(text) if text else {}
            except _json.JSONDecodeError:
                data = {"pattern": text}
            if action == "record":
                entry = hr.record(data)
                result = {"status": "recorded", "entry": entry}
            elif action == "explain":
                result = hr.explain(
                    candidate_type=str(data.get("candidate_type", "") or ""),
                    target=str(data.get("target", "") or ""),
                    category=str(data.get("category", "") or "candidate-path"),
                    heuristic_id=str(data.get("heuristic_id", "") or ""),
                    pattern=str(data.get("pattern", "") or ""),
                    limit=int(data.get("limit", 10) or 10),
                )
            else:
                feedback = hr.record_candidate_path_feedback(
                    candidate_type=str(data.get("candidate_type", "") or ""),
                    target=str(data.get("target", "") or ""),
                    outcome=str(data.get("outcome", "") or ""),
                    evidence=data.get("evidence") or [],
                    source=str(data.get("source", "") or "cli"),
                    task_id=str(data.get("task_id", "") or ""),
                    session_id=str(data.get("session_id", "") or ""),
                    weight_before=data.get("weight_before"),
                    weight_delta=data.get("weight_delta"),
                    why=str(data.get("why", "") or ""),
                    next_action=str(data.get("next_action", "") or ""),
                    verification_cost=str(data.get("verification_cost", "") or ""),
                    category=str(data.get("category", "") or "candidate-path"),
                    pattern=str(data.get("pattern", "") or ""),
                    trigger=str(data.get("trigger", "") or ""),
                )
                result = {"status": "recorded", "feedback": feedback}
        else:
            result = {"error": f"Unknown action: {action}"}
        print(json.dumps(result, indent=2, default=str, ensure_ascii=False))

    @app.command("workflow-profile")
    def workflow_profile_cmd(
        profile: str = typer.Option("quick-fix", help="Profile name: quick-fix, contract-change, long-task, architecture"),
    ):
        """Get a workflow protocol profile."""
        import dataclasses as _dc

        from memory_center.core.verification.workflow_profiles import get_workflow_profile

        result = get_workflow_profile(profile)
        if _dc.is_dataclass(result) and not isinstance(result, type):
            result = _dc.asdict(result)
        typer.echo(json.dumps(result, indent=2, default=str, ensure_ascii=False))

    @app.command("workflow-recommend")
    def workflow_recommend_cmd(
        workspace: str = typer.Option("", help="Optional path to .memory-center/workspace.yaml for learned recommendation"),
        description: str = typer.Option(..., help="Task description to match"),
    ):
        """Recommend a workflow profile based on task description."""
        from memory_center.core.verification.workflow_profiles import (
            recommend_workflow,
            recommend_workflow_with_learning,
        )

        result = recommend_workflow_with_learning(workspace, description) if workspace else recommend_workflow(description)
        typer.echo(json.dumps(result, indent=2, default=str, ensure_ascii=False))

    @app.command("bundle-export")
    def bundle_export_cmd(
        workspace: str = typer.Option(..., help="Path to .memory-center/workspace.yaml"),
        agent: str = typer.Option("codex", help="Target agent: codex, claude, cursor"),
        output: str = typer.Option("", help="Output directory"),
    ):
        """Export agent usage bundle for the specified platform."""
        from memory_center.core.verification.bundle_export import generate_agent_bundle

        result = generate_agent_bundle(workspace, agent=agent)
        print(json.dumps(result, indent=2, default=str))

    @app.command("setup-agent")
    def setup_agent_cmd(
        workspace: str = typer.Option(..., help="Path to .memory-center/workspace.yaml"),
    ):
        """Generate instructions, repair MCP bindings, and audit host-agent readiness."""
        from memory_center.core.audit.runtime import setup_agent_runtime

        result = setup_agent_runtime(workspace)
        typer.echo(json.dumps(result, indent=2, default=str, ensure_ascii=False))

    @app.command("explanation")
    def explanation_cmd(
        text: str = typer.Option(..., help="Content to explain"),
        persona: str = typer.Option("developer", help="Target persona: developer, architect, manager"),
    ):
        """Generate persona-adapted explanation."""
        from memory_center.core.explanation.schema import Explanation

        exp = Explanation(subject="explanation", summary=text, persona=persona)
        result = exp.adapt_for_persona(persona).to_full()
        print(json.dumps(result, indent=2, default=str, ensure_ascii=False))

    @app.command("business-flow")
    def business_flow_cmd(
        workspace: str = typer.Option(..., help="Path to .memory-center/workspace.yaml"),
        seed: str = typer.Option(..., help="Seed node ID to extract flows from"),
        max_depth: int = typer.Option(4, help="Maximum traversal depth"),
    ):
        """Extract business flows from a seed node."""
        from memory_center.core.domain.flow import extract_business_flows_for_workspace

        result = extract_business_flows_for_workspace(workspace, seed, max_depth=max_depth)
        print(json.dumps(result, indent=2, default=str))

    @app.command("business-flow-impact")
    def business_flow_impact_cmd(
        workspace: str = typer.Option(..., help="Path to .memory-center/workspace.yaml"),
        node_id: str = typer.Option(..., help="Node ID to check impact for"),
        max_depth: int = typer.Option(3, help="Maximum depth"),
    ):
        """Find impacted nodes along business flows."""
        from memory_center.core.domain.flow import business_flow_impact_for_workspace

        result = business_flow_impact_for_workspace(workspace, node_id, max_depth=max_depth)
        print(json.dumps(result, indent=2, default=str))

