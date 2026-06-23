from __future__ import annotations

import json
import re
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Dict, List, Tuple

from ..config import load_workspace_config
from ..diagnostics import DIAG, diag_entry
from ..indexer import JAVA_EXTENSIONS, safe_read, walk_project
from ..workspace_shape import analyze_workspace_shape, collect_workspace_service_entries, select_primary_service_entry
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
    all_java_files, workspace_shape = _collect_workspace_java_files(config)
    java_files = _sample_java_files(all_java_files, limit=limit)
    service_coverage = _build_service_coverage(all_java_files, java_files)

    result: Dict[str, Any] = {
        "workspace": config.workspace,
        "files_scanned": len(java_files),
        "projects": sorted({project for project, _, _ in java_files}),
        "limit": limit,
        "workspace_shape": workspace_shape,
        "service_coverage": service_coverage,
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
            result["summary"]["regex_totals"][field] += _value_size(field, getattr(regex_result, field))

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
            regex_value = getattr(regex_result, field)
            tree_value = getattr(tree_result, field)
            result["summary"]["tree_sitter_totals"][field] += _value_size(field, tree_value)

            comparison = _compare_field_values(field, regex_value, tree_value)
            missing = comparison["missing"]
            extra = comparison["extra"]
            stat = result["summary"]["field_stats"][field]
            if missing:
                stat["lagging_files"] += 1
                if len(regressions) < max_findings:
                    regressions.append(
                        {
                            "project": project,
                            "file": logical_path,
                            "field": field,
                            "regex_count": comparison["regex_count"],
                            "tree_sitter_count": comparison["tree_sitter_count"],
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
                            "regex_count": comparison["regex_count"],
                            "tree_sitter_count": comparison["tree_sitter_count"],
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


def _collect_workspace_java_files(config: Any) -> Tuple[List[Tuple[str, str, Path]], Dict[str, Any]]:
    service_entries = collect_workspace_service_entries(config)
    workspace_shape = analyze_workspace_shape(config)
    unique_roots: Dict[str, Path] = {}
    for entry in service_entries:
        unique_roots.setdefault(entry.root_text, entry.root)

    file_records: List[Tuple[str, str, Path]] = []
    seen_files: set[str] = set()
    for root_text, root_path in unique_roots.items():
        for path in walk_project(root_path):
            if path.suffix not in JAVA_EXTENSIONS:
                continue
            abs_path = str(path.resolve())
            if abs_path in seen_files:
                continue
            seen_files.add(abs_path)
            primary = select_primary_service_entry(path, service_entries)
            if primary is None:
                continue
            logical_path = config.service_logical_file_path(primary.service, path)
            file_records.append((primary.name, logical_path, path))
    return file_records, workspace_shape


def _sample_java_files(
    records: List[Tuple[str, str, Path]],
    *,
    limit: int,
) -> List[Tuple[str, str, Path]]:
    if limit <= 0 or limit >= len(records):
        return records

    buckets: Dict[str, deque[Tuple[str, str, Path]]] = defaultdict(deque)
    order: List[str] = []
    seen_projects: set[str] = set()
    for record in records:
        project = record[0]
        buckets[project].append(record)
        if project not in seen_projects:
            seen_projects.add(project)
            order.append(project)

    sampled: List[Tuple[str, str, Path]] = []
    while len(sampled) < limit:
        progressed = False
        for project in order:
            bucket = buckets[project]
            if not bucket:
                continue
            sampled.append(bucket.popleft())
            progressed = True
            if len(sampled) >= limit:
                break
        if not progressed:
            break
    return sampled


def _build_service_coverage(
    all_records: List[Tuple[str, str, Path]],
    sampled_records: List[Tuple[str, str, Path]],
) -> Dict[str, Any]:
    total_counts: Dict[str, int] = defaultdict(int)
    sampled_counts: Dict[str, int] = defaultdict(int)
    for project, _, _ in all_records:
        total_counts[project] += 1
    for project, _, _ in sampled_records:
        sampled_counts[project] += 1
    return {
        "total_services_with_java": len(total_counts),
        "sampled_services": sorted(sampled_counts),
        "sampled_service_count": len(sampled_counts),
        "total_file_counts": dict(sorted(total_counts.items())),
        "sampled_file_counts": dict(sorted(sampled_counts.items())),
    }


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


def _value_size(field: str, value: Any) -> int:
    if field == "field_types" and isinstance(value, dict):
        return len(value)
    return len(_normalize_value(value))


def _compare_field_values(field: str, regex_value: Any, tree_value: Any) -> Dict[str, Any]:
    if field == "field_types":
        return _compare_field_types(regex_value, tree_value)

    regex_norm = _normalize_value(regex_value)
    tree_norm = _normalize_value(tree_value)
    return {
        "regex_count": len(regex_norm),
        "tree_sitter_count": len(tree_norm),
        "missing": sorted(regex_norm - tree_norm),
        "extra": sorted(tree_norm - regex_norm),
    }


def _compare_field_types(regex_value: Any, tree_value: Any) -> Dict[str, Any]:
    regex_types = _coerce_str_dict(regex_value)
    tree_types = _coerce_str_dict(tree_value)
    regex_keys = set(regex_types)
    tree_keys = set(tree_types)

    missing = [f"{key}:{regex_types[key]}" for key in sorted(regex_keys - tree_keys)]
    extra = [f"{key}:{tree_types[key]}" for key in sorted(tree_keys - regex_keys)]

    for key in sorted(regex_keys & tree_keys):
        regex_type = regex_types[key]
        tree_type = tree_types[key]
        if _field_type_covers(tree_type, regex_type, field_name=key):
            continue
        if _field_type_covers(regex_type, tree_type, field_name=key):
            missing.append(f"{key}:{regex_type}")
            continue
        missing.append(f"{key}:{regex_type}")
        extra.append(f"{key}:{tree_type}")

    return {
        "regex_count": len(regex_types),
        "tree_sitter_count": len(tree_types),
        "missing": missing,
        "extra": extra,
    }


def _coerce_str_dict(value: Any) -> Dict[str, str]:
    if not isinstance(value, dict):
        return {}
    result: Dict[str, str] = {}
    for key, raw in value.items():
        key_text = str(key or "").strip()
        if not key_text:
            continue
        result[key_text] = str(raw or "").strip()
    return result


def _field_type_covers(candidate: str, baseline: str, *, field_name: str = "") -> bool:
    candidate_norm = _normalize_type_text(candidate)
    baseline_norm = _normalize_type_text(baseline)
    if not baseline_norm:
        return True
    if not candidate_norm:
        return False
    if candidate_norm == baseline_norm:
        return True

    candidate_sig = _type_signature(candidate_norm)
    baseline_sig = _type_signature(baseline_norm)
    if candidate_sig == baseline_sig:
        return True
    if _type_family(candidate_sig) == _type_family(baseline_sig) and _type_family(candidate_sig):
        return True
    if candidate_sig.endswith(baseline_sig):
        return True
    if _type_family(candidate_sig) == "string" and not _looks_like_java_type_name(baseline):
        return True
    if _looks_like_constant_name(field_name) and _type_family(candidate_sig) == "string":
        return True

    baseline_literal_type = _literal_type_name(baseline)
    if baseline_literal_type:
        baseline_literal_sig = _type_signature(baseline_literal_type)
        if candidate_sig == baseline_literal_sig:
            return True
        if _type_family(candidate_sig) == _type_family(baseline_literal_sig) and _type_family(candidate_sig):
            return True

    return False


def _normalize_type_text(value: str) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def _type_signature(value: str) -> str:
    compact = _normalize_type_text(value)
    compact = re.sub(r"\b(?:[A-Za-z_]\w*\.)+([A-Za-z_]\w*)", r"\1", compact)
    return compact


def _type_family(value: str) -> str:
    families = {
        "byte": "integer",
        "Byte": "integer",
        "short": "integer",
        "Short": "integer",
        "int": "integer",
        "Integer": "integer",
        "long": "integer",
        "Long": "integer",
        "float": "decimal",
        "Float": "decimal",
        "double": "decimal",
        "Double": "decimal",
        "boolean": "boolean",
        "Boolean": "boolean",
        "char": "char",
        "Character": "char",
        "String": "string",
    }
    return families.get(value, value)


def _literal_type_name(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw.lower() in {"true", "false"}:
        return "Boolean"
    if re.fullmatch(r"[+-]?\d+[lL]?", raw):
        return "Long" if raw.endswith(("L", "l")) else "Integer"
    if re.fullmatch(r"[+-]?\d+\.\d+[fFdD]?", raw):
        return "Double"
    if raw.startswith('"') and raw.endswith('"'):
        return "String"
    if _looks_like_java_type_name(raw):
        return ""
    return "String"


def _looks_like_java_type_name(raw: str) -> bool:
    if raw.upper() == raw and any(ch.isalpha() for ch in raw):
        return False
    primitives = {
        "byte", "short", "int", "long", "float", "double", "boolean", "char", "void",
        "Byte", "Short", "Integer", "Long", "Float", "Double", "Boolean", "Character",
        "String", "Object", "List", "Set", "Map",
    }
    if raw in primitives:
        return True
    normalized = _normalize_type_text(raw)
    if re.fullmatch(r"(?:[A-Za-z_]\w*\.)*[A-Z][A-Za-z0-9_]*(?:<.*>)?", normalized):
        return True
    return False


def _looks_like_constant_name(raw: str) -> bool:
    text = str(raw or "").strip()
    return bool(text) and text.upper() == text and any(ch.isalpha() for ch in text)


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
