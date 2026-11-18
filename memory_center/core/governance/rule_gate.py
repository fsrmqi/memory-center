"""规则门禁的执行入口 —— 加载规则、只评估 gate 规则、汇总违规。

供 CLI / CI 使用的薄编排层：把 ``core.governance.rules.load_rules_from_yaml``
与 ``core.governance.rule_checks.evaluate_gate_rules`` 串成一次可判定成败的运行。

设计要点：
- strict/lenient 由规则自身决定：``enforcement`` 不是 gate 的规则一律不参与判定，
  但仍会被计数回报，避免"规则写了却没生效"的静默。
- 规则文件加载失败属于配置错误，与"有违规"区分开，调用方可据此给出不同退出码。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from memory_center.core.governance.rule_checks import MAX_FINDINGS_DEFAULT, evaluate_gate_rules
from memory_center.core.governance.rules import load_rules_from_yaml


def expand_rule_paths(paths: list[str | Path]) -> list[Path]:
    """Expand directories into their ``*.yaml`` files; keep file paths as-is."""
    expanded: list[Path] = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            expanded.extend(sorted(path.glob("*.yaml")))
        else:
            expanded.append(path)
    return expanded


def run_gate(
    rules_paths: list[str | Path],
    source_root: str | Path,
    *,
    max_findings: int = MAX_FINDINGS_DEFAULT,
    rule_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Run gate rules against ``source_root``.

    Returns a summary dict; ``ok`` is False when any gate rule reports findings,
    when a rule's ``check`` is invalid, or when ``source_root`` does not exist.
    Raises ``ValueError`` when a rules file is missing or a rule definition is invalid.
    """
    files = expand_rule_paths(rules_paths)
    if not files:
        raise ValueError("未提供任何规则文件")
    missing = [str(path) for path in files if not path.is_file()]
    if missing:
        raise ValueError("规则文件不存在：" + "、".join(missing))

    rules = []
    for path in files:
        rules.extend(load_rules_from_yaml(path))
    if rule_ids:
        wanted = set(rule_ids)
        rules = [rule for rule in rules if rule.id in wanted]

    root = Path(source_root)
    if not root.is_dir():
        return {
            "ok": False,
            "rules_files": [str(path) for path in files],
            "source_root": str(root),
            "gate_rule_count": 0,
            "skipped_rule_count": 0,
            "violation_count": 0,
            "results": [],
            "errors": [f"source_root 不是目录：{root}"],
        }

    gate_rules = [rule for rule in rules if str(rule.enforcement).strip() == "gate"]
    results = evaluate_gate_rules(gate_rules, root, max_findings=max_findings)
    violations = sum(len(result.get("findings", [])) for result in results)
    errors = [
        f"{result['rule_id']}: {result['error']}"
        for result in results
        if result.get("error")
    ]
    return {
        "ok": violations == 0 and not errors,
        "rules_files": [str(path) for path in files],
        "source_root": str(root),
        "gate_rule_count": len(gate_rules),
        "skipped_rule_count": len(rules) - len(gate_rules),
        "violation_count": violations,
        "results": results,
        "errors": errors,
    }


def format_text(summary: dict[str, Any]) -> str:
    """Human-readable rendering, findings first, with each rule's repair steps."""
    lines: list[str] = []
    if summary.get("errors"):
        lines.append("规则门禁配置错误：")
        lines.extend(f"  - {item}" for item in summary["errors"])
        lines.append("")

    for result in summary.get("results", []):
        findings = result.get("findings", [])
        if not findings:
            continue
        lines.append(
            f"[{result['rule_id']}] {len(findings)} 处违规"
            f"（{result['kind']}，检查 {result['checked_files']} 个文件）"
        )
        for item in findings:
            lines.append(f"  - {item['path']}:{item['line']}  {item['message']}")
        steps = findings[0].get("repair_steps") or []
        if steps:
            lines.append("  修复步骤：")
            lines.extend(f"    {step}" for step in steps)
        if result.get("truncated"):
            lines.append("  ... 违规已截断，完整结果请用 --format json")
        lines.append("")

    lines.append(
        f"gate 规则 {summary['gate_rule_count']} 条，违规 {summary['violation_count']} 处，"
        f"跳过（非 gate）{summary['skipped_rule_count']} 条"
    )
    lines.append("结论：" + ("通过" if summary.get("ok") else "未通过"))
    return "\n".join(lines)


__all__ = ["expand_rule_paths", "run_gate", "format_text"]
