"""证据约束推理 Prompt 的可重复静态合同与人工观测评测。"""
from __future__ import annotations

import hashlib
import inspect
import re
from pathlib import Path
from typing import Any

import yaml

from memory_center.core.governance.reasoning_prompts import REASONING_PROMPT_BUILDERS

_CASE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_OBSERVATION_CHECKS = (
    "bounded_interaction",
    "evidence_used",
    "epistemic_boundary_respected",
    "actionable_output",
)

BUILTIN_REASONING_PROMPT_CASES: tuple[dict[str, Any], ...] = (
    {
        "case_id": "clarify-change-request-smoke",
        "prompt": "clarify_change_request",
        "args": {"request": "Add a backward-compatible field to a shared request contract."},
        "required_markers": ["mc_start", "mc_lookup", "at most five questions", "exactly one at a time", "AMBIGUOUS or UNKNOWN", "acceptance_candidates"],
        "forbidden_markers": ["assume the missing service does not exist"],
        "real_case": False,
    },
    {
        "case_id": "audit-project-claim-smoke",
        "prompt": "audit_project_claim",
        "args": {"claim": "Every consumer is compatible with the new field.", "scope": "workspace"},
        "required_markers": ["checkable project facts", "value or strategy judgments", "evidence_level", "confidence alone must never upgrade a claim to VERIFIED", "NOT_FOUND must never be presented as proof of absence"],
        "forbidden_markers": ["confidence is equivalent to VERIFIED"],
        "real_case": False,
    },
    {
        "case_id": "design-minimal-validation-smoke",
        "prompt": "design_minimal_validation",
        "args": {"change": "Change a service contract while preserving existing clients.", "task_id": "example-task"},
        "required_markers": ["critical_hypothesis", "continue_if", "stop_if", "rollback", "falsifiable", "workspace-approved argv profiles", "Do not claim VERIFIED"],
        "forbidden_markers": ["execute any supplied shell command"],
        "real_case": False,
    },
    {
        "case_id": "compare-change-options-smoke",
        "prompt": "compare_change_options",
        "args": {"problem": "Choose a compatible API migration path.", "option_a": "Extend the existing endpoint.", "option_b": "Introduce a versioned endpoint.", "constraints": "Existing clients must keep working.", "task_id": "example-task"},
        "required_markers": ["Steelman both options", "same dimensions", "Do not invent expert personas", "Ask at most one question", "genuine_disagreements", "Record a task decision only after the user accepts"],
        "forbidden_markers": ["invent a world-famous expert"],
        "real_case": False,
    },
)


def _load_yaml_mapping(path: str | Path, *, label: str) -> dict[str, Any]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a YAML object")
    if payload.get("schema_version") != 1:
        raise ValueError(f"{label} schema_version must be 1")
    return payload


def load_reasoning_prompt_cases(cases_file: str | Path | None = None) -> list[dict[str, Any]]:
    raw_cases = list(BUILTIN_REASONING_PROMPT_CASES) if cases_file is None else _load_yaml_mapping(cases_file, label="reasoning prompt cases").get("cases", [])
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("reasoning prompt cases must contain a non-empty cases list")
    cases: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_cases:
        if not isinstance(raw, dict):
            raise ValueError("each reasoning prompt case must be an object")
        case_id = str(raw.get("case_id", ""))
        if not _CASE_ID_RE.fullmatch(case_id):
            raise ValueError("reasoning prompt case_id must be a portable lowercase logical identifier")
        if case_id in seen:
            raise ValueError("reasoning prompt case_id values must be unique")
        seen.add(case_id)
        prompt = str(raw.get("prompt", ""))
        builder = REASONING_PROMPT_BUILDERS.get(prompt)
        if builder is None:
            raise ValueError(f"unsupported reasoning prompt: {prompt}")
        args = raw.get("args", {})
        if not isinstance(args, dict):
            raise ValueError("reasoning prompt case args must be an object")
        try:
            inspect.signature(builder).bind(**args)
        except TypeError as exc:
            raise ValueError(f"invalid args for reasoning prompt case {case_id}") from exc
        required = raw.get("required_markers", [])
        forbidden = raw.get("forbidden_markers", [])
        if not isinstance(required, list) or not required or not all(isinstance(item, str) and item for item in required):
            raise ValueError("reasoning prompt required_markers must be a non-empty string list")
        if not isinstance(forbidden, list) or not all(isinstance(item, str) and item for item in forbidden):
            raise ValueError("reasoning prompt forbidden_markers must be a string list")
        cases.append({"case_id": case_id, "prompt": prompt, "args": args, "required_markers": required, "forbidden_markers": forbidden, "real_case": raw.get("real_case") is True})
    return cases


def load_reasoning_prompt_observations(observations_file: str | Path | None = None) -> dict[str, dict[str, Any]]:
    if observations_file is None:
        return {}
    raw_observations = _load_yaml_mapping(observations_file, label="reasoning prompt observations").get("observations", [])
    if not isinstance(raw_observations, list):
        raise ValueError("reasoning prompt observations must be a list")
    observations: dict[str, dict[str, Any]] = {}
    for raw in raw_observations:
        if not isinstance(raw, dict):
            raise ValueError("each reasoning prompt observation must be an object")
        case_id = str(raw.get("case_id", ""))
        if not _CASE_ID_RE.fullmatch(case_id) or case_id in observations:
            raise ValueError("reasoning prompt observation case_id must be portable and unique")
        reviewer = str(raw.get("reviewer", "")).strip()
        evidence_refs = raw.get("evidence_refs", [])
        checks = raw.get("checks", {})
        if not reviewer:
            raise ValueError("reasoning prompt observation reviewer is required")
        if not isinstance(evidence_refs, list) or not evidence_refs or not all(isinstance(item, str) and item for item in evidence_refs):
            raise ValueError("reasoning prompt observation evidence_refs must be a non-empty string list")
        if not isinstance(checks, dict) or set(checks) != set(_OBSERVATION_CHECKS) or not all(isinstance(checks[name], bool) for name in _OBSERVATION_CHECKS):
            raise ValueError("reasoning prompt observation checks must contain the four required boolean checks")
        observations[case_id] = {"passed": all(checks.values()), "evidence_ref_count": len(evidence_refs), "identity_assurance": "self_asserted"}
    return observations


def evaluate_reasoning_prompts(
    cases_file: str | Path | None = None,
    observations_file: str | Path | None = None,
) -> dict[str, Any]:
    """渲染并核查 Prompt 合同；真实效果只接受本地 real_case 人工观测。"""
    cases = load_reasoning_prompt_cases(cases_file)
    observations = load_reasoning_prompt_observations(observations_file)
    case_ids = {case["case_id"] for case in cases}
    if set(observations) - case_ids:
        raise ValueError("reasoning prompt observations contain an unknown case_id")
    case_results: list[dict[str, Any]] = []
    for case in cases:
        rendered = REASONING_PROMPT_BUILDERS[case["prompt"]](**case["args"])
        missing_count = sum(marker not in rendered for marker in case["required_markers"])
        forbidden_count = sum(marker in rendered for marker in case["forbidden_markers"])
        passed = missing_count == 0 and forbidden_count == 0
        case_results.append({
            "case_id": case["case_id"],
            "prompt": case["prompt"],
            "real_case": case["real_case"],
            "passed": passed,
            "required_marker_count": len(case["required_markers"]),
            "missing_marker_count": missing_count,
            "forbidden_marker_hit_count": forbidden_count,
            "rendered_chars": len(rendered),
            "rendered_sha256": hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
        })

    static_passed = sum(row["passed"] for row in case_results)
    static_contract = {"status": "pass" if static_passed == len(case_results) else "fail", "total": len(case_results), "passed": static_passed, "failed": len(case_results) - static_passed, "cases": case_results}

    real_cases = {case["case_id"]: case for case in cases if case["real_case"]}
    observed_real = {case_id: observation for case_id, observation in observations.items() if case_id in real_cases}
    covered_prompts = {real_cases[case_id]["prompt"] for case_id in observed_real}
    required_prompts = set(REASONING_PROMPT_BUILDERS)
    if not real_cases or not observed_real:
        behavior_status = "real_case_missing"
    elif covered_prompts != required_prompts:
        behavior_status = "insufficient_real_cases"
    elif all(observation["passed"] for observation in observed_real.values()):
        behavior_status = "pass"
    else:
        behavior_status = "fail"
    real_behavior = {
        "status": behavior_status,
        "real_case_count": len(real_cases),
        "observed_case_count": len(observed_real),
        "covered_prompts": sorted(covered_prompts),
        "missing_prompts": sorted(required_prompts - covered_prompts),
        "passed_observations": sum(item["passed"] for item in observed_real.values()),
        "failed_observations": sum(not item["passed"] for item in observed_real.values()),
        "identity_assurance": "self_asserted" if observed_real else "none",
    }

    if static_contract["status"] == "fail" or behavior_status == "fail":
        overall_status = "fail"
    elif behavior_status == "pass":
        overall_status = "pass"
    elif behavior_status == "insufficient_real_cases":
        overall_status = "static_pass_real_cases_incomplete"
    else:
        overall_status = "static_pass_real_case_missing"
    return {
        "schema_version": 1,
        "evaluation_kind": "reasoning_prompt_acceptance",
        "overall_status": overall_status,
        "release_ready": overall_status == "pass",
        "static_contract": static_contract,
        "real_behavior": real_behavior,
        "limitations": [
            "静态合同评测只验证 Prompt 结构，不调用模型，也不证明真实任务效果。",
            "公开示例不得替代本地真实 case；真实观测只保存逻辑 case ID、布尔检查和证据引用计数。",
            "人工 reviewer 为调用方声明身份，identity_assurance=self_asserted。",
        ],
        "next_action": "为四类 Prompt 各准备至少一个本地 real_case，并用脱敏 evidence_refs 记录人工观测。" if behavior_status != "pass" else "四类 Prompt 已具备静态合同和本地真实观测，可继续观察后再决定是否扩展 delivery schema。",
    }
