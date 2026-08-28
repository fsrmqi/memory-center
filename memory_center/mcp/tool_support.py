"""MCP 工具注册共享的参数校验与响应整形辅助函数。"""
from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from memory_center.core.foundation.errors import InvalidInputError
from memory_center.core.observability.diagnostics import DIAG, diag_entry

_JAVA_CHAIN_SYMBOL_RE = re.compile(
    r"((?:[a-z_][\w$]*\.)+[A-Z][\w$]*(?:#[a-zA-Z_][\w$]*)?|(?<![a-z_])[A-Z][\w$]*\.[a-z_][\w$]*(?:#[a-zA-Z_][\w$]*)?|(?<![a-z_])[A-Z][\w$]*(?:#[a-zA-Z_][\w$]*)?)"
)
# Lowercase-starting camelCase method names (getXxx / setXxx / buildXxx / ...)
# are real symbols too. The class-name pattern above cannot match them, so a
# pure method query like `getClusterUniversalStateForAppMachine` used to fall
# back to an inner Capitalized fragment (the DTO name) and surface the wrong
# anchor. Match the whole verb-prefixed identifier instead.
_JAVA_CAMEL_METHOD_RE = re.compile(
    r"\b(?:get|set|is|has|build|create|query|find|submit|send|handle|run|do|apply|check|update|delete|save|parse|convert|to|from)[A-Z][A-Za-z0-9_]*"
)


def extract_symbol_like_token(*values: str) -> str:
    for raw in values:
        text = (raw or "").strip()
        if not text:
            continue
        matches = _JAVA_CHAIN_SYMBOL_RE.findall(text)
        if matches:
            matches.sort(key=len, reverse=True)
            return matches[0]
        # No class/chain fragment: a lowercase-starting camelCase method name
        # (e.g. getClusterUniversalStateForAppMachine). Prefer the longest
        # verb-prefixed identifier over nothing so symbol lookup hits the
        # Method node instead of an inner Capitalized fragment (a DTO).
        method_matches = _JAVA_CAMEL_METHOD_RE.findall(text)
        if method_matches:
            method_matches.sort(key=len, reverse=True)
            return method_matches[0]
    return ""


def wants_deep_chain(*values: str) -> bool:
    text = " ".join((value or "") for value in values).lower()
    return any(token in text for token in ["全链路", "到底层", "最底层", "一路到底", "full chain", "trace to sink"])


def validate_analyze_request(depth: str, direction: str, max_depth: int, execution_mode: str) -> None:
    if depth not in {"quick", "standard", "full"}:
        raise InvalidInputError("depth must be quick, standard, or full", suggested_action="使用 quick、standard 或 full 重试。")
    if direction not in {"upstream", "downstream", "both"}:
        raise InvalidInputError("direction must be upstream, downstream, or both", suggested_action="使用 upstream、downstream 或 both 重试。")
    if not 1 <= max_depth <= 6:
        raise InvalidInputError("max_depth must be between 1 and 6", suggested_action="将 max_depth 设置在 1 到 6 之间；更深分析请分阶段执行。")
    if execution_mode not in {"sync", "background"}:
        raise InvalidInputError("execution_mode must be sync or background", suggested_action="使用 sync 或 background 重试。")


def degraded_analysis_step(name: str, operation: Callable[[], Any]) -> tuple[Any | None, dict[str, Any] | None]:
    """Keep successful graph evidence usable when an optional phase fails."""
    try:
        return operation(), None
    except Exception as exc:  # Optional enrichments must not hide graph evidence.
        return None, diag_entry(
            DIAG.UNAVAILABLE,
            exc=exc,
            phase=name,
            next_action="保留已有影响证据；检查该阶段依赖后单独重试，或改用 depth=quick。",
        )


def flatten_walkthrough_payload(result: dict[str, Any], mode_key: str = "mode_used") -> dict[str, Any]:
    summary_lines = result.get("summary_lines", []) or []
    return {
        mode_key: "walkthrough",
        "found": result.get("found", False),
        "target": result.get("target", {}),
        "answer": "\n".join(summary_lines),
        "answer_markdown": result.get("answer_markdown", ""),
        "answer_template": result.get("answer_template", {}),
        "summary_lines": summary_lines,
        "primary_flow": summary_lines,
        "read_targets": collect_walkthrough_read_targets(result),
        "mermaid_flow": result.get("mermaid_flow", ""),
        "performance_risks": result.get("performance_risks", []),
        "data_scope_guards": result.get("data_scope_guards", []),
        "diff_context": result.get("diff_context", {}),
        "glossary_hits": result.get("glossary_hits", []),
        "schema_version": result.get("schema_version", 1),
        "fields_contract": result.get("fields_contract", {}),
        "index_freshness": result.get("index_freshness", {}),
        "completion_status": result.get("completion_status", {}),
        "branch_outline": result.get("branch_outline", []),
        "anti_patterns": result.get("anti_patterns", []),
        "cache": result.get("cache", {}),
        "agent_usage_policy": result.get("agent_usage_policy", {}),
        "next_actions": result.get("next_actions", []),
        "result": result,
    }


def collect_walkthrough_read_targets(result: dict[str, Any]) -> list[dict[str, Any]]:
    existing = result.get("read_targets", [])
    if isinstance(existing, list) and existing:
        return existing
    targets: list[dict[str, Any]] = []
    seen = set()

    def add(role: str, item: dict[str, Any], label: str = "") -> None:
        abs_path = item.get("absolute_file_path") or item.get("file_path")
        if not abs_path:
            return
        key = (role, abs_path, item.get("line", 0), label)
        if key in seen:
            return
        seen.add(key)
        targets.append({
            "role": role,
            "label": label or item.get("class") or item.get("controller") or item.get("method") or "",
            "absolute_file_path": abs_path,
            "line": item.get("line", 0),
            "project": item.get("project", ""),
        })

    target = result.get("target", {}) or {}
    add("target", target, f"{target.get('class', '')}#{target.get('method', '')}")
    for impl in result.get("local_service_continuations", []) or []:
        impl_target = impl.get("target", {}) or {}
        add("local_impl", impl_target, f"{impl_target.get('class', '')}#{impl_target.get('method', '')}")
        for same in impl.get("same_class_method_continuations", []) or []:
            same_target = same.get("target", {}) or {}
            add("local_impl_same_class", same_target, f"{same_target.get('class', '')}#{same_target.get('method', '')}")
    for same in result.get("same_class_method_continuations", []) or []:
        same_target = same.get("target", {}) or {}
        add("same_class", same_target, f"{same_target.get('class', '')}#{same_target.get('method', '')}")
    for feign in result.get("feign_continuations", []) or []:
        for server in (feign.get("server_walkthroughs", []) or [])[:1]:
            add("server_controller", server, f"{server.get('controller', '')}#{server.get('method', '')}")
            for impl in (server.get("service_impl_continuations", []) or [])[:1]:
                impl_target = impl.get("target", {}) or {}
                add("server_impl", impl_target, f"{impl_target.get('class', '')}#{impl_target.get('method', '')}")
                for same in impl.get("same_class_method_continuations", []) or []:
                    same_target = same.get("target", {}) or {}
                    add("server_impl_same_class", same_target, f"{same_target.get('class', '')}#{same_target.get('method', '')}")
    return targets
