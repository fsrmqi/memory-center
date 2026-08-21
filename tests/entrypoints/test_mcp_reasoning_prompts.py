from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import memory_center.mcp.insights as insights


class _FakeMCP:
    def __init__(self) -> None:
        self.prompts: dict[str, Callable[..., str]] = {}
        self.resources: dict[str, Callable[..., Any]] = {}
        self.tools: dict[str, Callable[..., Any]] = {}

    def prompt(self):
        def decorator(func: Callable[..., str]):
            self.prompts[func.__name__] = func
            return func

        return decorator

    def resource(self, uri: str):
        def decorator(func: Callable[..., Any]):
            self.resources[uri] = func
            return func

        return decorator

    def tool(self):
        def decorator(func: Callable[..., Any]):
            self.tools[func.__name__] = func
            return func

        return decorator


def test_reasoning_prompts_are_registered_additively(monkeypatch) -> None:
    mcp = _FakeMCP()
    monkeypatch.setattr(insights, "safe_mcp_tool", lambda target, _context: target.tool())

    insights.register_insight_surface(mcp, SimpleNamespace(workspace_file="workspace.yaml", startup_diagnostics={}))

    assert {
        "clarify_change_request",
        "audit_project_claim",
        "design_minimal_validation",
        "compare_change_options",
    }.issubset(mcp.prompts)
    assert {"detect_impact", "spring_cloud_safe_change"}.issubset(mcp.prompts)


def test_clarify_change_request_is_bounded_and_evidence_first() -> None:
    prompt = insights.build_clarify_change_request_prompt("扩展订单 DTO")

    assert "at most five questions" in prompt
    assert "exactly one at a time" in prompt
    assert "mc_start" in prompt and "mc_lookup" in prompt
    assert "AMBIGUOUS or UNKNOWN" in prompt
    assert "acceptance_candidates" in prompt
    assert "扩展订单 DTO" in prompt


def test_audit_project_claim_preserves_epistemic_boundaries() -> None:
    prompt = insights.build_audit_project_claim_prompt("所有消费者都兼容新字段", "order-service")

    for required in (
        "checkable project facts",
        "value or strategy judgments",
        "evidence_level",
        "confidence alone must never upgrade a claim to VERIFIED",
        "NOT_FOUND must never be presented as proof of absence",
        "strongest_supported_version",
    ):
        assert required in prompt
    assert "order-service" in prompt


def test_minimal_validation_is_falsifiable_and_executor_safe() -> None:
    prompt = insights.build_design_minimal_validation_prompt("升级 Feign 契约", "task-42")

    for required in (
        "critical_hypothesis",
        "continue_if",
        "stop_if",
        "rollback",
        "falsifiable",
        "workspace-approved argv profiles",
        "Do not claim VERIFIED",
        "task-42",
    ):
        assert required in prompt


def test_compare_change_options_steelmans_without_role_play() -> None:
    prompt = insights.build_compare_change_options_prompt(
        "接口迁移",
        "扩展旧接口",
        "新增 v2 接口",
        "必须兼容旧客户端",
        "task-43",
    )

    for required in (
        "Steelman both options",
        "same dimensions",
        "Do not invent expert personas",
        "Ask at most one question",
        "genuine_disagreements",
        "Record a task decision only after the user accepts",
    ):
        assert required in prompt
    assert "扩展旧接口" in prompt
    assert "新增 v2 接口" in prompt
