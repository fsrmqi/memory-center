from __future__ import annotations

from typing import Any

TREE_SITTER_INSTALL_HINT = 'pipx inject memory-center "tree-sitter>=0.22.0" "tree-sitter-java>=0.21.0"'
TREE_SITTER_VALIDATE_HINT = "memory-center eval-parser-benchmark --workspace <workspace.yaml>"


def parser_precision_from_diagnostics(diagnostics: dict[str, Any] | None) -> dict[str, Any]:
    """Summarize parser precision state for downstream retrieval/reasoning diagnostics."""
    diagnostics = dict(diagnostics or {})
    parse_count = int(diagnostics.get("parse_count", 0) or 0)
    fallback_count = int(diagnostics.get("fallback_count", 0) or 0)
    native_success_count = int(diagnostics.get("native_success_count", 0) or 0)
    tree_sitter_available = bool(diagnostics.get("tree_sitter_available", False))
    selected_parser = str(diagnostics.get("selected_parser", "") or "regex")
    fallback_rate = round(fallback_count / parse_count, 4) if parse_count else 0.0

    if not parse_count:
        status = "unknown"
        precision_risk = "unknown"
        recommended_action = "run_reindex"
    elif not tree_sitter_available and fallback_count >= parse_count:
        status = "regex_only"
        precision_risk = "medium"
        recommended_action = "install_tree_sitter_java_and_reindex"
    elif fallback_count > 0:
        status = "mixed_fallback"
        precision_risk = "low"
        recommended_action = "review_parser_fallback_reasons"
    elif tree_sitter_available and native_success_count > 0:
        status = "tree_sitter_active"
        precision_risk = "low"
        recommended_action = "use_current_parser_evidence"
    else:
        status = selected_parser
        precision_risk = "low"
        recommended_action = "use_current_parser_evidence"

    payload: dict[str, Any] = {
        "status": status,
        "selected_parser": selected_parser,
        "tree_sitter_available": tree_sitter_available,
        "parse_count": parse_count,
        "fallback_count": fallback_count,
        "fallback_rate": fallback_rate,
        "fallback_reasons": diagnostics.get("fallback_reasons", {}) or {},
        "critical_disagreement_count": int(diagnostics.get("critical_disagreement_count", 0) or 0),
        "precision_risk": precision_risk,
        "recommended_action": recommended_action,
    }
    if status == "regex_only":
        payload["install_hint"] = TREE_SITTER_INSTALL_HINT
        payload["validation_hint"] = TREE_SITTER_VALIDATE_HINT
    return payload


def parser_precision_from_graph_summary(summary: dict[str, Any] | None) -> dict[str, Any]:
    summary = dict(summary or {})
    diagnostics = summary.get("parser_diagnostics")
    if isinstance(diagnostics, dict):
        return parser_precision_from_diagnostics(diagnostics)
    return parser_precision_from_diagnostics({})


def parser_precision_from_workspace(workspace_file: str) -> dict[str, Any]:
    from .store import WorkspaceStore

    try:
        summary = WorkspaceStore(workspace_file).read_json_prefer_backend("graph-summary.json", {})
    except Exception as exc:
        return {
            "status": "unknown",
            "precision_risk": "unknown",
            "recommended_action": "run_reindex",
            "diagnostic_error": str(exc),
        }
    return parser_precision_from_graph_summary(summary)
