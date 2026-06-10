from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from ..config import load_workspace_config
from ..diagnostics import DIAG, diag_entry
from ..indexer import JAVA_EXTENSIONS, safe_read, walk_project
from .base import JavaParseResult
from .java_regex_parser import RegexJavaParser
from .tree_sitter_parser import TreeSitterJavaParser

_COMPARE_FIELDS: Tuple[str, ...] = (
    "package",
    "imports",
    "classes",
    "interfaces",
    "methods",
    "fields",
    "annotations",
    "field_types",
    "bean_injections",
    "method_calls",
    "dto_field_usages",
    "config_usages",
    "data_resources",
)

_CORE_FIELDS = {"package", "imports", "classes", "interfaces", "methods", "fields", "annotations"}


def benchmark_java_parsers(
    workspace_file: str | Path,
    *,
    limit: int = 200,
    max_findings: int = 20,
) -> Dict[str, Any]:
    """Compare regex and tree-sitter Java parsers on a real workspace."""
    config = load_workspace_config(workspace_file)
    regex_parser = RegexJavaParser()
    tree_parser = TreeSitterJavaParser()
    java_files = list(_collect_java_files(config, limit=limit))

    result: Dict[str, Any] = {
        "workspace": config.workspace,
        "files_scanned": len(java_files),
        "projects": sorted({project for project, _, _ in java_files}),
        "limit": limit,
        "parser_selection": {
            "regex": regex_parser.name,
            "tree_sitter": tree_parser.name,
        },
        "tree_sitter": diag_entry(
            DIAG.ACTIVE if tree_parser.available else DIAG.UNAVAILABLE,
            reason="ready" if tree_parser.available else "tree-sitter parser unavailable",
        ),
        "summary": {
            "regex_totals": {field: 0 for field in _COMPARE_FIELDS},
            "tree_sitter_totals": {field: 0 for field in _COMPARE_FIELDS},
            "field_stats": {
                field: {"equal_files": 0, "lagging_files": 0, "leading_files": 0}
                for field in _COMPARE_FIELDS
            },
        },
        "regressions": [],
        "improvements": [],
        "score": 0,
        "quality": "unknown",
        "recommendations": [],
    }

    if not java_files:
        result["tree_sitter"] = diag_entry(DIAG.EMPTY, reason="no java files found in workspace")
        result["recommendations"] = ["当前 workspace 没有可比较的 Java 文件。"]
        return result

    baseline_rows: List[Tuple[str, str, JavaParseResult, str]] = []
    for project, logical_path, path in java_files:
        text = safe_read(path)
        regex_result = regex_parser.parse(text, logical_path)
        baseline_rows.append((project, logical_path, regex_result, text))
        for field in _COMPARE_FIELDS:
            regex_norm = _normalize_value(getattr(regex_result, field))
            result["summary"]["regex_totals"][field] += len(regex_norm)

    if not tree_parser.available:
        result["recommendations"] = [
            "安装 tree-sitter Java 依赖后重新运行 parser benchmark，以验证真实 workspace 精度。",
        ]
        return result

    regressions: List[Dict[str, Any]] = []
    improvements: List[Dict[str, Any]] = []

    for project, logical_path, regex_result, text in baseline_rows:
        tree_result = tree_parser.parse(text, logical_path)
        for field in _COMPARE_FIELDS:
            regex_norm = _normalize_value(getattr(regex_result, field))
            tree_norm = _normalize_value(getattr(tree_result, field))

            result["summary"]["tree_sitter_totals"][field] += len(tree_norm)

            missing = sorted(regex_norm - tree_norm)
            extra = sorted(tree_norm - regex_norm)
            stat = result["summary"]["field_stats"][field]
            if missing:
                stat["lagging_files"] += 1
                if len(regressions) < max_findings:
                    regressions.append(
                        {
                            "project": project,
                            "file": logical_path,
                            "field": field,
                            "regex_count": len(regex_norm),
                            "tree_sitter_count": len(tree_norm),
                            "missing_examples": missing[:5],
                        }
                    )
            elif extra:
                stat["leading_files"] += 1
                if len(improvements) < max_findings:
                    improvements.append(
                        {
                            "project": project,
                            "file": logical_path,
                            "field": field,
                            "regex_count": len(regex_norm),
                            "tree_sitter_count": len(tree_norm),
                            "extra_examples": extra[:5],
                        }
                    )
            else:
                stat["equal_files"] += 1

    result["regressions"] = regressions
    result["improvements"] = improvements
    result["score"] = _score_parser_quality(result["summary"]["field_stats"])
    result["quality"] = _score_to_quality(result["score"])
    result["recommendations"] = _build_recommendations(
        result["summary"]["field_stats"],
        result["score"],
        bool(regressions),
    )
    return result


def _collect_java_files(config: Any, *, limit: int) -> Iterable[Tuple[str, str, Path]]:
    seen = 0
    for svc in config.services:
        service_root = config.resolve_service_path(svc)
        if not service_root.exists():
            continue
        for path in walk_project(service_root):
            if path.suffix not in JAVA_EXTENSIONS:
                continue
            logical_path = config.service_logical_file_path(svc, path)
            yield svc.name, logical_path, path
            seen += 1
            if limit > 0 and seen >= limit:
                return


def _normalize_value(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return {value} if value else set()
    if isinstance(value, dict):
        return {json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)}
    if isinstance(value, list):
        normalized = set()
        for item in value:
            if isinstance(item, dict):
                normalized.add(json.dumps(item, sort_keys=True, ensure_ascii=False, default=str))
            elif item is not None and item != "":
                normalized.add(str(item))
        return normalized
    return {str(value)}


def _score_parser_quality(field_stats: Dict[str, Dict[str, int]]) -> int:
    penalty = 0
    for field, stats in field_stats.items():
        lagging = int(stats.get("lagging_files", 0))
        if field in _CORE_FIELDS:
            penalty += lagging * 10
        else:
            penalty += lagging * 4
    return max(0, 100 - penalty)


def _score_to_quality(score: int) -> str:
    if score >= 85:
        return "high"
    if score >= 60:
        return "medium"
    return "low"


def _build_recommendations(
    field_stats: Dict[str, Dict[str, int]],
    score: int,
    has_regression: bool,
) -> List[str]:
    recommendations: List[str] = []
    if not has_regression:
        recommendations.append("tree-sitter 与 regex 基线没有发现丢失项，可以继续扩大真实 workspace 验证范围。")
    else:
        ranked = sorted(
            ((field, stats.get("lagging_files", 0)) for field, stats in field_stats.items()),
            key=lambda item: item[1],
            reverse=True,
        )
        top_field, top_count = ranked[0]
        if top_count > 0:
            recommendations.append(f"优先检查 `{top_field}`，当前有 {top_count} 个文件出现 tree-sitter 落后于 regex 的情况。")
    if score < 85:
        recommendations.append("在默认启用 tree-sitter 之前，建议先对回归字段补专门 fixture 和真实仓库样本。")
    else:
        recommendations.append("可以开始在中大型 Spring Cloud workspace 上采样运行，并观察噪声与解析耗时。")
    return recommendations
