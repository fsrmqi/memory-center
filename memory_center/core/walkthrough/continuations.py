"""Continuation builders: local steps, Feign clients, server impls, same-class chains."""

from __future__ import annotations

from typing import Any, Dict, List

from ..orchestrator.common import _project_matches
from .symbols import (
    detect_unqualified_same_class_calls,
    find_method_span_lines,
    find_method_symbol_entry,
    find_receiver_impl_method,
    resolve_indexed_abs_path,
)

__all__ = [
    "build_method_local_steps",
    "build_method_feign_continuations",
    "build_service_impl_continuations",
    "build_same_class_method_continuations",
    "build_method_walkthrough_next_actions",
    "summarize_dto_field_filters",
    "classify_dto_field_rule_groups",
    "dedupe_feign_continuations",
]


def _format_method_step_summary(kind: str, call: Dict[str, Any]) -> str:
    receiver_type = call.get("receiver_type", "") or "unknown"
    receiver = call.get("receiver", "")
    method = call.get("method_name", "")
    if kind == "feign_call":
        return f"调用 Feign {receiver_type}.{method}"
    return f"调用 {receiver or receiver_type}.{method}"


def build_method_local_steps(
    method_calls: List[Dict[str, Any]],
    dto_field_usages: List[Dict[str, Any]],
    feigns: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    feign_interfaces = {item.get("interface", "") for item in feigns}
    steps: List[Dict[str, Any]] = []
    for call in method_calls:
        receiver_type = call.get("receiver_type", "")
        kind = "feign_call" if receiver_type in feign_interfaces else "method_call"
        steps.append(
            {
                "kind": kind,
                "line": int(call.get("line", 0) or 0),
                "receiver": call.get("receiver", ""),
                "receiver_type": receiver_type,
                "method": call.get("method_name", ""),
                "summary": _format_method_step_summary(kind, call),
            }
        )
    for usage in dto_field_usages:
        steps.append(
            {
                "kind": "dto_field_read",
                "line": int(usage.get("line", 0) or 0),
                "receiver": usage.get("receiver", ""),
                "receiver_type": usage.get("receiver_type", ""),
                "field": usage.get("field", ""),
                "summary": f"读取 DTO 字段 {usage.get('receiver', '')}.{usage.get('field', '')}",
            }
        )
    steps.sort(key=lambda row: (int(row.get("line", 0) or 0), row.get("kind", "")))
    return steps


def _with_endpoint_confidence(api: Dict[str, Any], target_service: str) -> Dict[str, Any]:
    item = dict(api)
    project = str(api.get("project", "") or "")
    file_path = str(api.get("file", "") or "")
    controller = str(api.get("controller", "") or "")
    reasons: List[str] = []
    score = 0.35
    if target_service and (_project_matches(target_service, project) or _project_matches(project, target_service)):
        score += 0.35
        reasons.append("project_matches_target_service")
    if target_service and target_service.replace("-", "").lower() in file_path.replace("-", "").lower():
        score += 0.15
        reasons.append("file_path_mentions_target_service")
    if controller and controller in file_path:
        score += 0.08
        reasons.append("controller_matches_file")
    if project:
        score += 0.05
        reasons.append("project_present")
    item["confidence"] = round(min(score, 1.0), 2)
    item["confidence_reasons"] = reasons or ["http_method_and_path_match"]
    return item


def _rank_feign_matched_endpoints(
    endpoints: List[Dict[str, Any]], target_service: str
) -> List[Dict[str, Any]]:
    enriched = [_with_endpoint_confidence(api, target_service) for api in endpoints]
    return sorted(
        enriched,
        key=lambda api: (
            -float(api.get("confidence", 0.0) or 0.0),
            str(api.get("project", "") or ""),
            str(api.get("file", "") or ""),
        ),
    )


def _summarize_endpoint_walkthrough(
    api: Dict[str, Any],
    symbols: List[Dict[str, Any]],
    file_abs_map: Dict[tuple, str],
) -> Dict[str, Any]:
    controller = api.get("controller", "")
    method = api.get("method_name", "")
    entry = find_method_symbol_entry(
        symbols,
        {"class": controller, "method": method, "package": ""},
        project=api.get("project", ""),
    )
    if not entry:
        return {
            "project": api.get("project", ""),
            "controller": controller,
            "method": method,
            "found": False,
            "reason": "controller method not found in java-symbol-index",
            "endpoint_confidence": api.get("confidence", 0.0),
            "endpoint_confidence_reasons": api.get("confidence_reasons", []),
        }
    calls = [
        dict(call)
        for call in entry["symbol"].get("method_calls", [])
        if call.get("owner_method") == method
    ]
    calls.sort(key=lambda row: int(row.get("line", 0) or 0))
    dto_usages = [
        dict(usage)
        for usage in entry["symbol"].get("dto_field_usages", [])
        if usage.get("owner_method") == method
    ]
    dto_usages.sort(key=lambda row: int(row.get("line", 0) or 0))
    local_steps = build_method_local_steps(calls, dto_usages, feigns=[])
    service_impls = build_service_impl_continuations(symbols, entry, calls, file_abs_map)
    return {
        "project": entry["project"],
        "controller": controller,
        "method": method,
        "found": True,
        "file_path": entry["file"],
        "absolute_file_path": resolve_indexed_abs_path(file_abs_map, entry["project"], entry["file"]),
        "line": int((entry["symbol"].get("method_lines") or {}).get(method, 0) or 0),
        "endpoint_confidence": api.get("confidence", 0.0),
        "endpoint_confidence_reasons": api.get("confidence_reasons", []),
        "local_steps": local_steps,
        "service_impl_continuations": service_impls,
    }


def _continuations_for_feign_method(
    feign: Dict[str, Any],
    method_name: str,
    apis: List[Dict[str, Any]],
    symbols: List[Dict[str, Any]],
    file_abs_map: Dict[tuple, str],
    source_call: Dict[str, Any],
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for method in feign.get("methods", []) or []:
        if method.get("method_name") != method_name:
            continue
        endpoints = [
            api for api in apis
            if api.get("http_method") == method.get("http_method") and api.get("path") == method.get("path")
        ]
        endpoints = _rank_feign_matched_endpoints(endpoints, feign.get("target_service", ""))
        endpoint_summaries = [_summarize_endpoint_walkthrough(api, symbols, file_abs_map) for api in endpoints[:3]]
        out.append(
            {
                "interface": feign.get("interface", ""),
                "method": method_name,
                "target_service": feign.get("target_service", ""),
                "http_method": method.get("http_method", ""),
                "path": method.get("path", ""),
                "source_line": int(source_call.get("line", 0) or 0),
                "matched_endpoints": [
                    {
                        "project": api.get("project", ""),
                        "controller": api.get("controller", ""),
                        "method": api.get("method_name", ""),
                        "file_path": api.get("file", ""),
                        "absolute_file_path": resolve_indexed_abs_path(file_abs_map, api.get("project", ""), api.get("file", "")),
                        "http_method": api.get("http_method", ""),
                        "path": api.get("path", ""),
                        "confidence": api.get("confidence", 0.0),
                        "confidence_reasons": api.get("confidence_reasons", []),
                    }
                    for api in endpoints
                ],
                "server_walkthroughs": endpoint_summaries,
            }
        )
    return out


def dedupe_feign_continuations(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    deduped: List[Dict[str, Any]] = []
    seen = set()
    for item in items:
        key = (item.get("interface"), item.get("method"), item.get("http_method"), item.get("path"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def build_method_feign_continuations(
    entry: Dict[str, Any],
    method_name: str,
    method_calls: List[Dict[str, Any]],
    feigns: List[Dict[str, Any]],
    apis: List[Dict[str, Any]],
    symbols: List[Dict[str, Any]],
    file_abs_map: Dict[tuple, str],
) -> List[Dict[str, Any]]:
    continuations: List[Dict[str, Any]] = []
    feign_by_interface = {item.get("interface", ""): item for item in feigns}
    owner_feign = feign_by_interface.get(entry.get("class_name", ""))
    if owner_feign:
        continuations.extend(_continuations_for_feign_method(owner_feign, method_name, apis, symbols, file_abs_map, source_call={}))
    for call in method_calls:
        feign = feign_by_interface.get(call.get("receiver_type", ""))
        if not feign:
            continue
        continuations.extend(_continuations_for_feign_method(feign, call.get("method_name", ""), apis, symbols, file_abs_map, source_call=call))
    return dedupe_feign_continuations(continuations)


def build_service_impl_continuations(
    symbols: List[Dict[str, Any]],
    entry: Dict[str, Any],
    method_calls: List[Dict[str, Any]],
    file_abs_map: Dict[tuple, str] | None = None,
    feigns: List[Dict[str, Any]] | None = None,
    apis: List[Dict[str, Any]] | None = None,
) -> List[Dict[str, Any]]:
    continuations: List[Dict[str, Any]] = []
    seen = set()
    for call in method_calls:
        receiver_type = str(call.get("receiver_type", "") or "")
        method_name = str(call.get("method_name", "") or "")
        if not receiver_type or not method_name:
            continue
        impl_entry = find_receiver_impl_method(symbols, receiver_type, method_name, entry.get("project", ""))
        if not impl_entry:
            continue
        key = (impl_entry.get("project", ""), impl_entry.get("file", ""), impl_entry.get("class_name", ""), method_name)
        if key in seen:
            continue
        seen.add(key)
        impl_calls = [
            dict(row)
            for row in impl_entry["symbol"].get("method_calls", [])
            if row.get("owner_method") == method_name
        ]
        impl_calls.sort(key=lambda row: int(row.get("line", 0) or 0))
        impl_dto = [
            dict(row)
            for row in impl_entry["symbol"].get("dto_field_usages", [])
            if row.get("owner_method") == method_name
        ]
        impl_dto.sort(key=lambda row: int(row.get("line", 0) or 0))
        nested_feigns = build_method_feign_continuations(
            impl_entry,
            method_name,
            impl_calls,
            feigns or [],
            apis or [],
            symbols,
            file_abs_map or {},
        )
        nested_same_class = build_same_class_method_continuations(
            symbols,
            impl_entry,
            method_name,
            file_abs_map or {},
            feigns or [],
            apis or [],
        )
        continuations.append(
            {
                "receiver": call.get("receiver", ""),
                "receiver_type": receiver_type,
                "method": method_name,
                "source_line": int(call.get("line", 0) or 0),
                "target": {
                    "package": impl_entry["symbol"].get("package", ""),
                    "class": impl_entry.get("class_name", ""),
                    "method": method_name,
                    "project": impl_entry.get("project", ""),
                    "file_path": impl_entry.get("file", ""),
                    "absolute_file_path": resolve_indexed_abs_path(file_abs_map or {}, impl_entry.get("project", ""), impl_entry.get("file", "")),
                    "line": int((impl_entry["symbol"].get("method_lines") or {}).get(method_name, 0) or 0),
                },
                "local_steps": build_method_local_steps(impl_calls, impl_dto, feigns=[]),
                "same_class_method_continuations": nested_same_class,
                "feign_continuations": nested_feigns,
                "data_resources": impl_entry["symbol"].get("data_resources", []),
                "config_usages": impl_entry["symbol"].get("config_usages", []),
            }
        )
    return continuations


def build_same_class_method_continuations(
    symbols: List[Dict[str, Any]],
    entry: Dict[str, Any],
    method_name: str,
    file_abs_map: Dict[tuple, str],
    feigns: List[Dict[str, Any]],
    apis: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    symbol = entry.get("symbol", {}) or {}
    class_methods = set(symbol.get("methods", []) or [])
    if not class_methods:
        return []
    abs_path = resolve_indexed_abs_path(file_abs_map, entry.get("project", ""), entry.get("file", ""))
    called_methods = detect_unqualified_same_class_calls(abs_path, method_name, class_methods)
    continuations: List[Dict[str, Any]] = []
    for called in called_methods:
        if called == method_name:
            continue
        target_entry = find_method_symbol_entry(
            symbols,
            {"class": entry.get("class_name", ""), "method": called, "package": symbol.get("package", "") or ""},
            project=entry.get("project", ""),
        )
        if not target_entry:
            continue
        calls = [
            dict(row)
            for row in target_entry["symbol"].get("method_calls", [])
            if row.get("owner_method") == called
        ]
        calls.sort(key=lambda row: int(row.get("line", 0) or 0))
        dto = [
            dict(row)
            for row in target_entry["symbol"].get("dto_field_usages", [])
            if row.get("owner_method") == called
        ]
        dto.sort(key=lambda row: int(row.get("line", 0) or 0))
        continuations.append(
            {
                "method": called,
                "target": {
                    "package": target_entry["symbol"].get("package", ""),
                    "class": target_entry.get("class_name", ""),
                    "method": called,
                    "project": target_entry.get("project", ""),
                    "file_path": target_entry.get("file", ""),
                    "absolute_file_path": resolve_indexed_abs_path(file_abs_map, target_entry.get("project", ""), target_entry.get("file", "")),
                    "line": int((target_entry["symbol"].get("method_lines") or {}).get(called, 0) or 0),
                },
                "local_steps": build_method_local_steps(calls, dto, feigns),
                "field_filter_summary": summarize_dto_field_filters(dto),
                "rule_groups": classify_dto_field_rule_groups(dto),
                "feign_continuations": build_method_feign_continuations(target_entry, called, calls, feigns, apis, symbols, file_abs_map),
                "data_resources": target_entry["symbol"].get("data_resources", []),
                "config_usages": target_entry["symbol"].get("config_usages", []),
            }
        )
        continuations[-1]["target"]["evidence_span"] = find_method_span_lines(
            continuations[-1]["target"]["absolute_file_path"],
            called,
        )
    return continuations


def summarize_dto_field_filters(dto_usages: List[Dict[str, Any]]) -> Dict[str, Any]:
    fields: List[str] = []
    seen = set()
    for row in dto_usages:
        receiver_type = row.get("receiver_type", "") or row.get("receiver", "")
        if "Dto" not in receiver_type and "DTO" not in receiver_type:
            continue
        field = str(row.get("field", "") or "")
        if not field or field in seen:
            continue
        seen.add(field)
        fields.append(field)
    return {
        "unique_dto_fields": fields[:80],
        "unique_dto_field_count": len(fields),
        "truncated": len(fields) > 80,
    }


def classify_dto_field_rule_groups(dto_usages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    summary = summarize_dto_field_filters(dto_usages)
    fields = summary.get("unique_dto_fields", []) or []
    groups = [
        ("identity", {"id", "idList", "notVersionId", "urlMd5"}),
        ("audit", {"reviewType", "reviewTypeList", "reviewState", "reviewStateList", "resultType", "resultTypeList"}),
        ("site_url_content", {"siteInfo", "siteCode", "article", "url", "searchUrlType", "pageType", "pageTypeList", "parentUrl"}),
        ("question_type_script", {"questionTypeCountGt0", "questionTypeCountGt0List"}),
        ("time", {"dateType", "startDate", "endDate", "dateType2", "startDate2", "endDate2"}),
        ("code", {"codeType", "codeTypeVal"}),
        ("region", {"distIdList", "distSign", "provDistId", "cityDistId", "countyDistId"}),
        ("organization", {"tradePid", "tradeSid", "tradeGid", "organPid", "organSid", "organGid", "payType", "isParentBill", "unitPayType", "deliveryTeam"}),
        ("data_protection", {"protectCode", "categoryTag", "unitLevel", "isPublic", "isSubmited"}),
        ("release_label", {"releaseFlag", "dataBizType", "labelIds"}),
        ("inventory", {"invResult", "invResultList", "invBatchNo", "invProcessResult", "invProcessMethod", "pubOffice", "invProcessBy"}),
        ("sort", {"sortField", "sortFlag", "check"}),
    ]
    remaining = set(fields)
    out: List[Dict[str, Any]] = []
    for name, known in groups:
        matched = [field for field in fields if field in known]
        if matched:
            remaining.difference_update(matched)
            out.append({"group": name, "fields": matched, "count": len(matched)})
    if remaining:
        ordered = [field for field in fields if field in remaining]
        out.append({"group": "other", "fields": ordered, "count": len(ordered)})
    return out


def build_method_walkthrough_next_actions(
    feign_continuations: List[Dict[str, Any]],
    downstream_summary: Dict[str, Any],
    local_service_continuations: List[Dict[str, Any]] | None = None,
    same_class_continuations: List[Dict[str, Any]] | None = None,
) -> List[str]:
    actions: List[str] = []
    has_server_walkthroughs = any(item.get("server_walkthroughs") for item in feign_continuations or [])
    has_server_impls = any(
        server.get("service_impl_continuations")
        for item in feign_continuations or []
        for server in item.get("server_walkthroughs", []) or []
    )
    if local_service_continuations:
        actions.append("优先阅读 local_service_continuations 中的本地 Service Impl 续链；直接使用 absolute_file_path，不需要 find")
    if same_class_continuations:
        actions.append("优先阅读 same_class_method_continuations 中的同类私有/辅助方法续链；直接使用 absolute_file_path 和 field_filter_summary，不需要 sed 切片")
    if feign_continuations and has_server_walkthroughs:
        if has_server_impls:
            actions.append("优先阅读 feign_continuations.server_walkthroughs[].service_impl_continuations 中的服务端 Impl 续链；直接使用 absolute_file_path，不需要 find")
        else:
            actions.append("优先阅读 feign_continuations.server_walkthroughs 中的服务端 Controller 续链；直接使用 absolute_file_path，不需要 find")
    elif feign_continuations:
        actions.append("对 feign_continuations.matched_endpoints 中的 Controller#method 继续调用 mc_lookup(mode='walkthrough')")
    if downstream_summary.get("total_edges", 0):
        actions.append("downstream_summary 仅作补充图谱线索；若与 walkthrough 冲突，以 local/service/feign continuations 为准")
    if not actions:
        actions.append("当前方法没有索引到下游调用；必要时先 reindex 或用代码搜索确认动态调用")
    return actions
