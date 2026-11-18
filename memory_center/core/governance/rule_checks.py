"""规则的可执行判据 —— 把 ``Rule.check`` 从描述变成可评估的约束。

设计参考 ARCH-CHECK 的做法：规则不只写在文档里，而是带一条可机检的判据；
违规信息必须自带修复步骤（``Rule.repair_steps``），否则 AI 拿到报错仍然不知道
下一步做什么。

支持三类 ``check.kind``，全部为纯 AST 静态分析，不导入也不执行被检查代码：

- ``forbidden_import``：``path_prefix`` 下的模块不得导入 ``forbidden_prefixes``。
- ``max_lines``：单个文件的物理行数上限。
- ``max_params``：单个函数签名的参数个数上限。

边界：本模块只做静态检查，不写文件、不执行子进程、不修改被检查仓库。
"""
from __future__ import annotations

import ast
from importlib.util import resolve_name
from pathlib import Path
from typing import Any

from memory_center.core.foundation.models import Rule

CHECK_KINDS = ("forbidden_import", "max_lines", "max_params")
MAX_FINDINGS_DEFAULT = 50


def supported_check_kinds() -> tuple[str, ...]:
    """Locally evaluable check kinds, in stable order."""
    return CHECK_KINDS


def normalize_repair_steps(steps: Any) -> list[str]:
    """Flatten ``repair_steps`` into a list of strings.

    YAML 里写 ``- Step 1: 先定位导入点`` 不会得到字符串，而是单键映射
    ``{"Step 1": "先定位导入点"}``。要求作者给每行加引号既反直觉又容易漏，
    因此在加载时统一拍平成 ``"Step 1: 先定位导入点"``。
    """
    normalized: list[str] = []
    if not isinstance(steps, list):
        return normalized
    for item in steps:
        if isinstance(item, str):
            text = item.strip()
        elif isinstance(item, dict) and len(item) == 1:
            key, value = next(iter(item.items()))
            text = f"{key}: {value}".strip()
        else:
            text = ""
        if text:
            normalized.append(text)
    return normalized


def validate_check(check: dict[str, Any]) -> list[str]:
    """Return human-readable problems with a ``Rule.check`` payload."""
    problems: list[str] = []
    kind = str(check.get("kind") or "").strip()
    if not kind:
        return ["check.kind 不能为空，可选值：" + "、".join(CHECK_KINDS)]
    if kind not in CHECK_KINDS:
        return [f"check.kind={kind!r} 不受支持，可选值：" + "、".join(CHECK_KINDS)]
    config = check.get("config")
    if config is not None and not isinstance(config, dict):
        problems.append("check.config 必须是对象（mapping）")
        return problems
    config = config or {}
    if kind == "forbidden_import":
        forbidden = config.get("forbidden_prefixes")
        if not isinstance(forbidden, list) or not forbidden:
            problems.append("forbidden_import 需要非空 config.forbidden_prefixes 列表")
    elif kind in ("max_lines", "max_params"):
        limit = config.get("max")
        if not isinstance(limit, int) or limit <= 0:
            problems.append(f"{kind} 需要正整数 config.max")
    return problems


def _iter_python_files(root: Path, path_prefix: str) -> list[Path]:
    base = root / path_prefix if path_prefix else root
    if not base.exists():
        return []
    return [
        path
        for path in sorted(base.rglob("*.py"))
        if "__pycache__" not in path.parts and path.is_file()
    ]


def _module_name(root: Path, path: Path) -> tuple[str, bool]:
    """Repo-relative module path and whether the file is a package __init__."""
    rel = path.relative_to(root).with_suffix("")
    parts = list(rel.parts)
    is_package = parts[-1] == "__init__"
    if is_package:
        parts = parts[:-1]
    return ".".join(parts), is_package


def _imported_targets(tree: ast.AST, module: str, is_package: bool) -> list[tuple[int, str]]:
    """All intra-project import targets with their line numbers."""
    package = module if is_package else module.rsplit(".", 1)[0]
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                try:
                    base = resolve_name("." * node.level + (node.module or ""), package)
                except (ImportError, ValueError):
                    continue
            else:
                base = node.module or ""
            if base:
                found.append((node.lineno, base))
    return found


def _check_forbidden_import(root: Path, config: dict[str, Any]) -> tuple[int, list[dict[str, Any]]]:
    forbidden = [str(item) for item in config.get("forbidden_prefixes", []) if str(item)]
    files = _iter_python_files(root, str(config.get("path_prefix") or ""))
    findings: list[dict[str, Any]] = []
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError):  # 目标仓库里的坏文件不应让门禁崩掉
            continue
        module, is_package = _module_name(root, path)
        for lineno, target in _imported_targets(tree, module, is_package):
            if any(target == prefix or target.startswith(prefix + ".") for prefix in forbidden):
                findings.append(
                    {
                        "path": str(path.relative_to(root)),
                        "line": lineno,
                        "message": f"禁止导入 {target}（命中规则 forbidden_prefixes）",
                    }
                )
    return len(files), findings


def _check_max_lines(root: Path, config: dict[str, Any]) -> tuple[int, list[dict[str, Any]]]:
    limit = int(config.get("max", 0) or 0)
    files = _iter_python_files(root, str(config.get("path_prefix") or ""))
    findings = []
    for path in files:
        try:
            lines = len(path.read_text(encoding="utf-8").splitlines())
        except OSError:
            continue
        if limit and lines > limit:
            findings.append(
                {
                    "path": str(path.relative_to(root)),
                    "line": 0,
                    "message": f"文件 {lines} 行，超过上限 {limit} 行",
                }
            )
    return len(files), findings


def _check_max_params(root: Path, config: dict[str, Any]) -> tuple[int, list[dict[str, Any]]]:
    limit = int(config.get("max", 0) or 0)
    files = _iter_python_files(root, str(config.get("path_prefix") or ""))
    findings: list[dict[str, Any]] = []
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            params = list(node.args.posonlyargs) + list(node.args.args) + list(node.args.kwonlyargs)
            if node.args.vararg:
                params.append(node.args.vararg)
            if node.args.kwarg:
                params.append(node.args.kwarg)
            # 方法签名的 self/cls 不计入业务参数。
            if params and params[0].arg in ("self", "cls"):
                params = params[1:]
            if limit and len(params) > limit:
                findings.append(
                    {
                        "path": str(path.relative_to(root)),
                        "line": node.lineno,
                        "message": f"函数 {node.name} 有 {len(params)} 个参数，超过上限 {limit}",
                    }
                )
    return len(files), findings


_CHECKERS = {
    "forbidden_import": _check_forbidden_import,
    "max_lines": _check_max_lines,
    "max_params": _check_max_params,
}


def run_check(rule: Rule, source_root: str | Path, *, max_findings: int = MAX_FINDINGS_DEFAULT) -> dict[str, Any]:
    """Evaluate one rule's ``check`` against ``source_root``.

    Returns ``{"rule_id", "kind", "checked_files", "findings", "truncated"}``;
    every finding carries the rule's ``repair_steps`` so the caller can surface
    an actionable message without re-reading the rule.
    """
    root = Path(source_root)
    check = dict(rule.check or {})
    kind = str(check.get("kind") or "").strip()
    problems = validate_check(check)
    if problems:
        return {
            "rule_id": rule.id,
            "kind": kind,
            "checked_files": 0,
            "findings": [],
            "truncated": False,
            "error": "; ".join(problems),
        }
    config = dict(check.get("config") or {})
    checked_files, findings = _CHECKERS[kind](root, config)
    truncated = len(findings) > max_findings
    steps = normalize_repair_steps(rule.repair_steps) or normalize_repair_steps(rule.checklist)
    limited = findings[:max_findings]
    for item in limited:
        item["repair_steps"] = steps
    return {
        "rule_id": rule.id,
        "kind": kind,
        "checked_files": checked_files,
        "findings": limited,
        "truncated": truncated,
    }


def evaluate_gate_rules(
    rules: list[Rule],
    source_root: str | Path,
    *,
    max_findings: int = MAX_FINDINGS_DEFAULT,
) -> list[dict[str, Any]]:
    """Evaluate only ``enforcement == "gate"`` rules; advisory rules are context only."""
    return [
        run_check(rule, source_root, max_findings=max_findings)
        for rule in rules
        if str(rule.enforcement or "advisory").strip() == "gate"
    ]


__all__ = [
    "CHECK_KINDS",
    "MAX_FINDINGS_DEFAULT",
    "supported_check_kinds",
    "normalize_repair_steps",
    "validate_check",
    "run_check",
    "evaluate_gate_rules",
]
