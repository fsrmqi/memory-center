"""Gate 命令族:按业务域从 cli/main.py 拆出的命令组(ADR-0002)。"""
from __future__ import annotations

# Typer evaluates command annotations at runtime in Python 3.9 environments.
# ruff: noqa: UP006,UP035,UP045
import json
from pathlib import Path
from typing import List, Optional

import typer
from rich import print

from ._options import RELEASE_GATE_QUERY_OPTION


def register_gate_commands(app: typer.Typer) -> None:
    @app.command("assertion-status")
    def assertion_status_cmd(
        workspace: str = typer.Option(...),
        assertion_id: str = typer.Option(...),
        status: str = typer.Option(..., help="VERIFIED, REJECTED, EXTRACTED, INFERRED, or AMBIGUOUS."),
        verification_ref: str = typer.Option(
            "", help="Required when status is VERIFIED; use a sanitized evidence reference."
        ),
        actor: str = typer.Option(""),
    ):
        """Explicitly update one assertion status while preserving an audit event."""
        from memory_center.core.knowledge.assertions import update_assertion_status
        from memory_center.core.storage.workspace import WorkspaceStore

        print(
            json.dumps(
                update_assertion_status(
                    WorkspaceStore(workspace), assertion_id, status=status, verification_ref=verification_ref, actor=actor
                ),
                ensure_ascii=False,
                indent=2,
            )
        )

    @app.command("assertion-inspect")
    def assertion_inspect_cmd(
        workspace: str = typer.Option(...),
        assertion_id: str = typer.Option(...),
    ):
        """Expand one assertion reference without reading the assertion audit stream."""
        from memory_center.core.knowledge.assertions import inspect_assertion
        from memory_center.core.storage.workspace import WorkspaceStore

        print(json.dumps(inspect_assertion(WorkspaceStore(workspace), assertion_id), ensure_ascii=False, indent=2))

    @app.command("assertion-query")
    def assertion_query_cmd(
        workspace: str = typer.Option(...),
        as_of_generation: str = typer.Option(""),
        as_of_time: str = typer.Option(""),
        time_axis: str = typer.Option("valid", help="valid, event, or observed."),
        limit: int = typer.Option(20, min=1, max=500),
    ):
        """Read a bounded assertion history by validity, event, or observation time."""
        from memory_center.core.knowledge.assertions import query_assertions
        from memory_center.core.storage.workspace import WorkspaceStore

        print(
            json.dumps(
                query_assertions(
                    WorkspaceStore(workspace),
                    as_of_generation=as_of_generation,
                    as_of_time=as_of_time,
                    time_axis=time_axis,
                    limit=limit,
                ),
                ensure_ascii=False,
                indent=2,
            )
        )

    @app.command("parser-status")
    def parser_status_cmd():
        """Show tree-sitter Java activation status and install hints."""
        from memory_center.core.indexing.precision import tree_sitter_activation_status

        print(json.dumps(tree_sitter_activation_status(), ensure_ascii=False, indent=2, default=str))

    @app.command("bench-profile")
    def bench_profile_cmd(
        workspace: str = typer.Option(..., help="Workspace yaml file."),
        top: int = typer.Option(50, help="How many top functions to print."),
        sort_by: str = typer.Option(
            "cumulative",
            help="pstats sort key: cumulative | tottime | calls | pcalls.",
        ),
        by_module: bool = typer.Option(
            False,
            "--by-module/--by-function",
            help="Also print a module-level rollup (helpful for P1-0 diagnostics).",
        ),
        label: str = typer.Option("", help="Free-form tag appended to the .prof filename."),
    ):
        """Profile a full reindex with cProfile and print the hot functions.

        The raw ``.prof`` file is saved under
        ``$workspace/.memory-center/perf-profiles/`` so it can be re-analysed
        with ``snakeviz`` / ``pyprof2calltree``. Use this command before
        designing a perf optimisation so the proposed work targets the
        actual dominant cost (see ``docs/benchmarks/`` for the original P0
        motivation).
        """
        from memory_center.core.perf import aggregate_by_module, profile_reindex

        workspace_path = Path(workspace).expanduser().resolve()
        result = profile_reindex(workspace_path, top_n=top, sort_by=sort_by, label=label)
        print(f"[green]reindex elapsed:[/green] {result.elapsed_s:.2f}s")
        print(f"[green]pstats:[/green] {result.pstats_path}")
        print(f"  total_calls={result.total_calls} primitive_calls={result.primitive_calls}")
        print(f"\n=== top {top} by {sort_by} ===")
        print(result.top_summary)
        if by_module:
            print(f"\n=== top {min(20, top)} by module (cumulative time) ===")
            rows = aggregate_by_module(result.pstats_path, limit=min(20, top))
            for row in rows:
                print(
                    f"{row['cumulative_s']:>8.2f}s  tot={row['tottime_s']:>7.2f}s  calls={row['calls']:>8}  {row['module']}"
                )

    @app.command("release-gate")
    def release_gate_cmd(
        workspace: str = typer.Option(..., help="Workspace yaml file."),
        query: Optional[List[str]] = RELEASE_GATE_QUERY_OPTION,
        golden_cases: str = typer.Option("", help="Optional private Golden cases yaml file."),
        java_call_cases: str = typer.Option("", help="Optional private Java call resolution cases yaml file."),
        parser_limit: int = typer.Option(0, min=0, help="Parser comparison sample size; 0 disables it."),
        baseline: str = typer.Option("", help="Optional portable release-gate baseline JSON file."),
        save_baseline: str = typer.Option("", help="Optional output path for the current portable baseline."),
        label: str = typer.Option("current", help="Label used when saving a baseline."),
        max_latency_regression_pct: float = typer.Option(15.0, min=0.0, help="Maximum component P95 latency regression."),
        query_samples: int = typer.Option(
            1, min=1, max=20, help="Samples per query; first is cold, later samples measure hot P95."
        ),
        max_hot_query_p95_ms: float = typer.Option(
            2000.0, min=0.0, help="Maximum hot-query P95 in milliseconds; 0 disables the absolute budget."
        ),
        ontology_path: List[str] = typer.Option([], help="Optional logical paths for isolated ontology performance gate."),  # noqa: B008
        ontology_full: bool = typer.Option(False, help="Run the isolated full ontology reindex gate."),
        max_quality_drop: float = typer.Option(0.02, min=0.0, max=1.0, help="Maximum component quality-score drop."),
        cochange_commits: int = typer.Option(
            0, min=0, max=100, help="Independent Git co-change cases; 0 disables the gate component."
        ),
    ):
        """Run index, retrieval and optional precision checks as one release gate."""

        from memory_center.application.release_gate import run_release_gate, save_release_gate_baseline

        result = run_release_gate(
            workspace,
            queries=list(query or []),
            golden_cases=golden_cases or None,
            java_call_cases=java_call_cases or None,
            parser_limit=parser_limit,
            baseline=baseline or None,
            max_latency_regression_pct=max_latency_regression_pct,
            query_samples=query_samples,
            max_hot_query_p95_ms=max_hot_query_p95_ms,
            ontology_paths=ontology_path,
            ontology_full=ontology_full,
            max_quality_drop=max_quality_drop,
            cochange_commits=cochange_commits,
        )
        response: dict[str, object] = {"result": result}
        if save_baseline and result["passed"]:
            response["baseline"] = save_release_gate_baseline(result, save_baseline, label=label)
        elif save_baseline:
            response["baseline"] = {"saved": False, "reason": "release_gate_failed"}
        print(json.dumps(response, ensure_ascii=False, indent=2, default=str))
        if not result["passed"]:
            raise typer.Exit(code=1)

