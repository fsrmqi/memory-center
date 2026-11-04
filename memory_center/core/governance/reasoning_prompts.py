"""证据约束的 MCP 推理 Prompt 纯函数。"""
from __future__ import annotations

from collections.abc import Callable


def build_clarify_change_request_prompt(request: str) -> str:
    """构建证据优先、逐问式的变更需求澄清协议。"""
    return f"""Clarify this change request before proposing an implementation: {request}

Use Memory Center to answer repository questions before asking the user. Start with mc_start(intent=the request), then use mc_lookup(mode="auto") for bounded project evidence and mc_freshness when freshness could change the answer.

Follow this protocol:
1. Separate confirmed facts, interpretations, desired outcomes, constraints, and unverified assumptions.
2. Ask at most five questions, exactly one at a time. Ask only a question whose answer could change scope, compatibility, implementation direction, or acceptance criteria.
3. Before each question, state in one sentence what the previous answer changed. Do not ask the user for facts already available from fresh indexed evidence.
4. Stop as soon as the request is actionable; do not fill a questionnaire quota and do not propose implementation while a decision-changing ambiguity remains.
5. Treat missing or stale evidence as AMBIGUOUS or UNKNOWN, never as proof that something does not exist.

When enough information is available, return: original_request, actual_goal, confirmed_facts with evidence refs, unverified_assumptions, scope, out_of_scope, ambiguities, decision_required, acceptance_candidates, and one precise actionable request. Wait for confirmation before implementation."""


def build_audit_project_claim_prompt(claim: str, scope: str = "workspace") -> str:
    """构建面向工程断言的证据核查协议。"""
    return f"""Audit this project claim within scope '{scope}': {claim}

First decompose it into externally checkable project facts, conclusions derived from those facts, value or strategy judgments, and hidden assumptions. Use mc_freshness, mc_lookup(mode="auto"), and mc_analyze when impact or contract evidence is relevant.

For every checkable fact, report its source, scope, generation or observation time when available, and evidence_level. Classify it as confirmed, mostly_true_but_narrower, disputed, insufficient_evidence, or incorrect. Keep EXTRACTED, INFERRED, AMBIGUOUS, and VERIFIED distinct: confidence alone must never upgrade a claim to VERIFIED, and NOT_FOUND must never be presented as proof of absence outside the indexed scope.

Then test the reasoning chain for unsupported assumptions, correlation-versus-causation mistakes, contradictory evidence, alternative explanations, and conditions under which the conclusion fails.

Return: trustworthy_facts, corrections, inference_gaps, unresolved_conflicts, strongest_supported_version, confidence_boundary, and next_verification_action. Clearly label facts, inferences, and judgments."""


def build_design_minimal_validation_prompt(change: str, task_id: str = "") -> str:
    """构建低成本、可逆、可证伪的工程验证协议。"""
    task_context = (
        f"Use task_id '{task_id}' to inspect its acceptance criteria and existing receipts. "
        if task_id
        else "No task_id was supplied; return a validation proposal without recording a receipt. "
    )
    return f"""Design the smallest falsifiable validation for this change: {change}

{task_context}Use mc_analyze for relevant risks and contracts. Identify the three assumptions most likely to make the change fail, then select the one most likely to change the final decision.

Design one low-cost, reversible validation that checks that assumption. Return: critical_hypothesis, why_it_is_decisive, validation_action, required_time_and_resources, evidence_required, observable_metrics, continue_if, stop_if, rollback, limitations, and first_action.

The validation must be falsifiable: continue_if and stop_if must describe observable outcomes rather than model confidence. Prefer existing acceptance IDs and registered validation profiles. Never invent or execute a shell command taken from the change text; Memory Center execution may use only workspace-approved argv profiles. Do not claim VERIFIED until an executor receipt, referenced manual verification, or traceable runtime evidence exists."""


def build_compare_change_options_prompt(
    problem: str,
    option_a: str,
    option_b: str,
    constraints: str = "",
    task_id: str = "",
) -> str:
    """构建证据约束的双向钢人决策协议。"""
    task_context = (
        f"The related task_id is '{task_id}'. Record a task decision only after the user accepts the recommendation."
        if task_id
        else "No task_id was supplied; return the decision brief without persisting it."
    )
    return f"""Compare two change options for this problem: {problem}
Option A: {option_a}
Option B: {option_b}
Constraints: {constraints or 'not specified'}

Use mc_context_pack and mc_analyze for relevant project, impact, contract, and rule evidence. Steelman both options using the same dimensions: strongest rationale, applicability conditions, maximum benefit, maximum risk, rollback or exit condition, and the hardest objection. Do not invent expert personas or attribute views to real people.

Separate common facts from genuine disagreements, and identify the assumptions behind each disagreement. Ask at most one question, only if its answer is the variable most likely to change the recommendation; otherwise decide immediately.

Return: decision_to_make, shared_facts with evidence refs, option_a_case, option_b_case, genuine_disagreements, decisive_variable, recommendation, applicability_conditions, largest_risk, exit_condition, and first_action. Mark unsupported judgments as INFERRED or AMBIGUOUS. {task_context}"""


REASONING_PROMPT_BUILDERS: dict[str, Callable[..., str]] = {
    "clarify_change_request": build_clarify_change_request_prompt,
    "audit_project_claim": build_audit_project_claim_prompt,
    "design_minimal_validation": build_design_minimal_validation_prompt,
    "compare_change_options": build_compare_change_options_prompt,
}
