from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .base import JavaParseResult
from .java_regex_parser import RegexJavaParser
from .tree_sitter_parser import TreeSitterJavaParser

_ENTITY_FIELDS = (
    "classes",
    "interfaces",
    "method_signatures",
    "fields",
    "bean_injections",
    "method_calls",
)


def compare_parsers(source_file: str | Path) -> dict[str, Any]:
    """Compare regex, native AST, and merged tree-sitter parser facts."""
    path = Path(source_file)
    text = path.read_text(encoding="utf-8")
    regex_result = RegexJavaParser().parse(text, path.name)
    tree_parser = TreeSitterJavaParser()
    native_result = tree_parser.parse_native(text, path.name)
    final_result = tree_parser.parse(text, path.name)

    if native_result is None:
        return {
            "file": path.name,
            "tree_sitter_available": False,
            "missing_in_tree_sitter": [],
            "critical_disagreements": [],
            "native_gaps": [],
            "method_identities": [],
            "metrics": {"entity_recall": 0.0, "max_line_delta": 0},
        }

    missing = _missing_entities(regex_result, final_result)
    native_gaps = _missing_entities(regex_result, native_result)
    regex_controllers, regex_feigns = _spring_mappings(regex_result, text, path.name)
    final_controllers, final_feigns = _spring_mappings(final_result, text, path.name)
    mapping_disagreements = _mapping_disagreements(
        regex_controllers,
        final_controllers,
        regex_feigns,
        final_feigns,
    )
    method_identities, line_disagreements, max_line_delta = _method_identity_report(
        regex_result, final_result
    )
    critical = [*missing, *line_disagreements, *mapping_disagreements]
    expected_count = sum(len(_entity_keys(getattr(regex_result, field))) for field in _ENTITY_FIELDS)
    missing_count = len(missing)
    recall = 1.0 if expected_count == 0 else max(0.0, (expected_count - missing_count) / expected_count)
    return {
        "file": path.name,
        "tree_sitter_available": True,
        "missing_in_tree_sitter": missing,
        "critical_disagreements": critical,
        "native_gaps": native_gaps,
        "method_identities": method_identities,
        "controller_mappings": final_controllers,
        "feign_mappings": final_feigns,
        "metrics": {
            "entity_recall": round(recall, 4),
            "max_line_delta": max_line_delta,
        },
    }


def compare_parser_corpus(corpus_dir: str | Path) -> dict[str, Any]:
    reports = [compare_parsers(path) for path in sorted(Path(corpus_dir).glob("*.java"))]
    available = [report for report in reports if report["tree_sitter_available"]]
    critical = [item for report in available for item in report["critical_disagreements"]]
    recalls = [float(report["metrics"]["entity_recall"]) for report in available]
    return {
        "files": reports,
        "file_count": len(reports),
        "critical_disagreements": critical,
        "entity_recall": round(sum(recalls) / len(recalls), 4) if recalls else 0.0,
        "max_line_delta": max(
            (int(report["metrics"]["max_line_delta"]) for report in available),
            default=0,
        ),
    }


def _missing_entities(expected: JavaParseResult, actual: JavaParseResult) -> list[dict[str, str]]:
    missing: list[dict[str, str]] = []
    for field in _ENTITY_FIELDS:
        expected_keys = _entity_keys(getattr(expected, field))
        actual_keys = _entity_keys(getattr(actual, field))
        for identity in sorted(expected_keys - actual_keys):
            missing.append({"field": field, "identity": identity})
    return missing


def _entity_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return {f"{key}={value[key]}" for key in sorted(value)}
    if not isinstance(value, list):
        return {str(value)} if value not in (None, "") else set()
    keys = set()
    for item in value:
        if isinstance(item, dict):
            identity = item.get("identity")
            if identity:
                keys.add(str(identity))
            else:
                keys.add(json.dumps(item, sort_keys=True, ensure_ascii=False, default=str))
        elif item not in (None, ""):
            keys.add(str(item))
    return keys


def _method_identity_report(
    expected: JavaParseResult,
    actual: JavaParseResult,
) -> tuple[list[dict[str, Any]], list[dict[str, str]], int]:
    expected_by_id = {
        str(item.get("identity", "")): item
        for item in expected.method_signatures
        if item.get("identity")
    }
    actual_by_id = {
        str(item.get("identity", "")): item
        for item in actual.method_signatures
        if item.get("identity")
    }
    rows: list[dict[str, Any]] = []
    disagreements: list[dict[str, str]] = []
    max_delta = 0
    for identity in sorted(set(expected_by_id) | set(actual_by_id)):
        expected_line = int(expected_by_id.get(identity, {}).get("line", 0) or 0)
        actual_line = int(actual_by_id.get(identity, {}).get("line", 0) or 0)
        delta = abs(expected_line - actual_line) if expected_line and actual_line else 0
        max_delta = max(max_delta, delta)
        rows.append(
            {
                "identity": identity,
                "regex_line": expected_line,
                "tree_sitter_line": actual_line,
                "line_delta": delta,
            }
        )
        if delta > 1:
            disagreements.append(
                {"field": "method_lines", "identity": identity, "reason": f"line_delta={delta}"}
            )
    return rows, disagreements, max_delta


def _spring_mappings(
    parsed: JavaParseResult,
    text: str,
    file_name: str,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    from memory_center.core.foundation.models import JavaSymbol
    from memory_center.core.indexing.reindex import parse_controllers, parse_feign_clients

    symbol = JavaSymbol(
        project="parser-corpus",
        file=file_name,
        package=parsed.package,
        classes=list(parsed.classes),
        interfaces=list(parsed.interfaces),
        methods=list(parsed.methods),
        fields=list(parsed.fields),
        annotations=list(parsed.annotations),
        imports=list(parsed.imports),
        constants=dict(parsed.constants),
    )
    controllers = sorted(
        (
            {
                "controller": endpoint.controller,
                "method_name": str(endpoint.method_name or ""),
                "http_method": endpoint.http_method,
                "path": endpoint.path,
            }
            for endpoint in parse_controllers("parser-corpus", file_name, text, symbol)
        ),
        key=lambda item: (item["path"], item["http_method"], item["method_name"]),
    )
    feigns = []
    for client in parse_feign_clients("parser-corpus", file_name, text, symbol, {}):
        for method in client.methods:
            feigns.append(
                {
                    "interface": client.interface,
                    "method_name": str(method.get("method_name", "")),
                    "http_method": str(method.get("http_method", "")),
                    "path": str(method.get("path", "")),
                }
            )
    feigns.sort(key=lambda item: (item["path"], item["http_method"], item["method_name"]))
    return controllers, feigns


def _mapping_disagreements(
    expected_controllers: list[dict[str, str]],
    actual_controllers: list[dict[str, str]],
    expected_feigns: list[dict[str, str]],
    actual_feigns: list[dict[str, str]],
) -> list[dict[str, str]]:
    disagreements = []
    for field, expected, actual in (
        ("controller_mappings", expected_controllers, actual_controllers),
        ("feign_mappings", expected_feigns, actual_feigns),
    ):
        expected_keys = {json.dumps(item, sort_keys=True) for item in expected}
        actual_keys = {json.dumps(item, sort_keys=True) for item in actual}
        for identity in sorted(expected_keys - actual_keys):
            disagreements.append({"field": field, "identity": identity})
    return disagreements
