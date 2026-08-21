from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from memory_center.cli.main import app
from memory_center.core.benchmark.reasoning_prompts import (
    BUILTIN_REASONING_PROMPT_CASES,
    evaluate_reasoning_prompts,
    load_reasoning_prompt_observations,
)


def test_builtin_reasoning_prompt_smoke_is_static_only() -> None:
    report = evaluate_reasoning_prompts()

    assert report["static_contract"]["status"] == "pass"
    assert report["static_contract"]["total"] == 4
    assert report["real_behavior"]["status"] == "real_case_missing"
    assert report["overall_status"] == "static_pass_real_case_missing"
    assert report["release_ready"] is False
    assert all("args" not in row for row in report["static_contract"]["cases"])


def test_public_template_cannot_satisfy_real_case_gate() -> None:
    report = evaluate_reasoning_prompts("examples/reasoning-prompt-eval/cases.template.yaml")

    assert report["static_contract"]["status"] == "pass"
    assert report["real_behavior"]["real_case_count"] == 0
    assert report["real_behavior"]["status"] == "real_case_missing"
    assert report["release_ready"] is False


def test_local_real_cases_and_redacted_observations_can_complete_report(tmp_path: Path) -> None:
    cases_file = tmp_path / "cases.yaml"
    cases = [{**case, "real_case": True} for case in BUILTIN_REASONING_PROMPT_CASES]
    cases_file.write_text(yaml.safe_dump({"schema_version": 1, "cases": cases}, sort_keys=False), encoding="utf-8")

    secret_reviewer = "private-reviewer-name"
    secret_ref = "session:private-reference"
    observations_file = tmp_path / "observations.yaml"
    observations_file.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "observations": [
                    {
                        "case_id": case["case_id"],
                        "reviewer": secret_reviewer,
                        "evidence_refs": [secret_ref],
                        "checks": {
                            "bounded_interaction": True,
                            "evidence_used": True,
                            "epistemic_boundary_respected": True,
                            "actionable_output": True,
                        },
                    }
                    for case in cases
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    report = evaluate_reasoning_prompts(cases_file, observations_file)
    serialized = json.dumps(report, ensure_ascii=False)

    assert report["overall_status"] == "pass"
    assert report["release_ready"] is True
    assert report["real_behavior"]["observed_case_count"] == 4
    assert report["real_behavior"]["identity_assurance"] == "self_asserted"
    assert secret_reviewer not in serialized
    assert secret_ref not in serialized


def test_static_contract_failure_does_not_echo_private_marker(tmp_path: Path) -> None:
    private_marker = "private-company-only-marker"
    cases_file = tmp_path / "cases.yaml"
    case = {**BUILTIN_REASONING_PROMPT_CASES[0], "required_markers": [private_marker], "real_case": True}
    cases_file.write_text(yaml.safe_dump({"schema_version": 1, "cases": [case]}, sort_keys=False), encoding="utf-8")

    report = evaluate_reasoning_prompts(cases_file)

    assert report["overall_status"] == "fail"
    assert report["static_contract"]["cases"][0]["missing_marker_count"] == 1
    assert private_marker not in json.dumps(report)


def test_observations_require_evidence_and_all_boolean_checks(tmp_path: Path) -> None:
    observations_file = tmp_path / "observations.yaml"
    observations_file.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "observations": [
                    {
                        "case_id": "local-case",
                        "reviewer": "reviewer",
                        "evidence_refs": [],
                        "checks": {},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="evidence_refs"):
        load_reasoning_prompt_observations(observations_file)


def test_observation_for_unknown_case_is_rejected(tmp_path: Path) -> None:
    observations_file = tmp_path / "observations.yaml"
    observations_file.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "observations": [
                    {
                        "case_id": "unknown-local-case",
                        "reviewer": "reviewer",
                        "evidence_refs": ["session:redacted"],
                        "checks": {
                            "bounded_interaction": True,
                            "evidence_used": True,
                            "epistemic_boundary_respected": True,
                            "actionable_output": True,
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unknown case_id"):
        evaluate_reasoning_prompts(observations_file=observations_file)


def test_eval_reasoning_prompts_cli_outputs_unified_report() -> None:
    result = CliRunner().invoke(app, ["eval-reasoning-prompts"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["evaluation_kind"] == "reasoning_prompt_acceptance"
    assert payload["static_contract"]["status"] == "pass"
    assert payload["real_behavior"]["status"] == "real_case_missing"
