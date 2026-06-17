"""Risk, scope, freshness, diff and outline helpers for walkthrough results.

These helpers operate on already-built walkthrough dicts (target / continuations /
local steps).  They do not load the workspace store or graph store, so they can be
unit-tested by passing in plain dictionaries.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List

from .symbols import (
    extract_java_case_labels,
    extract_java_method_body_from_path,
)

__all__ = [
    "build_walkthrough_performance_risks",
    "build_data_scope_guards",
    "build_walkthrough_diff_context",
    "build_walkthrough_index_freshness",
    "build_walkthrough_branch_outline",
    "build_method_walkthrough_mermaid",
    "collect_result_abs_paths",
    "git_changed_abs_paths",
    "dedupe_risk_items",
]


def _steps_to_calls(steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    calls = []
    for step in steps:
        if step.get("kind") == "method_call":
            calls.append({
                "receiver": step.get("receiver", ""),
                "receiver_type": step.get("receiver_type", ""),
                "method": step.get("method", ""),
                "line": step.get("line", 0),
            })
    return calls


def dedupe_risk_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen = set()
    for item in items:
        key = (item.get("code"), json.dumps(item.get("evidence", {}), sort_keys=True, ensure_ascii=False))
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def build_walkthrough_performance_risks(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    risks: List[Dict[str, Any]] = []

    def add(severity: str, code: str, message: str, evidence: Dict[str, Any]) -> None:
        risks.append({"severity": severity, "code": code, "message": message, "evidence": evidence})

    all_calls = list(result.get("method_calls", []) or [])
    for same in result.get("same_class_method_continuations", []) or []:
        all_calls.extend(_steps_to_calls(same.get("local_steps", []) or []))
    for feign in result.get("feign_continuations", []) or []:
        for server in feign.get("server_walkthroughs", []) or []:
            for impl in server.get("service_impl_continuations", []) or []:
                all_calls.extend(_steps_to_calls(impl.get("local_steps", []) or []))
                for same in impl.get("same_class_method_continuations", []) or []:
                    all_calls.extend(_steps_to_calls(same.get("local_steps", []) or []))
                    field_count = (same.get("field_filter_summary", {}) or {}).get("unique_dto_field_count", 0)
                    if field_count and field_count >= 30:
                        add("medium", "many_optional_filters", f"辅助方法 {same.get('method', '')} 涉及 {field_count} 个 DTO 过滤字段，ES 查询组合复杂。", same.get("target", {}))

    for call in all_calls:
        method = str(call.get("method_name") or call.get("method") or "")
        receiver = " ".join(str(call.get(key) or "") for key in ["receiver", "receiver_type"])
        line = int(call.get("line", 0) or 0)
        if method == "scriptQuery":
            add("high", "es_script_query", "检测到 Elasticsearch scriptQuery，通常是分页查询热点风险。", {"receiver": receiver, "line": line})
        elif method == "wildcardQuery":
            add("medium", "es_wildcard_query", "检测到 wildcardQuery，前缀通配或包含查询可能影响索引命中。", {"receiver": receiver, "line": line})
        elif method == "queryStringQuery":
            add("medium", "es_query_string_wildcard", "检测到 queryStringQuery，若拼接 *xxx* 会扩大扫描范围。", {"receiver": receiver, "line": line})
        elif method == "setTrackTotalHits":
            add("low", "track_total_hits", "检测到 trackTotalHits(true)，总数精确统计会增加查询成本。", {"receiver": receiver, "line": line})
        elif method == "search" and "Elasticsearch" in receiver:
            add("info", "es_search", "核心落点是 Elasticsearch 查询，需关注分页、排序和过滤条件组合。", {"receiver": receiver, "line": line})
    return dedupe_risk_items(risks)


def build_data_scope_guards(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    guards: List[Dict[str, Any]] = []
    target_path = (result.get("target", {}) or {}).get("absolute_file_path", "")
    target_method = (result.get("target", {}) or {}).get("method", "")
    body = extract_java_method_body_from_path(target_path, target_method)
    text = body or ""

    def guard(status: str, code: str, message: str, evidence: Dict[str, Any]) -> None:
        guards.append({"status": status, "code": code, "message": message, "evidence": evidence})

    guard(
        "present" if "getCustomInfo" in text else "unknown",
        "custom_info_enrichment",
        "入口是否先通过 CommonService 获取保护单位信息。",
        {"method": target_method, "file": target_path},
    )
    guard(
        "present" if "setCustCode(null)" in text.replace(" ", "") else "unknown",
        "cust_code_cleared",
        "入口是否清空外部传入 custCode，避免调用方指定越权客户。",
        {"method": target_method, "file": target_path},
    )
    guard(
        "present" if "SecurityConstants.FROM_IN" in text else "unknown",
        "internal_feign_header",
        "Feign 调用是否携带内部来源标记。",
        {"method": target_method, "file": target_path},
    )
    protected_fields = set()
    for feign in result.get("feign_continuations", []) or []:
        for server in feign.get("server_walkthroughs", []) or []:
            for impl in server.get("service_impl_continuations", []) or []:
                for same in impl.get("same_class_method_continuations", []) or []:
                    for group in same.get("rule_groups", []) or []:
                        if group.get("group") == "data_protection":
                            protected_fields.update(group.get("fields", []) or [])
    guard(
        "present" if protected_fields else "unknown",
        "downstream_data_protection_filters",
        "下游查询是否包含 protectCode/categoryTag/unitLevel/isPublic/isSubmited 等数据范围过滤。",
        {"fields": sorted(protected_fields)},
    )
    return guards


def collect_result_abs_paths(result: Dict[str, Any]) -> List[str]:
    paths: List[str] = []

    def add(item: Dict[str, Any]) -> None:
        path = item.get("absolute_file_path")
        if path and path not in paths:
            paths.append(path)

    add(result.get("target", {}) or {})
    for impl in result.get("local_service_continuations", []) or []:
        add(impl.get("target", {}) or {})
    for same in result.get("same_class_method_continuations", []) or []:
        add(same.get("target", {}) or {})
    for feign in result.get("feign_continuations", []) or []:
        for server in feign.get("server_walkthroughs", []) or []:
            add(server)
            for impl in server.get("service_impl_continuations", []) or []:
                add(impl.get("target", {}) or {})
                for same in impl.get("same_class_method_continuations", []) or []:
                    add(same.get("target", {}) or {})
    return paths


def git_changed_abs_paths(root: Path) -> set[str]:
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"],
            text=True,
            capture_output=True,
            timeout=3,
            check=False,
        )
    except Exception:
        return set()
    out: set[str] = set()
    if proc.returncode != 0:
        return out
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        raw = line[3:] if len(line) > 3 else line.strip()
        if " -> " in raw:
            raw = raw.split(" -> ", 1)[1]
        out.add(str((root / raw).resolve()))
    return out


def build_walkthrough_diff_context(config: Any, result: Dict[str, Any]) -> Dict[str, Any]:
    root = getattr(config, "root_path", Path.cwd())
    changed_abs = git_changed_abs_paths(root)
    read_paths = collect_result_abs_paths(result)
    touched = [path for path in read_paths if path in changed_abs]
    return {
        "enabled": bool(changed_abs),
        "changed_file_count": len(changed_abs),
        "touched_read_targets": touched,
        "has_touched_read_targets": bool(touched),
    }


def build_walkthrough_index_freshness(
    walkthrough_index_signature: Dict[str, float],
    result: Dict[str, Any],
) -> Dict[str, Any]:
    latest_index_mtime = max(walkthrough_index_signature.values(), default=0.0)
    stale_targets: List[Dict[str, Any]] = []
    for path in collect_result_abs_paths(result):
        try:
            file_mtime = Path(path).stat().st_mtime
        except OSError:
            continue
        if latest_index_mtime and file_mtime > latest_index_mtime:
            stale_targets.append({
                "absolute_file_path": path,
                "file_mtime": file_mtime,
                "index_mtime": latest_index_mtime,
            })
    return {
        "index_stale": bool(stale_targets),
        "latest_index_mtime": latest_index_mtime,
        "stale_read_targets": stale_targets,
        "recommended_action": "先读取 stale_read_targets 的实时文件；必要时运行 reindex" if stale_targets else "",
    }


def build_walkthrough_branch_outline(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    outlines: List[Dict[str, Any]] = []

    def add_from_continuation(source: str, continuation: Dict[str, Any]) -> None:
        target = continuation.get("target", {}) or {}
        groups = []
        for group in continuation.get("rule_groups", []) or []:
            fields = group.get("fields", []) or []
            groups.append({
                "group": group.get("group", ""),
                "field_count": len(fields),
                "fields": fields[:20],
            })
        if not groups:
            summary = continuation.get("field_filter_summary", {}) or {}
            fields = summary.get("unique_dto_fields", []) or []
            if fields:
                groups.append({
                    "group": "dto_fields",
                    "field_count": len(fields),
                    "fields": fields[:20],
                })
        if not groups:
            calls = [
                step.get("method", "")
                for step in continuation.get("local_steps", []) or []
                if step.get("kind") == "method_call" and step.get("method")
            ]
            if calls:
                groups.append({
                    "group": "method_calls",
                    "field_count": len(calls),
                    "fields": calls[:20],
                })
        span = (target.get("evidence_span") or continuation.get("evidence_span") or {})
        if groups:
            outlines.append({
                "source": source,
                "target": {
                    "class": target.get("class", ""),
                    "method": target.get("method", ""),
                    "absolute_file_path": target.get("absolute_file_path", ""),
                    "line": target.get("line", 0),
                },
                "kind": "rule_group_outline",
                "groups": groups,
                "evidence_span": span,
            })

    for same in result.get("same_class_method_continuations", []) or []:
        add_from_continuation("same_class", same)
    for feign in result.get("feign_continuations", []) or []:
        for server in feign.get("server_walkthroughs", []) or []:
            for impl in server.get("service_impl_continuations", []) or []:
                for same in impl.get("same_class_method_continuations", []) or []:
                    add_from_continuation("server_impl_same_class", same)

    if not outlines:
        target = result.get("target", {}) or {}
        case_labels = extract_java_case_labels(target.get("absolute_file_path", ""), target.get("method", ""))
        if case_labels:
            outlines.append({
                "source": "target",
                "target": {
                    "class": target.get("class", ""),
                    "method": target.get("method", ""),
                    "absolute_file_path": target.get("absolute_file_path", ""),
                    "line": target.get("line", 0),
                },
                "kind": "switch_case_outline",
                "cases": case_labels[:40],
            })
    return outlines


def build_method_walkthrough_mermaid(result: Dict[str, Any]) -> str:
    lines = ["flowchart TD"]
    counter = 0

    def node(label: str) -> str:
        nonlocal counter
        counter += 1
        ident = f"N{counter}"
        safe = label.replace('"', "'")
        lines.append(f'  {ident}["{safe}"]')
        return ident

    target = result.get("target", {}) or {}
    root = node(f"{target.get('project', '')}:{target.get('class', '')}#{target.get('method', '')}")
    last = root
    for impl in result.get("local_service_continuations", []) or []:
        impl_target = impl.get("target", {}) or {}
        n = node(f"{impl_target.get('project', '')}:{impl_target.get('class', '')}#{impl_target.get('method', '')}")
        lines.append(f"  {last} --> {n}")
    for feign in result.get("feign_continuations", []) or []:
        fnode = node(f"Feign {feign.get('interface', '')}.{feign.get('method', '')}")
        lines.append(f"  {root} --> {fnode}")
        for server in (feign.get("server_walkthroughs", []) or [])[:1]:
            snode = node(f"{server.get('project', '')}:{server.get('controller', '')}#{server.get('method', '')}")
            lines.append(f"  {fnode} --> {snode}")
            for impl in (server.get("service_impl_continuations", []) or [])[:1]:
                impl_target = impl.get("target", {}) or {}
                inode = node(f"{impl_target.get('project', '')}:{impl_target.get('class', '')}#{impl_target.get('method', '')}")
                lines.append(f"  {snode} --> {inode}")
                for same in (impl.get("same_class_method_continuations", []) or [])[:2]:
                    same_target = same.get("target", {}) or {}
                    qnode = node(f"{same_target.get('class', '')}#{same_target.get('method', '')}")
                    lines.append(f"  {inode} --> {qnode}")
    if result.get("performance_risks"):
        risk = node(f"风险 {len(result.get('performance_risks', []) or [])}")
        lines.append(f"  {root} -.-> {risk}")
    guards = [item for item in result.get("data_scope_guards", []) or [] if item.get("status") == "present"]
    if guards:
        guard = node(f"数据范围保护 {len(guards)}")
        lines.append(f"  {root} -.-> {guard}")
    diff = result.get("diff_context", {}) or {}
    if diff.get("has_touched_read_targets"):
        changed = node(f"Diff 命中 {len(diff.get('touched_read_targets', []) or [])}")
        lines.append(f"  {root} -.-> {changed}")
    return "\n".join(lines)
