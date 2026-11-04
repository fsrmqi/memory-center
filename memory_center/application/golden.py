"""Golden 用例的任务执行器；评分与统计仍位于 core.benchmark。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from memory_center.core.benchmark.cases import GoldenCase
from memory_center.core.benchmark.golden import extract_logical_evidence
from memory_center.core.benchmark.golden import run_golden_suite as score_golden_suite


def run_golden_suite(workspace_file: str | Path, cases_file: str | Path, **kwargs: Any) -> dict[str, Any]:
    if kwargs.get("case_runner") is not None:
        return score_golden_suite(workspace_file, cases_file, **kwargs)

    def runner(case: GoldenCase) -> dict[str, Any]:
        from memory_center.core import orchestrator

        if case.mode == "walkthrough":
            payload = orchestrator.memory_method_walkthrough(workspace_file, case.query, depth=6, limit=160, view="full", budget="large", report_level="deep", project=case.project)
        elif case.mode == "impact":
            payload = orchestrator.memory_impact(workspace_file, case.query, direction="upstream", max_depth=4, project=case.project, view="full", budget="large")
        elif case.mode == "context":
            payload = orchestrator.memory_context(workspace_file, case.query, max_depth=3, project=case.project, view="full", budget="large")
        else:
            payload = orchestrator.memory_query_hybrid(workspace_file, case.query, limit=80, enable_vector=case.enable_vector, project=case.project)
        return {**extract_logical_evidence(payload), "payload": payload}

    return score_golden_suite(workspace_file, cases_file, case_runner=runner, **kwargs)
