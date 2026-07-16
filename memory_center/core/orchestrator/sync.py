from __future__ import annotations

from pathlib import Path
from typing import Any

from ..artifacts import (
    append_task_change_log,
    get_task_artifact,
    resolve_task_space,
    touch_task_activity,
    update_task_current_summary_snapshot,
    update_task_artifact,
)
from ..write_receipts import build_write_receipt
from .common import (
    LAYER_L2,
    TOOL_WORKSPACE_SYNC_CASE_ARTIFACTS,
    TOOL_WORKSPACE_SYNC_SNIFF_ARTIFACTS,
    _build_sniff_auto_sync_recommendation,
    _case_risk_level,
    _case_risk_profile,
    _load_auto_sync_rules,
    _merge_artifact_section,
    _render_ref_label,
    _score_threshold_for_sync_mode,
    load_context,
)


TASK_SYNC_EXISTING_ARTIFACT_MAX_BYTES = 512 * 1024


def workspace_sync_sniff_to_artifacts(
    workspace_file: str | Path,
    intent: str,
    limit: int = 12,
    task_id: str = "",
    title: str = "",
    auto_sync_mode: str = "balanced",
    sniff_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from .workspace import workspace_sniff

    config, store = load_context(workspace_file)
    sniff = sniff_result if isinstance(sniff_result, dict) else workspace_sniff(workspace_file, intent, limit=limit)
    auto_sync_rules = _load_auto_sync_rules(store)
    aliases = (auto_sync_rules or {}).get("mode_aliases", {}) or {}
    resolved_mode = aliases.get(auto_sync_mode, auto_sync_mode)
    threshold = _score_threshold_for_sync_mode(resolved_mode)

    resolved = resolve_task_space(
        workspace_file,
        intent=intent,
        title=title or task_id,
        create_if_missing=True,
        score_threshold=threshold,
        related_texts=_task_resolution_hints_from_sniff(sniff),
    )
    resolved_task_id = resolved.get("task_id", "")
    if not resolved_task_id:
        return {
            "workspace": config.workspace,
            "synced": False,
            "reason": "failed_to_resolve_task_space",
            "sniff": sniff,
            "resolved": resolved,
        }

    touch_task_activity(workspace_file, resolved_task_id, source="sync_sniff_artifacts")

    auto_sync = _build_sniff_auto_sync_recommendation(store, resolved, sniff.get("risk_level", ""), auto_sync_mode=auto_sync_mode)

    skipped_oversized_artifacts: list[str] = []
    if _sync_task_artifact_section(
        workspace_file,
        resolved_task_id,
        "context",
        "Sniff Context",
        _render_sniff_context_markdown(sniff),
        source="sync_sniff_artifacts",
    ):
        skipped_oversized_artifacts.append("context")
    if _sync_task_artifact_section(
        workspace_file,
        resolved_task_id,
        "plan",
        "Sniff Plan",
        _render_sniff_plan_markdown(sniff),
        source="sync_sniff_artifacts",
    ):
        skipped_oversized_artifacts.append("plan")

    summary_body = _render_task_current_summary_from_sniff(sniff, resolved)
    update_task_current_summary_snapshot(workspace_file, resolved_task_id, summary_body, source="sync_sniff_artifacts")

    updated_artifacts = [name for name in ["context", "plan"] if name not in skipped_oversized_artifacts] + ["current_summary"]
    receipt = build_write_receipt(
        layer=LAYER_L2,
        action=TOOL_WORKSPACE_SYNC_SNIFF_ARTIFACTS,
        scope="task_space",
        target=resolved_task_id,
        target_file=f"tasks/{resolved_task_id}",
        task_id=resolved_task_id,
        updated_artifacts=updated_artifacts,
    )

    return {
        "workspace": config.workspace,
        "synced": True,
        "task_id": resolved_task_id,
        "title": resolved.get("title", ""),
        "intent": intent,
        "auto_sync_mode": auto_sync_mode,
        "auto_sync_recommendation": auto_sync,
        "updated_artifacts": updated_artifacts,
        "skipped_oversized_artifacts": skipped_oversized_artifacts,
        "resolved": resolved,
        "sniff_summary": {
            "risk_level": sniff.get("risk_level", ""),
            "matched_services": sniff.get("matched_services", []),
            "candidate_file_count": len(sniff.get("candidate_files", [])),
            "related_feign_count": len(sniff.get("related_feigns", [])),
            "related_api_count": len(sniff.get("related_apis", [])),
            "related_mq_count": len(sniff.get("related_mq", [])),
        },
        "write_receipt": receipt,
        "sniff_reused": sniff_result is not None,
    }


def workspace_sync_case_to_artifacts(
    workspace_file: str | Path,
    session_id: str,
    task_id: str = "",
    title: str = "",
    auto_sync_mode: str = "balanced",
) -> dict[str, Any]:
    from .session import workspace_suggest_case

    config, store = load_context(workspace_file)
    case_result = workspace_suggest_case(workspace_file, session_id)
    if not case_result.get("found"):
        return {
            "workspace": config.workspace,
            "synced": False,
            "reason": "session_not_found",
            "session_id": session_id,
            "hint": case_result.get("hint", ""),
        }

    case = case_result.get("draft_case", {})
    if not case:
        return {
            "workspace": config.workspace,
            "synced": False,
            "reason": "no_draft_case",
            "session_id": session_id,
        }

    threshold = _score_threshold_for_sync_mode(auto_sync_mode)

    case_intent = case.get("task", "") or title or f"case from session {session_id}"
    resolved = resolve_task_space(
        workspace_file,
        intent=case_intent,
        title=title or task_id,
        create_if_missing=True,
        score_threshold=threshold,
        related_texts=_task_resolution_hints_from_case(case),
    )
    resolved_task_id = resolved.get("task_id", "")
    if not resolved_task_id:
        return {
            "workspace": config.workspace,
            "synced": False,
            "reason": "failed_to_resolve_task_space",
            "session_id": session_id,
            "case": case,
            "resolved": resolved,
        }

    touch_task_activity(workspace_file, resolved_task_id, source="sync_case_artifacts")

    skipped_oversized_artifacts: list[str] = []
    if _sync_task_artifact_section(
        workspace_file,
        resolved_task_id,
        "design",
        "Case Design",
        _render_case_markdown(case),
        source="sync_case_artifacts",
    ):
        skipped_oversized_artifacts.append("design")

    change_log_entry = _render_change_log_entry(case, session_id)
    append_task_change_log(workspace_file, resolved_task_id, change_log_entry, source="sync_case_artifacts")

    summary_body = _render_task_current_summary_from_case(case, resolved, session_id)
    update_task_current_summary_snapshot(workspace_file, resolved_task_id, summary_body, source="sync_case_artifacts")

    risk_profile = _case_risk_profile(case)
    updated_artifacts = [name for name in ["design"] if name not in skipped_oversized_artifacts] + ["change_log", "current_summary"]
    receipt = build_write_receipt(
        layer=LAYER_L2,
        action=TOOL_WORKSPACE_SYNC_CASE_ARTIFACTS,
        scope="task_space",
        target=resolved_task_id,
        target_file=f"tasks/{resolved_task_id}",
        task_id=resolved_task_id,
        session_id=session_id,
        source_session_id=session_id,
        updated_artifacts=updated_artifacts,
    )

    return {
        "workspace": config.workspace,
        "synced": True,
        "task_id": resolved_task_id,
        "title": resolved.get("title", ""),
        "session_id": session_id,
        "auto_sync_mode": auto_sync_mode,
        "auto_sync_recommendation": _build_sniff_auto_sync_recommendation(store, resolved, risk_profile.get("risk_level", ""), auto_sync_mode=auto_sync_mode),
        "updated_artifacts": updated_artifacts,
        "skipped_oversized_artifacts": skipped_oversized_artifacts,
        "resolved": resolved,
        "case_summary": {
            "task": case.get("task", ""),
            "projects": case.get("projects", []),
            "file_count": len(case.get("files", [])),
            "risk_level": risk_profile.get("risk_level", ""),
            "risk_signals": risk_profile.get("signals", []),
        },
        "write_receipt": receipt,
    }


def _sync_task_artifact_section(
    workspace_file: str | Path,
    task_id: str,
    artifact_name: str,
    section_name: str,
    section_body: str,
    *,
    source: str,
) -> bool:
    """Return True when a large artifact is intentionally preserved unchanged."""
    try:
        artifact = get_task_artifact(
            workspace_file,
            task_id,
            artifact_name,
            max_bytes=TASK_SYNC_EXISTING_ARTIFACT_MAX_BYTES,
        )
        if artifact.get("truncated"):
            return True
        existing = str(artifact.get("content", ""))
    except Exception:
        existing = ""
    merged = _merge_artifact_section(existing, section_name, section_body)
    update_task_artifact(workspace_file, task_id, artifact_name, merged, source=source)
    return False


def _render_sniff_context_markdown(sniff: dict[str, Any]) -> str:
    parts: list[str] = []
    intent = sniff.get("intent", "")
    if intent:
        parts.append(f"**Intent / 意图**: {intent}")
    risk_level = sniff.get("risk_level", "")
    if risk_level:
        parts.append(f"**Risk Level**: {risk_level}")

    matched_services = sniff.get("matched_services", [])
    if matched_services:
        parts.append("")
        parts.append("### Matched Services / 匹配服务")
        for svc in matched_services:
            if isinstance(svc, dict):
                name = svc.get("name", "") or svc.get("service_name", "") or svc.get("project", "")
                parts.append(f"- {name}")
            else:
                parts.append(f"- {svc}")

    candidate_files = sniff.get("candidate_files", [])
    if candidate_files:
        parts.append("")
        parts.append("### Candidate Files / 候选文件")
        for item in candidate_files[:10]:
            path = item.get("path", "")
            project = item.get("project", "")
            score = item.get("score", 0)
            label = f"{project}/{path}" if project else path
            parts.append(f"- `{label}` (score={score})")

    related_feigns = sniff.get("related_feigns", [])
    if related_feigns:
        parts.append("")
        parts.append("### Related Feign Clients / 相关 Feign")
        for item in related_feigns[:6]:
            interface = item.get("interface", "")
            project = item.get("project", "")
            parts.append(f"- `{interface}` ({project})")

    related_apis = sniff.get("related_apis", [])
    if related_apis:
        parts.append("")
        parts.append("### Related APIs / 相关接口")
        for item in related_apis[:6]:
            method = item.get("http_method", "")
            path = item.get("path", "")
            parts.append(f"- {method} `{path}`")

    related_mq = sniff.get("related_mq", [])
    if related_mq:
        parts.append("")
        parts.append("### Related MQ Topics / 相关消息队列")
        for item in related_mq[:6]:
            topic = item.get("topic", "")
            project = item.get("project", "")
            parts.append(f"- `{topic}` ({project})")

    related_cases = sniff.get("historical_cases", [])
    if related_cases:
        parts.append("")
        parts.append("### Historical Cases / 历史案例")
        for item in related_cases[-5:]:
            task = item.get("task", "")
            projects = item.get("projects", [])
            label = f"{task} [{', '.join(projects[:3])}]" if projects else task
            parts.append(f"- {label}")

    source_refs = sniff.get("source_refs", [])
    if source_refs:
        parts.append("")
        parts.append("### Source References / 来源引用")
        for ref in source_refs[:8]:
            parts.append(f"- {_render_ref_label(ref)}")

    rules = sniff.get("related_rules", [])
    if rules:
        parts.append("")
        parts.append("### Related Rules / 相关规则")
        for rule in rules[:6]:
            name = rule.get("name", "") or rule.get("title", "")
            severity = rule.get("severity", "")
            if name:
                parts.append(f"- [{severity}] {name}" if severity else f"- {name}")

    if not parts:
        parts.append("_No sniff context available._")

    return "\n".join(parts)


def _task_resolution_hints_from_sniff(sniff: dict[str, Any]) -> list[str]:
    hints: list[str] = []
    for service in sniff.get("matched_services", []) or []:
        if isinstance(service, dict):
            hints.append(str(service.get("name", "") or service.get("service_name", "") or service.get("project", "")))
        else:
            hints.append(str(service))
    for item in sniff.get("candidate_files", []) or []:
        if isinstance(item, dict):
            hints.append(str(item.get("path", "")))
            hints.append(str(item.get("project", "")))
    for key in ("related_feigns", "related_apis", "related_mq", "historical_cases"):
        for item in sniff.get(key, []) or []:
            hints.append(str(item))
    return [item for item in hints if item.strip()]


def _task_resolution_hints_from_case(case: dict[str, Any]) -> list[str]:
    hints: list[str] = []
    for key in ("projects", "files", "risk_points", "source_refs"):
        for item in case.get(key, []) or []:
            hints.append(str(item))
    for key in ("task", "flow"):
        value = str(case.get(key, "") or "")
        if value:
            hints.append(value)
    return [item for item in hints if item.strip()]


def _render_sniff_plan_markdown(sniff: dict[str, Any]) -> str:
    parts: list[str] = []
    intent = sniff.get("intent", "")
    if intent:
        parts.append(f"**Objective / 目标**: {intent}")

    risk_level = sniff.get("risk_level", "")
    if risk_level:
        parts.append(f"**Risk Level**: {risk_level}")

    matched_services = sniff.get("matched_services", [])
    service_names = []
    for svc in matched_services:
        if isinstance(svc, dict):
            service_names.append(svc.get("name", "") or svc.get("service_name", "") or svc.get("project", ""))
        else:
            service_names.append(str(svc))

    parts.append("")
    parts.append("## Action Items / 行动项")

    if service_names:
        parts.append(f"1. **Review impacted services**: {', '.join(service_names[:6])}")

    candidate_files = sniff.get("candidate_files", [])
    if candidate_files:
        top_files = [item.get("path", "") for item in candidate_files[:5]]
        parts.append(f"2. **Inspect top candidate files**: {', '.join(top_files)}")

    related_feigns = sniff.get("related_feigns", [])
    related_apis = sniff.get("related_apis", [])
    related_mq = sniff.get("related_mq", [])
    contract_items = []
    if related_feigns:
        contract_items.append(f"Feign ({len(related_feigns)})")
    if related_apis:
        contract_items.append(f"API ({len(related_apis)})")
    if related_mq:
        contract_items.append(f"MQ ({len(related_mq)})")
    if contract_items:
        parts.append(f"3. **Check contract compatibility**: {', '.join(contract_items)}")

    rules = sniff.get("related_rules", [])
    if rules:
        parts.append(f"4. **Follow relevant rules**: {len(rules)} rule(s) matched")

    next_steps = sniff.get("next_steps", [])
    if next_steps:
        parts.append("")
        parts.append("## Next Steps / 后续步骤")
        for idx, step in enumerate(next_steps, start=5):
            if isinstance(step, dict):
                text = step.get("text", "") or step.get("description", "") or str(step)
                parts.append(f"{idx}. {text}")
            else:
                parts.append(f"{idx}. {step}")

    symbolic = sniff.get("symbolic_context", {})
    if isinstance(symbolic, dict):
        flow_mermaid = symbolic.get("flow_mermaid", "")
        if flow_mermaid:
            parts.append("")
            parts.append("## Flow Diagram / 流程图")
            parts.append("")
            parts.append(f"```mermaid\n{flow_mermaid}\n```")

    if len(parts) <= 2:
        parts.append("")
        parts.append("_No plan items generated from sniff._")

    return "\n".join(parts)


def _render_case_markdown(case: dict[str, Any]) -> str:
    parts: list[str] = []
    task = case.get("task", "")
    if task:
        parts.append(f"**Task / 任务**: {task}")

    projects = case.get("projects", [])
    if projects:
        parts.append(f"**Projects / 项目**: {', '.join(projects)}")

    files = case.get("files", [])
    if files:
        parts.append("")
        parts.append("### Files / 涉及文件")
        for item in files[:30]:
            parts.append(f"- `{item}`")

    flow = case.get("flow", "")
    if flow:
        parts.append("")
        parts.append("### Flow / 流程")
        parts.append(flow)

    risk_points = case.get("risk_points", [])
    if risk_points:
        parts.append("")
        parts.append("### Risk Points / 风险点")
        for point in risk_points:
            parts.append(f"- {point}")

    risk_profile = _case_risk_profile(case)
    risk_level = risk_profile.get("risk_level", "")
    risk_signals = risk_profile.get("signals", [])
    if risk_level:
        parts.append("")
        parts.append(f"**Assessed Risk Level**: {risk_level}")
        if risk_signals:
            parts.append(f"**Risk Signals**: {', '.join(risk_signals[:8])}")

    verified_by = case.get("verified_by", [])
    if verified_by:
        parts.append("")
        parts.append("### Verified By / 验证方式")
        for item in verified_by:
            parts.append(f"- {item}")

    source_refs = case.get("source_refs", [])
    if source_refs:
        parts.append("")
        parts.append("### Source References / 来源引用")
        for ref in source_refs[:10]:
            parts.append(f"- {_render_ref_label(ref)}")

    evidence_refs = case.get("evidence_refs", [])
    if evidence_refs:
        parts.append("")
        parts.append("### Evidence References / 证据引用")
        for ref in evidence_refs[:10]:
            parts.append(f"- {_render_ref_label(ref)}")

    if not parts:
        parts.append("_No case details available._")

    return "\n".join(parts)


def _render_change_log_entry(case: dict[str, Any], session_id: str) -> str:
    parts: list[str] = []
    task = case.get("task", "")
    if task:
        parts.append(f"Case synced: {task}")
    else:
        parts.append(f"Case synced from session {session_id}")

    projects = case.get("projects", [])
    if projects:
        parts.append(f"Projects: {', '.join(projects)}")

    risk_level = _case_risk_level(case)
    if risk_level:
        parts.append(f"Risk level: {risk_level}")

    flow = case.get("flow", "")
    if flow:
        parts.append(f"Flow: {flow}")

    risk_points = case.get("risk_points", [])
    if risk_points:
        parts.append("Risk points:")
        for point in risk_points[:5]:
            parts.append(f"  - {point}")

    parts.append(f"Source session: {session_id}")

    return "\n".join(parts)


def _render_task_current_summary_from_sniff(sniff: dict[str, Any], resolved_info: dict[str, Any]) -> str:
    parts: list[str] = []
    parts.append("# Current Summary / 当前最短上下文")
    parts.append("")

    intent = sniff.get("intent", "")
    if intent:
        parts.append(f"**Intent**: {intent}")

    task_title = resolved_info.get("title", "")
    task_id = resolved_info.get("task_id", "")
    if task_title:
        parts.append(f"**Task**: {task_title} (`{task_id}`)")

    risk_level = sniff.get("risk_level", "")
    if risk_level:
        parts.append(f"**Risk Level**: {risk_level}")

    matched_services = sniff.get("matched_services", [])
    if matched_services:
        service_names = []
        for svc in matched_services:
            if isinstance(svc, dict):
                service_names.append(svc.get("name", "") or svc.get("service_name", "") or svc.get("project", ""))
            else:
                service_names.append(str(svc))
        parts.append(f"**Impacted Services**: {', '.join(service_names[:6])}")

    candidate_files = sniff.get("candidate_files", [])
    if candidate_files:
        parts.append(f"**Top Files**: {len(candidate_files)} candidate(s)")
        for item in candidate_files[:3]:
            parts.append(f"  - `{item.get('path', '')}`")

    contract_summary = []
    related_feigns = sniff.get("related_feigns", [])
    if related_feigns:
        contract_summary.append(f"{len(related_feigns)} Feign")
    related_apis = sniff.get("related_apis", [])
    if related_apis:
        contract_summary.append(f"{len(related_apis)} API")
    related_mq = sniff.get("related_mq", [])
    if related_mq:
        contract_summary.append(f"{len(related_mq)} MQ")
    if contract_summary:
        parts.append(f"**Contracts**: {', '.join(contract_summary)}")

    rules = sniff.get("related_rules", [])
    if rules:
        parts.append(f"**Matched Rules**: {len(rules)}")

    cases = sniff.get("historical_cases", [])
    if cases:
        parts.append(f"**Historical Cases**: {len(cases)}")

    next_steps = sniff.get("next_steps", [])
    if next_steps:
        parts.append("")
        parts.append("## Next Steps")
        for step in next_steps[:4]:
            if isinstance(step, dict):
                parts.append(f"- {step.get('text', '') or step.get('description', '') or str(step)}")
            else:
                parts.append(f"- {step}")

    return "\n".join(parts)


def _render_task_current_summary_from_case(
    case: dict[str, Any],
    resolved_info: dict[str, Any],
    session_id: str,
) -> str:
    parts: list[str] = []
    parts.append("# Current Summary / 当前最短上下文")
    parts.append("")

    task = case.get("task", "")
    if task:
        parts.append(f"**Task**: {task}")

    task_title = resolved_info.get("title", "")
    task_id = resolved_info.get("task_id", "")
    if task_title:
        parts.append(f"**Task Space**: {task_title} (`{task_id}`)")

    projects = case.get("projects", [])
    if projects:
        parts.append(f"**Projects**: {', '.join(projects)}")

    files = case.get("files", [])
    if files:
        parts.append(f"**Files**: {len(files)} file(s)")
        for item in files[:5]:
            parts.append(f"  - `{item}`")

    flow = case.get("flow", "")
    if flow:
        parts.append(f"**Flow**: {flow}")

    risk_level = _case_risk_level(case)
    if risk_level:
        parts.append(f"**Risk Level**: {risk_level}")

    risk_points = case.get("risk_points", [])
    if risk_points:
        parts.append("")
        parts.append("## Risk Points")
        for point in risk_points[:5]:
            parts.append(f"- {point}")

    verified_by = case.get("verified_by", [])
    if verified_by:
        parts.append(f"**Verified By**: {', '.join(verified_by)}")

    parts.append(f"**Source Session**: {session_id}")

    return "\n".join(parts)
