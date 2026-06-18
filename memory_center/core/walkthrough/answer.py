"""Answer rendering, template loading, summary lines, and compact view helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import yaml

__all__ = [
    "method_walkthrough_fields_contract",
    "method_walkthrough_template_context",
    "render_method_walkthrough_answer",
    "load_method_walkthrough_template",
    "default_method_walkthrough_template",
    "normalize_report_level",
    "build_method_walkthrough_agent_policy",
    "build_method_walkthrough_anti_patterns",
    "select_compact_method_steps",
    "build_method_walkthrough_summary_lines",
    "compact_method_walkthrough_result",
    "method_walkthrough_read_targets_text",
    "method_walkthrough_rule_groups_text",
    "format_rule_group_lines",
    "build_glossary_hits",
    "load_walkthrough_glossary",
    "collect_walkthrough_terms",
    "format_glossary_hits",
    "format_risk_items",
    "format_diff_context",
    "format_index_freshness",
    "format_branch_outline",
    "format_anti_patterns",
    "display_method_path",
]


METHOD_WALKTHROUGH_SCHEMA_VERSION = 2


def method_walkthrough_fields_contract() -> Dict[str, Any]:
    return {
        "stable_top_level": [
            "schema_version",
            "fields_contract",
            "found",
            "target",
            "summary_lines",
            "answer_markdown",
            "read_targets",
            "agent_usage_policy",
            "next_actions",
        ],
        "enhancement_fields": [
            "mermaid_flow",
            "performance_risks",
            "data_scope_guards",
            "diff_context",
            "glossary_hits",
            "index_freshness",
            "branch_outline",
            "anti_patterns",
            "cache",
            "_reasoning",
        ],
        "compatibility": "additive_fields_only",
    }


def normalize_report_level(report_level: str) -> str:
    value = (report_level or "standard").strip().lower()
    return value if value in {"brief", "standard", "deep", "risk-focused", "code-review"} else "standard"


def build_method_walkthrough_agent_policy() -> Dict[str, Any]:
    return {
        "primary_path": "summary_lines -> local_service_continuations -> same_class_method_continuations -> feign_continuations.server_walkthroughs -> service_impl_continuations",
        "read_files_by": "absolute_file_path",
        "do_not_search_when_absolute_path_present": True,
        "do_not_sed_when_continuation_present": True,
        "avoid_tools": ["find", "grep -l", "rg --files", "IDEA search", "sed -n"],
        "reason": "walkthrough 已给出 controller/service impl/同类辅助方法的已索引落点、absolute_file_path 和字段摘要；重复搜索或 sed 切片会增加延迟并可能被同名类误导。",
    }


def build_method_walkthrough_anti_patterns() -> List[Dict[str, str]]:
    return [
        {
            "avoid": "parse_tool_results_json",
            "reason": "walkthrough 已把 answer_markdown、summary_lines、read_targets 等提升到顶层，解析本地 tool-results 会变慢且容易卡住。",
        },
        {
            "avoid": "repo_wide_find_before_read_targets",
            "reason": "存在 absolute_file_path 时应直接读文件；全仓库 find/grep 会被同名类和多模块干扰。",
        },
        {
            "avoid": "large_sed_ranges_for_known_continuations",
            "reason": "same_class_method_continuations 和 branch_outline 已给出方法级摘要，只有核对具体分支时才需要 live read。",
        },
        {
            "avoid": "ignore_index_freshness",
            "reason": "index_freshness.index_stale=true 时必须优先读实时文件或 reindex，否则链路可能落后于代码。",
        },
    ]


def display_method_path(item: Dict[str, Any]) -> str:
    return str(item.get("absolute_file_path") or item.get("file_path") or "")


def select_compact_method_steps(local_steps: List[Dict[str, Any]], limits: Dict[str, int]) -> List[Dict[str, Any]]:
    max_items = max(4, limits["steps"] + limits["events"])
    priority = {"feign_call": 0, "method_call": 1, "dto_field_read": 2}
    selected: List[Dict[str, Any]] = []
    seen = set()
    for step in sorted(local_steps or [], key=lambda row: (priority.get(row.get("kind", ""), 9), int(row.get("line", 0) or 0))):
        key = (step.get("kind"), step.get("line"), step.get("receiver"), step.get("method"), step.get("field"))
        if key in seen:
            continue
        seen.add(key)
        selected.append(step)
        if len(selected) >= max_items:
            break
    selected.sort(key=lambda row: (int(row.get("line", 0) or 0), priority.get(row.get("kind", ""), 9)))
    return selected


def build_method_walkthrough_summary_lines(
    target: Dict[str, Any],
    local_steps: List[Dict[str, Any]],
    local_service_continuations: List[Dict[str, Any]],
    same_class_continuations: List[Dict[str, Any]],
    feigns: List[Dict[str, Any]],
    downstream: Dict[str, Any],
    limits: Dict[str, int],
) -> List[str]:
    lines = [
        f"Target {target.get('project', '')}:{target.get('class', '')}#{target.get('method', '')} ({display_method_path(target)}:{target.get('line', 0)})"
    ]
    for step in select_compact_method_steps(local_steps or [], limits)[: limits["steps"] + limits["events"]]:
        lines.append(f"Step line {step.get('line', 0)}: {step.get('summary', '')}")
    for impl in (local_service_continuations or [])[: limits["events"]]:
        target_impl = impl.get("target", {}) or {}
        lines.append(
            f"LocalImpl {target_impl.get('project', '')}:{target_impl.get('class', '')}#{target_impl.get('method', '')} ({display_method_path(target_impl)}:{target_impl.get('line', 0)})"
        )
        for nested in (impl.get("feign_continuations", []) or [])[:1]:
            lines.append(
                f"LocalImplFeign {nested.get('interface', '')}.{nested.get('method', '')} -> {nested.get('http_method', '')} {nested.get('path', '')} endpoints={len(nested.get('matched_endpoints', []) or [])}"
            )
    for same in (same_class_continuations or [])[: limits["events"]]:
        same_target = same.get("target", {}) or {}
        field_summary = same.get("field_filter_summary", {}) or {}
        lines.append(
            f"SameClass {same_target.get('project', '')}:{same_target.get('class', '')}#{same_target.get('method', '')} ({display_method_path(same_target)}:{same_target.get('line', 0)}) fields={field_summary.get('unique_dto_field_count', 0)}"
        )
    for item in feigns[: limits["events"]]:
        endpoint_count = len(item.get("matched_endpoints", []) or [])
        lines.append(
            f"Feign {item.get('interface', '')}.{item.get('method', '')} -> {item.get('http_method', '')} {item.get('path', '')} endpoints={endpoint_count}"
        )
        for server in (item.get("server_walkthroughs", []) or [])[:1]:
            lines.append(
                f"Server {server.get('project', '')}:{server.get('controller', '')}#{server.get('method', '')} ({display_method_path(server)}:{server.get('line', 0)})"
            )
            for impl in (server.get("service_impl_continuations", []) or [])[:1]:
                target = impl.get("target", {}) or {}
                lines.append(
                    f"Impl {target.get('project', '')}:{target.get('class', '')}#{target.get('method', '')} ({display_method_path(target)}:{target.get('line', 0)})"
                )
                for same in (impl.get("same_class_method_continuations", []) or [])[:1]:
                    same_target = same.get("target", {}) or {}
                    field_summary = same.get("field_filter_summary", {}) or {}
                    lines.append(
                        f"ImplSameClass {same_target.get('project', '')}:{same_target.get('class', '')}#{same_target.get('method', '')} ({display_method_path(same_target)}:{same_target.get('line', 0)}) fields={field_summary.get('unique_dto_field_count', 0)}"
                    )
    if downstream.get("total_edges", 0):
        lines.append(f"Downstream edges={downstream.get('total_edges', 0)} depth={downstream.get('depth_reached', 0)}")
    return lines


def compact_method_walkthrough_result(result: Dict[str, Any], budget: str = "medium", *, cache_ttl_seconds: int = 15) -> Dict[str, Any]:
    from ..orchestrator.common import _budget_limits
    from ..reasoning.integration import compact_reasoning_view

    limits = _budget_limits(budget)
    target = result.get("target", {}) or {}
    feigns = result.get("feign_continuations", []) or []
    local_service_continuations = result.get("local_service_continuations", []) or []
    same_class_continuations = result.get("same_class_method_continuations", []) or []
    downstream = result.get("downstream_summary", {}) or {}
    return {
        "workspace": result.get("workspace", ""),
        "symbol": result.get("symbol", ""),
        "found": result.get("found", False),
        "schema_version": result.get("schema_version", METHOD_WALKTHROUGH_SCHEMA_VERSION),
        "fields_contract": result.get("fields_contract", method_walkthrough_fields_contract()),
        "target": target,
        "evidence_level": result.get("evidence_level", ""),
        "local_steps": select_compact_method_steps(result.get("local_steps", []) or [], limits),
        "local_service_continuations": local_service_continuations[: limits["steps"]],
        "same_class_method_continuations": same_class_continuations[: limits["steps"]],
        "feign_continuations": feigns[: limits["steps"]],
        "downstream_summary": {
            "items": (downstream.get("items", []) or [])[: limits["steps"] + limits["events"]],
            "total_edges": downstream.get("total_edges", 0),
            "depth_reached": downstream.get("depth_reached", 0),
            "type_counts": downstream.get("type_counts", {}),
        },
        "summary_lines": build_method_walkthrough_summary_lines(target, result.get("local_steps", []), local_service_continuations, same_class_continuations, feigns, downstream, limits),
        "answer_markdown": result.get("answer_markdown", ""),
        "answer_template": result.get("answer_template", {}),
        "mermaid_flow": result.get("mermaid_flow", ""),
        "performance_risks": result.get("performance_risks", [])[: limits["events"]],
        "data_scope_guards": result.get("data_scope_guards", []),
        "diff_context": result.get("diff_context", {}),
        "glossary_hits": result.get("glossary_hits", [])[: limits["events"]],
        "index_freshness": result.get("index_freshness", {}),
        "branch_outline": result.get("branch_outline", [])[: limits["steps"]],
        "anti_patterns": result.get("anti_patterns", []),
        "cache": result.get("cache", {"hit": False, "ttl_seconds": cache_ttl_seconds}),
        "workspace_escalation": result.get("workspace_escalation", {}),
        "agent_usage_policy": result.get("agent_usage_policy", build_method_walkthrough_agent_policy()),
        "next_actions": (result.get("next_actions", []) or [])[:3],
        "limitations": result.get("limitations", [])[:2],
        "_reasoning": compact_reasoning_view(result.get("_reasoning", {}), limit=2),
    }


def load_method_walkthrough_template(workspace_file: str | Path) -> Dict[str, str]:
    ws_dir = Path(workspace_file).expanduser().resolve().parent
    candidates = [
        ws_dir / "templates" / "method_walkthrough.md",
        ws_dir / "method_walkthrough_template.md",
    ]
    for candidate in candidates:
        if candidate.exists():
            try:
                return {
                    "status": "configured",
                    "path": str(candidate),
                    "template": candidate.read_text(encoding="utf-8"),
                }
            except OSError as exc:
                return {"status": "fallback_builtin", "path": str(candidate), "reason": str(exc), "template": ""}
    return {"status": "fallback_builtin", "path": "", "template": ""}


def default_method_walkthrough_template(report_level: str = "standard") -> str:
    level = normalize_report_level(report_level)
    if level == "brief":
        return (
            "## {target_label} 全链路梳理\n\n"
            "### 主线\n{summary_lines}\n\n"
            "### 风险\n{performance_risks}\n"
        )
    if level == "risk-focused":
        return (
            "## {target_label} 风险导向链路梳理\n\n"
            "### 主线\n{summary_lines}\n\n"
            "### 性能风险\n{performance_risks}\n\n"
            "### 数据范围保护\n{data_scope_guards}\n\n"
            "### Diff 命中\n{diff_context}\n"
            "### 索引新鲜度\n{index_freshness}\n"
        )
    if level == "deep":
        return (
            "## {target_label} 全链路深度梳理\n\n"
            "### 调用链主线\n{summary_lines}\n\n"
            "### Mermaid\n```mermaid\n{mermaid_flow}\n```\n\n"
            "### 建议直接阅读的文件\n{read_targets}\n\n"
            "### 大方法规则分组\n{rule_groups}\n\n"
            "### 业务词汇\n{glossary}\n\n"
            "### 性能风险\n{performance_risks}\n\n"
            "### 数据范围保护\n{data_scope_guards}\n\n"
            "### Diff 命中\n{diff_context}\n\n"
            "### 索引新鲜度\n{index_freshness}\n\n"
            "### 分支轮廓\n{branch_outline}\n\n"
            "### Agent 反模式\n{anti_patterns}\n\n"
            "### 下一步\n{next_actions}\n"
        )
    return (
        "## {target_label} 全链路梳理\n\n"
        "### 调用链主线\n{summary_lines}\n\n"
        "### Mermaid\n```mermaid\n{mermaid_flow}\n```\n\n"
        "### 建议直接阅读的文件\n{read_targets}\n\n"
        "### 大方法规则分组\n{rule_groups}\n\n"
        "### 性能风险\n{performance_risks}\n\n"
        "### 数据范围保护\n{data_scope_guards}\n\n"
        "### 索引新鲜度\n{index_freshness}\n\n"
        "### 分支轮廓\n{branch_outline}\n\n"
        "### 下一步\n{next_actions}\n"
    )


def method_walkthrough_read_targets_text(result: Dict[str, Any]) -> str:
    targets: List[str] = []

    def add(role: str, item: Dict[str, Any], label: str) -> None:
        path = display_method_path(item)
        if path:
            targets.append(f"- {role}: {label} ({path}:{item.get('line', 0)})")

    target = result.get("target", {}) or {}
    add("target", target, f"{target.get('class', '')}#{target.get('method', '')}")
    for impl in result.get("local_service_continuations", []) or []:
        impl_target = impl.get("target", {}) or {}
        add("local_impl", impl_target, f"{impl_target.get('class', '')}#{impl_target.get('method', '')}")
    for feign in result.get("feign_continuations", []) or []:
        for server in (feign.get("server_walkthroughs", []) or [])[:1]:
            add("server_controller", server, f"{server.get('controller', '')}#{server.get('method', '')}")
            for impl in (server.get("service_impl_continuations", []) or [])[:1]:
                impl_target = impl.get("target", {}) or {}
                add("server_impl", impl_target, f"{impl_target.get('class', '')}#{impl_target.get('method', '')}")
                for same in impl.get("same_class_method_continuations", []) or []:
                    same_target = same.get("target", {}) or {}
                    add("server_impl_same_class", same_target, f"{same_target.get('class', '')}#{same_target.get('method', '')}")
    return "\n".join(targets)


def format_rule_group_lines(continuation: Dict[str, Any]) -> List[str]:
    target = continuation.get("target", {}) or {}
    out = [f"- {target.get('class', '')}#{target.get('method', '')}:"]
    for group in continuation.get("rule_groups", []) or []:
        fields = ", ".join(group.get("fields", [])[:12])
        out.append(f"  - {group.get('group', '')}: {fields}")
    return out


def method_walkthrough_rule_groups_text(result: Dict[str, Any]) -> str:
    lines: List[str] = []
    for same in result.get("same_class_method_continuations", []) or []:
        lines.extend(format_rule_group_lines(same))
    for feign in result.get("feign_continuations", []) or []:
        for server in feign.get("server_walkthroughs", []) or []:
            for impl in server.get("service_impl_continuations", []) or []:
                for same in impl.get("same_class_method_continuations", []) or []:
                    lines.extend(format_rule_group_lines(same))
    return "\n".join(lines) if lines else "- 未识别到大方法规则分组。"


def load_walkthrough_glossary(workspace_file: str | Path) -> Dict[str, Any]:
    ws_dir = Path(workspace_file).expanduser().resolve().parent
    for path in [ws_dir / "glossary.yaml", ws_dir / "glossary.yml", ws_dir / "business-glossary.yaml"]:
        if not path.exists():
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            return {}
        if isinstance(data, dict) and "terms" in data and isinstance(data["terms"], dict):
            return data["terms"]
        if isinstance(data, dict):
            return data
    return {}


def collect_walkthrough_terms(result: Dict[str, Any]) -> set[str]:
    terms: set[str] = set()
    for step in result.get("local_steps", []) or []:
        for key in ["receiver", "receiver_type", "method", "field"]:
            if step.get(key):
                terms.add(str(step[key]))
    for usage in result.get("dto_field_usages", []) or []:
        if usage.get("field"):
            terms.add(str(usage["field"]))
    for same in result.get("same_class_method_continuations", []) or []:
        terms.update((same.get("field_filter_summary", {}) or {}).get("unique_dto_fields", []) or [])
    for feign in result.get("feign_continuations", []) or []:
        for server in feign.get("server_walkthroughs", []) or []:
            for impl in server.get("service_impl_continuations", []) or []:
                for same in impl.get("same_class_method_continuations", []) or []:
                    terms.update((same.get("field_filter_summary", {}) or {}).get("unique_dto_fields", []) or [])
    return terms


def build_glossary_hits(workspace_file: str | Path, result: Dict[str, Any]) -> List[Dict[str, Any]]:
    glossary = load_walkthrough_glossary(workspace_file)
    if not glossary:
        return []
    terms = collect_walkthrough_terms(result)
    hits = []
    for term in sorted(terms):
        entry = glossary.get(term) or glossary.get(term.lower())
        if not entry:
            continue
        if isinstance(entry, dict):
            description = str(entry.get("description") or entry.get("desc") or entry.get("meaning") or "")
            category = str(entry.get("category") or "")
        else:
            description = str(entry)
            category = ""
        hits.append({"term": term, "description": description, "category": category})
    return hits


def format_glossary_hits(items: List[Dict[str, Any]]) -> str:
    if not items:
        return "- 未配置或未命中 glossary。"
    return "\n".join(f"- {item.get('term', '')}: {item.get('description', '')}" for item in items[:30])


def format_risk_items(items: List[Dict[str, Any]]) -> str:
    if not items:
        return "- 未识别到明确风险。"
    return "\n".join(f"- [{item.get('severity', item.get('status', 'info'))}] {item.get('code', '')}: {item.get('message', '')}" for item in items)


def format_diff_context(diff: Dict[str, Any]) -> str:
    if not diff.get("enabled"):
        return "- 当前 git workspace 没有检测到改动，或不在 git 仓库内。"
    if not diff.get("has_touched_read_targets"):
        return f"- 当前有 {diff.get('changed_file_count', 0)} 个改动文件，但未命中本 walkthrough 主线。"
    return "\n".join(f"- 命中改动: {path}" for path in diff.get("touched_read_targets", []) or [])


def format_index_freshness(freshness: Dict[str, Any]) -> str:
    if not freshness:
        return "- 未检测索引新鲜度。"
    if not freshness.get("index_stale"):
        return "- 索引未发现比主链路文件更旧的情况。"
    return "\n".join(f"- 索引可能过期: {item.get('absolute_file_path', '')}" for item in freshness.get("stale_read_targets", []) or [])


def format_branch_outline(outlines: List[Dict[str, Any]]) -> str:
    if not outlines:
        return "- 未识别到可结构化的分支轮廓。"
    lines: List[str] = []
    for outline in outlines[:12]:
        target = outline.get("target", {}) or {}
        lines.append(f"- {outline.get('source', '')}: {target.get('class', '')}#{target.get('method', '')}")
        for group in outline.get("groups", []) or []:
            fields = ", ".join(group.get("fields", [])[:12])
            lines.append(f"  - {group.get('group', '')} ({group.get('field_count', 0)}): {fields}")
        if outline.get("cases"):
            lines.append(f"  - cases: {', '.join(outline.get('cases', [])[:20])}")
    return "\n".join(lines)


def format_anti_patterns(items: List[Dict[str, Any]]) -> str:
    if not items:
        return "- 无额外反模式提示。"
    return "\n".join(f"- {item.get('avoid', '')}: {item.get('reason', '')}" for item in items)


def method_walkthrough_template_context(result: Dict[str, Any], report_level: str = "standard") -> Dict[str, str]:
    target = result.get("target", {}) or {}
    summary_lines = result.get("summary_lines") or build_method_walkthrough_summary_lines(
        target,
        result.get("local_steps", []) or [],
        result.get("local_service_continuations", []) or [],
        result.get("same_class_method_continuations", []) or [],
        result.get("feign_continuations", []) or [],
        result.get("downstream_summary", {}) or {},
        {"steps": 4, "events": 4},
    )
    read_targets = method_walkthrough_read_targets_text(result)
    rule_groups = method_walkthrough_rule_groups_text(result)
    return {
        "report_level": normalize_report_level(report_level),
        "workspace": str(result.get("workspace", "")),
        "workspace_file": str(result.get("workspace_file", "")),
        "symbol": str(result.get("symbol", "")),
        "target_label": f"{target.get('project', '')}:{target.get('class', '')}#{target.get('method', '')}",
        "target_file": display_method_path(target),
        "target_line": str(target.get("line", 0)),
        "summary_lines": "\n".join(f"- {line}" for line in summary_lines),
        "read_targets": read_targets,
        "rule_groups": rule_groups,
        "glossary": format_glossary_hits(result.get("glossary_hits", []) or []),
        "performance_risks": format_risk_items(result.get("performance_risks", []) or []),
        "data_scope_guards": format_risk_items(result.get("data_scope_guards", []) or []),
        "diff_context": format_diff_context(result.get("diff_context", {}) or {}),
        "index_freshness": format_index_freshness(result.get("index_freshness", {}) or {}),
        "branch_outline": format_branch_outline(result.get("branch_outline", []) or []),
        "anti_patterns": format_anti_patterns(result.get("anti_patterns", []) or []),
        "mermaid_flow": result.get("mermaid_flow", ""),
        "next_actions": "\n".join(f"- {line}" for line in result.get("next_actions", []) or []),
    }


def render_method_walkthrough_answer(result: Dict[str, Any], workspace_file: str | Path, report_level: str = "standard") -> str:
    template_info = load_method_walkthrough_template(workspace_file)
    context = method_walkthrough_template_context(result, report_level=report_level)
    template = template_info.get("template", "") or default_method_walkthrough_template(report_level)
    try:
        rendered = template.format(**context)
    except Exception:
        rendered = default_method_walkthrough_template(report_level).format(**context)
        template_info = {"status": "fallback_builtin", "path": "", "reason": "template_render_failed"}
    result["answer_template"] = template_info
    return rendered.strip()
