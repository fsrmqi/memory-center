"""Optional, bounded adapter for the external ``skill-up`` evaluator.

Memory Center owns Skill identity, evidence and publication gates.  This
module only prepares and invokes the external evaluator through a fixed argv
contract, so it never becomes a query-path dependency or arbitrary shell API.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any
from uuid import uuid4

from memory_center.core.storage.workspace import WorkspaceStore

from .delivery import _read_skill_registry, _registry_skill, _skill_slug

_ENGINES = {"codex", "claude_code", "qodercli", "qwen_code"}
_TIMEOUT_SECONDS = 900
_ENVIRONMENT_FAILURE_MARKERS = (
    "authentication",
    "authorization",
    "connection refused",
    "dns",
    "network",
    "mcp",
    "rate limit",
    "timed out",
    "timeout",
    "token expired",
)


def skill_up_status() -> dict[str, Any]:
    binary = shutil.which("skill-up")
    if not binary:
        return {
            "available": False,
            "binary": "",
            "next_action": "安装 skill-up 后再运行 delivery-skill-eval-init 或 delivery-skill-eval-run。",
        }
    try:
        version = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=3, check=False)
        detail = (version.stdout or version.stderr).strip()[:300]
    except (OSError, subprocess.TimeoutExpired):
        detail = "unknown"
    return {
        "available": True,
        "binary": binary,
        "version": detail,
        "next_action": "先生成评测骨架，再由维护者补充脱敏的 cases/*.yaml。",
    }


def initialize_skill_up_eval(workspace_file: str | Path, *, skill_id: str, engine: str = "codex") -> dict[str, Any]:
    """Create an editable external-evaluation skeleton for one published Skill."""
    normalized_engine = engine.strip().lower()
    if normalized_engine not in _ENGINES:
        raise ValueError(f"unsupported engine: {engine}")
    store = WorkspaceStore(workspace_file)
    skill = _registry_skill(_read_skill_registry(store), skill_id)
    if not skill or skill.get("lifecycle") != "published" or not skill.get("published_path"):
        return {
            "initialized": False,
            "reason": "published_skill_required",
            "next_action": "仅对已发布 Skill 初始化外部评测；先完成 candidate、canary 与发布门禁。",
        }
    root = store.artifacts_dir / "skills" / "delivery-evals" / _skill_slug(skill_id)
    cases = root / "cases"
    cases.mkdir(parents=True, exist_ok=True)
    config = root / "eval.yaml"
    if not config.exists():
        config.write_text(
            "\n".join(
                [
                    "schema_version: v1alpha1",
                    "environment:",
                    "  type: none",
                    "skills:",
                    "  - source: local_path",
                    f"    path: {Path(str(skill['published_path'])).parent.as_posix()}",
                    "engine:",
                    f"  name: {normalized_engine}",
                    "cases:",
                    "  files: []",
                    "  parallelism: 1",
                    "report:",
                    "  formats: [json, junit, html]",
                    "",
                ]
            ),
            encoding="utf-8",
        )
    guide = cases / "README.md"
    if not guide.exists():
        guide.write_text(
            "# Skill-up 用例\n\n仅放入脱敏的 fixture、prompt 与确定性期望。每个 Skill 至少保留 3 到 5 个 case，并断言可观察行为，不要要求某个固定措辞。将 case YAML 路径显式加入 `../eval.yaml` 的 `cases.files`；不要写入私有源码、密钥或真实会话正文。\n",
            encoding="utf-8",
        )
    policy = root / "evaluation-policy.json"
    if not policy.exists():
        policy.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "baseline_mode": "disabled_until_isolated",
                    "minimum_cases": 3,
                    "comparison_status": "not_comparable",
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    return {
        "initialized": True,
        "skill_id": skill_id,
        "eval_config": str(config),
        "cases_dir": str(cases),
        "evaluation_policy": str(policy),
        "skill_up": skill_up_status(),
        "next_action": "补充 3 到 5 个脱敏用例后先执行 delivery-skill-eval-run --dry-run，确认 argv 与输出目录，再追加 --apply。",
    }


def run_skill_up_eval(workspace_file: str | Path, *, skill_id: str, apply: bool = False) -> dict[str, Any]:
    """Run fixed skill-up validate/run commands; no user-provided shell is accepted."""
    store = WorkspaceStore(workspace_file)
    root = store.artifacts_dir / "skills" / "delivery-evals" / _skill_slug(skill_id)
    config = root / "eval.yaml"
    if not config.exists():
        return {
            "executed": False,
            "reason": "eval_config_not_found",
            "next_action": "先执行 delivery-skill-eval-init。",
        }
    status = skill_up_status()
    if not status["available"]:
        return {"executed": False, "reason": "skill_up_unavailable", **status}
    output = root / "runs" / uuid4().hex[:12]
    validate_argv = [str(status["binary"]), "validate", str(config)]
    run_argv = [
        str(status["binary"]),
        "run",
        str(config),
        "--output-dir",
        str(output),
        "--format",
        "junit",
        "--format",
        "html",
    ]
    preview = {
        "executed": False,
        "apply": apply,
        "validate_argv": validate_argv,
        "run_argv": run_argv,
        "output_dir": str(output),
    }
    if not apply:
        return {**preview, "next_action": "确认配置和用例后追加 --apply；外部评测不会自动发布或修改 Skill。"}
    try:
        validation = subprocess.run(validate_argv, cwd=root, capture_output=True, text=True, timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            **preview,
            "executed": True,
            "passed": False,
            "classification": "environment_error",
            "phase": "validate",
            "output": str(exc)[:4000],
            "next_action": "检查 skill-up 二进制、网络、认证和 MCP 环境后重试；该结果不计入 Skill 失败率。",
        }
    if validation.returncode != 0:
        output_text = (validation.stdout + validation.stderr)[-4000:]
        classification = _classify_external_failure("validate", output_text)
        return {
            **preview,
            "executed": True,
            "passed": False,
            "classification": classification,
            "phase": "validate",
            "exit_code": validation.returncode,
            "output": output_text,
            "next_action": _classification_next_action(classification),
        }
    try:
        completed = subprocess.run(
            run_argv, cwd=root, capture_output=True, text=True, timeout=_TIMEOUT_SECONDS, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            **preview,
            "executed": True,
            "passed": False,
            "classification": "environment_error",
            "phase": "run",
            "output": str(exc)[:4000],
            "next_action": "检查运行环境后重试；超时或宿主故障不计入 Skill 失败率。",
        }
    result_path = output / "result.json"
    summary: dict[str, Any] = {}
    if result_path.exists():
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
            summary = dict(result.get("summary") or result.get("run_summary") or {})
        except (OSError, json.JSONDecodeError):
            summary = {"parse_status": "unavailable"}
    output_text = (completed.stdout + completed.stderr)[-4000:]
    classification = "pass" if completed.returncode == 0 else _classify_external_failure("run", output_text)
    receipt = {
        "skill_id": skill_id,
        "engine": "skill-up",
        "status": classification,
        "exit_code": completed.returncode,
        "result_path": str(result_path),
        "summary": summary,
        "comparison_status": "not_comparable",
    }
    log = root / "runs.jsonl"
    with log.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(receipt, ensure_ascii=False) + "\n")
    return {
        **preview,
        "executed": True,
        "passed": completed.returncode == 0,
        "classification": classification,
        "exit_code": completed.returncode,
        "receipt": receipt,
        "output": output_text,
        "next_action": _classification_next_action(classification),
    }


def _classify_external_failure(phase: str, output: str) -> str:
    lowered = output.lower()
    if any(marker in lowered for marker in _ENVIRONMENT_FAILURE_MARKERS):
        return "environment_error"
    return "evaluation_failure" if phase == "validate" else "skill_failure"


def _classification_next_action(classification: str) -> str:
    return {
        "pass": "将通过结果作为外部评测证据记录到 canary 观测；它不会自动满足发布门禁。",
        "environment_error": "检查 skill-up、网络、认证和 MCP 环境后重试；该结果不计入 Skill 失败率。",
        "evaluation_failure": "修复评测配置或用例断言后重试；不要将该结果归因为 Skill 能力失败。",
        "skill_failure": "复核失败 case 的可观察断言并修订 Skill；保留脱敏结果作为回归证据。",
    }[classification]
