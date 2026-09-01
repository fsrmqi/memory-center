from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from memory_center.core.foundation.schemas import with_schema

from ..tasks.artifacts import update_artifact
from ..tasks.receipts import build_write_receipt, persist_write_receipt, query_write_receipts
from ..tasks.timeline import timeline_query
from .rules import (
    _choose_l3_artifact_name,
    _load_write_policy_rules,
)
from .session import (
    workspace_log_session_event,
    workspace_suggest_case,
)
from .shared import (
    LAYER_L0,
    LAYER_L1,
    LAYER_L2,
    LAYER_L3,
    MEMORY_LAYER_ORDER,
    TOOL_WORKSPACE_ARTIFACT_UPDATE,
    TOOL_WORKSPACE_LOG_SESSION_EVENT,
    TOOL_WORKSPACE_RECORD_CASE,
    TOOL_WORKSPACE_START_SESSION,
    TOOL_WORKSPACE_SUGGEST_CASE,
    TOOL_WORKSPACE_SYNC_CASE_ARTIFACTS,
    TOOL_WORKSPACE_SYNC_SNIFF_ARTIFACTS,
    load_context,
)


def memory_write_judge(
    workspace_file: str | Path,
    text: str,
    source: str = "note",
    intent: str = "",
    prefer_layer: str = "",
    projects: list[str] | None = None,
    files: list[str] | None = None,
) -> dict[str, Any]:
    config, store = load_context(workspace_file)
    normalized_text = (text or "").strip().lower()
    normalized_intent = (intent or "").strip().lower()
    normalized_source = (source or "").strip().lower()
    preferred = (prefer_layer or "").strip().upper()

    layer_scores: dict[str, int] = {layer: 0 for layer in MEMORY_LAYER_ORDER}
    reasons: list[str] = []
    policy = _load_write_policy_rules(store)

    for layer, boost in (policy.get("source_layer_boosts", {}).get(normalized_source, {}) or {}).items():
        if layer in layer_scores:
            layer_scores[layer] += int(boost or 0)
    if normalized_source in (policy.get("source_layer_boosts", {}) or {}):
        reasons.append("来源命中了 write-policy-rules 的 source_layer_boosts。")

    for rule in policy.get("keyword_layer_boosts", []) or []:
        keywords = [str(item).lower() for item in rule.get("keywords", [])]
        if keywords and any(token in normalized_text for token in keywords):
            layer = str(rule.get("layer", "") or "")
            if layer in layer_scores:
                layer_scores[layer] += int(rule.get("score", 0) or 0)
                reasons.append(str(rule.get("reason", f"文本命中 {layer} 规则。")))

    for rule in policy.get("intent_layer_boosts", []) or []:
        keywords = [str(item).lower() for item in rule.get("keywords", [])]
        if normalized_intent and keywords and any(token in normalized_intent for token in keywords):
            layer = str(rule.get("layer", "") or "")
            if layer in layer_scores:
                layer_scores[layer] += int(rule.get("score", 0) or 0)
                reasons.append(str(rule.get("reason", f"意图命中 {layer} 规则。")))

    if projects:
        for layer, boost in (policy.get("projects_present_boosts", {}) or {}).items():
            if layer in layer_scores:
                layer_scores[layer] += int(boost or 0)
    if files:
        for layer, boost in (policy.get("files_present_boosts", {}) or {}).items():
            if layer in layer_scores:
                layer_scores[layer] += int(boost or 0)

    prefer_boost = int(policy.get("prefer_layer_boost", 3) or 3)
    if preferred in {"L0", "L0_SESSION_EVENTS"}:
        layer_scores[LAYER_L0] += prefer_boost
        reasons.append("用户偏好层级指向 L0。")
    if preferred in {"L1", "L1_CASE_ATOMS"}:
        layer_scores[LAYER_L1] += prefer_boost
        reasons.append("用户偏好层级指向 L1。")
    if preferred in {"L2", "L2_TASK_SPACES"}:
        layer_scores[LAYER_L2] += prefer_boost
        reasons.append("用户偏好层级指向 L2。")
    if preferred in {"L3", "L3_WORKSPACE_PROFILE"}:
        layer_scores[LAYER_L3] += prefer_boost
        reasons.append("用户偏好层级指向 L3。")

    ranked = sorted(layer_scores.items(), key=lambda item: item[1], reverse=True)
    selected_layer = ranked[0][0]
    top_score = ranked[0][1]
    second_score = ranked[1][1]
    confidence = "high" if top_score - second_score >= 3 else ("medium" if top_score - second_score >= 1 else "low")

    suggested_tool = TOOL_WORKSPACE_LOG_SESSION_EVENT
    suggested_action = "记录为会话事件（L0）"
    if selected_layer == LAYER_L1:
        suggested_tool = TOOL_WORKSPACE_RECORD_CASE
        suggested_action = "沉淀为可复用案例（L1）"
    elif selected_layer == LAYER_L2:
        suggested_tool = f"{TOOL_WORKSPACE_SYNC_SNIFF_ARTIFACTS} / {TOOL_WORKSPACE_SYNC_CASE_ARTIFACTS}"
        suggested_action = "同步到任务空间文档（L2）"
    elif selected_layer == LAYER_L3:
        suggested_tool = TOOL_WORKSPACE_ARTIFACT_UPDATE
        suggested_action = "写入工作区核心记忆块（L3）"

    return {
        "workspace": config.workspace,
        "input": {
            "source": source,
            "intent": intent,
            "prefer_layer": prefer_layer,
            "projects": projects or [],
            "files": files or [],
            "text_preview": text[:240],
        },
        "decision": {
            "selected_layer": selected_layer,
            "confidence": confidence,
            "layer_scores": layer_scores,
            "reasons": reasons[:8],
            "suggested_tool": suggested_tool,
            "suggested_action": suggested_action,
        },
    }


def memory_plan_write(
    workspace_file: str | Path,
    text: str,
    source: str = "note",
    intent: str = "",
    session_id: str = "",
    task_id: str = "",
    title: str = "",
    prefer_layer: str = "",
    projects: list[str] | None = None,
    files: list[str] | None = None,
) -> dict[str, Any]:
    config, _ = load_context(workspace_file)
    judge = memory_write_judge(
        workspace_file,
        text=text,
        source=source,
        intent=intent,
        prefer_layer=prefer_layer,
        projects=projects,
        files=files,
    )
    selected_layer = judge["decision"]["selected_layer"]
    steps: list[dict[str, Any]] = []

    if selected_layer == LAYER_L0:
        if session_id.strip():
            steps.append(
                {
                    "tool": TOOL_WORKSPACE_LOG_SESSION_EVENT,
                    "ready": True,
                    "purpose": "将信息作为会话事件写入 L0。",
                    "example_args": {
                        "session_id": session_id.strip(),
                        "event_type": source or "note",
                        "payload": {"text": text[:2000], "intent": intent},
                    },
                }
            )
        else:
            steps.append(
                {
                    "tool": TOOL_WORKSPACE_START_SESSION,
                    "ready": True,
                    "purpose": "缺少 session_id，先创建会话。",
                    "example_args": {"intent": intent or "写入记忆事件"},
                }
            )
            steps.append(
                {
                    "tool": TOOL_WORKSPACE_LOG_SESSION_EVENT,
                    "ready": False,
                    "purpose": "会话创建后写入事件。",
                    "required": ["session_id"],
                    "example_args": {"event_type": source or "note", "payload": {"text": text[:2000]}},
                }
            )
    elif selected_layer == LAYER_L1:
        ready = bool(projects and files)
        steps.append(
            {
                "tool": TOOL_WORKSPACE_RECORD_CASE,
                "ready": ready,
                "purpose": "将信息沉淀为 L1 案例。",
                "required": ([] if ready else ["projects", "files"]) + ([] if text.strip() else ["text/task"]),
                "example_args": {
                    "task": intent or "待补充任务标题",
                    "projects": projects or [],
                    "files": files or [],
                    "flow": "memory_write_judge -> record_case",
                    "risk_points": [text[:120]] if text.strip() else [],
                },
            }
        )
        if session_id.strip():
            steps.append(
                {
                    "tool": TOOL_WORKSPACE_SUGGEST_CASE,
                    "ready": True,
                    "purpose": "也可先用会话自动草拟 case 再确认入库。",
                    "example_args": {"session_id": session_id.strip()},
                }
            )
    elif selected_layer == LAYER_L2:
        if session_id.strip():
            steps.append(
                {
                    "tool": TOOL_WORKSPACE_SYNC_CASE_ARTIFACTS,
                    "ready": True,
                    "purpose": "从会话内容同步到 L2 任务空间（design/change-log/current-summary）。",
                    "example_args": {"session_id": session_id.strip(), "task_id": task_id.strip(), "title": title.strip()},
                }
            )
        else:
            steps.append(
                {
                    "tool": TOOL_WORKSPACE_SYNC_SNIFF_ARTIFACTS,
                    "ready": bool(intent.strip()),
                    "purpose": "从 intent 推导并同步到 L2 任务空间（context/plan/current-summary）。",
                    "required": [] if intent.strip() else ["intent"],
                    "example_args": {"intent": intent or text[:80], "task_id": task_id.strip(), "title": title.strip()},
                }
            )
    else:
        artifact_name = _choose_l3_artifact_name(text)
        steps.append(
            {
                "tool": TOOL_WORKSPACE_ARTIFACT_UPDATE,
                "ready": True,
                "purpose": "写入 L3 核心记忆块。",
                "example_args": {
                    "name": artifact_name,
                    "content": f"## Update\n\n{text[:2000]}",
                },
            }
        )

    return {
        "workspace": config.workspace,
        "memory_layer": selected_layer,
        "confidence": judge["decision"]["confidence"],
        "judge": judge["decision"],
        "plan": {
            "ready": all(bool(step.get("ready", False)) for step in steps),
            "steps": steps,
        },
    }


def memory_execute_write(
    workspace_file: str | Path,
    text: str,
    source: str = "note",
    intent: str = "",
    session_id: str = "",
    task_id: str = "",
    title: str = "",
    prefer_layer: str = "",
    projects: list[str] | None = None,
    files: list[str] | None = None,
) -> dict[str, Any]:
    from .session import workspace_start_session

    # lazy import to avoid circular deps
    from .sync import workspace_sync_case_to_artifacts, workspace_sync_sniff_to_artifacts

    plan_result = memory_plan_write(
        workspace_file,
        text=text,
        source=source,
        intent=intent,
        session_id=session_id,
        task_id=task_id,
        title=title,
        prefer_layer=prefer_layer,
        projects=projects,
        files=files,
    )
    executed: list[dict[str, Any]] = []
    current_session_id = session_id.strip()
    for step in plan_result.get("plan", {}).get("steps", []):
        tool = str(step.get("tool", "") or "")
        if tool == TOOL_WORKSPACE_START_SESSION:
            result = workspace_start_session(workspace_file, step.get("example_args", {}).get("intent", intent or "写入记忆事件"))
            current_session_id = str(result.get("session_id", "") or current_session_id)
            executed.append({"tool": tool, "result": result})
            continue
        if not step.get("ready", False):
            if tool == TOOL_WORKSPACE_LOG_SESSION_EVENT and current_session_id:
                result = workspace_log_session_event(
                    workspace_file,
                    current_session_id,
                    step.get("example_args", {}).get("event_type", source or "note"),
                    step.get("example_args", {}).get("payload", {"text": text[:2000], "intent": intent}),
                )
                executed.append({"tool": tool, "result": result, "auto_resolved": True})
                continue
            executed.append({"tool": tool, "skipped": True, "reason": "missing_required_args", "required": step.get("required", [])})
            continue
        if tool == TOOL_WORKSPACE_LOG_SESSION_EVENT:
            result = workspace_log_session_event(
                workspace_file,
                current_session_id or step.get("example_args", {}).get("session_id", ""),
                step.get("example_args", {}).get("event_type", source or "note"),
                step.get("example_args", {}).get("payload", {"text": text[:2000], "intent": intent}),
            )
        elif tool == TOOL_WORKSPACE_RECORD_CASE:
            result = workspace_record_case(
                workspace_file,
                step.get("example_args", {}).get("task", intent or text[:80] or "memory_execute_write"),
                step.get("example_args", {}).get("projects", projects or []),
                step.get("example_args", {}).get("files", files or []),
                flow=step.get("example_args", {}).get("flow", "memory_write_judge -> memory_plan_write -> memory_execute_write"),
                risk_points=step.get("example_args", {}).get("risk_points", [text[:120]] if text.strip() else []),
                source_session_id=current_session_id,
                source_task_id=task_id.strip(),
            )
        elif tool == TOOL_WORKSPACE_SUGGEST_CASE:
            result = workspace_suggest_case(workspace_file, current_session_id or step.get("example_args", {}).get("session_id", ""))
        elif tool == TOOL_WORKSPACE_SYNC_CASE_ARTIFACTS:
            result = workspace_sync_case_to_artifacts(
                workspace_file,
                current_session_id or step.get("example_args", {}).get("session_id", ""),
                task_id=step.get("example_args", {}).get("task_id", task_id.strip()),
                title=step.get("example_args", {}).get("title", title.strip()),
            )
        elif tool == TOOL_WORKSPACE_SYNC_SNIFF_ARTIFACTS:
            result = workspace_sync_sniff_to_artifacts(
                workspace_file,
                step.get("example_args", {}).get("intent", intent or text[:80]),
                task_id=step.get("example_args", {}).get("task_id", task_id.strip()),
                title=step.get("example_args", {}).get("title", title.strip()),
            )
        elif tool == TOOL_WORKSPACE_ARTIFACT_UPDATE:
            result = update_artifact(
                workspace_file,
                step.get("example_args", {}).get("name", "workspace_profile"),
                step.get("example_args", {}).get("content", f"## Update\n\n{text[:2000]}"),
            )
        else:
            executed.append({"tool": tool, "skipped": True, "reason": "unsupported_tool"})
            continue
        executed.append({"tool": tool, "result": result})
    return {
        "workspace": plan_result.get("workspace"),
        "memory_layer": plan_result.get("memory_layer"),
        "confidence": plan_result.get("confidence"),
        "judge": plan_result.get("judge"),
        "executed": executed,
        "write_receipts": [item["result"].get("write_receipt") for item in executed if isinstance(item.get("result"), dict) and item["result"].get("write_receipt")],
        "session_id": current_session_id,
    }


def workspace_record_case(
    workspace_file: str | Path,
    task: str,
    projects: list[str],
    files: list[str],
    flow: str = "",
    risk_points: list[str] | None = None,
    verified_by: list[str] | None = None,
    source_session_id: str = "",
    source_task_id: str = "",
    source_refs: list[dict[str, Any]] | None = None,
    valid_from: str = "",
    valid_to: str = "",
    superseded_by: str = "",
    current_truth: bool = True,
    extra_fields: dict[str, Any] | None = None,
    case_type: str = "engineering_case",
) -> dict[str, Any]:
    """记录一条已验证的 L1 case 原子。

    extra_fields 可携带 schema 声明的扩展字段(situation/approach/reflect/
    executions/successes 等);record 前按 `rules/case-schemas.yaml`(缺省用
    内置 engineering_case schema)做纯函数校验,校验失败不阻断写入,只把
    schema_validation 作为可读结果返回,保持对既有调用方的兼容。
    """
    _, store = load_context(workspace_file)
    from memory_center.core.knowledge.case_schema import load_case_registry, validate_case_draft

    item = {
        "task": task,
        "projects": projects,
        "files": files,
        "flow": flow,
        "risk_points": risk_points or [],
        "verified_by": verified_by or [],
        "memory_layer": "L1_case_atom",
        "source_session_id": source_session_id.strip(),
        "source_task_id": source_task_id.strip(),
        "source_refs": source_refs or [],
        "valid_from": valid_from.strip() or datetime.now(timezone.utc).isoformat(),
        "valid_to": valid_to.strip(),
        "superseded_by": superseded_by.strip(),
        "current_truth": bool(current_truth) and not superseded_by.strip() and not valid_to.strip(),
    }
    extras = extra_fields if isinstance(extra_fields, dict) else {}
    schema = load_case_registry(store).get(case_type)
    item["case_type"] = schema.case_type
    known_extra = {name: value for name, value in extras.items() if schema.field(name) is not None}
    item.update(known_extra)
    schema_validation = validate_case_draft(item, schema)
    if schema_validation.get("warnings"):
        item["schema_warnings"] = schema_validation["warnings"][:5]
    store.append_jsonl("cross-service-task-memory.jsonl", item)
    receipt = persist_write_receipt(
        store,
        build_write_receipt(
            layer=LAYER_L1,
            action=TOOL_WORKSPACE_RECORD_CASE,
            scope="memory",
            target="cross-service-task-memory.jsonl",
            target_file="memory/cross-service-task-memory.jsonl",
            source_session_id=item.get("source_session_id", ""),
            task_id=item.get("source_task_id", ""),
        ),
    )
    return {
        "recorded": True,
        "case": item,
        "write_receipt": receipt,
        "schema_validation": schema_validation,
    }


def workspace_write_receipts(
    workspace_file: str | Path,
    layer: str = "",
    action: str = "",
    scope: str = "",
    task_id: str = "",
    session_id: str = "",
    limit: int = 50,
) -> dict[str, Any]:
    config, _ = load_context(workspace_file)
    return {
        "workspace": config.workspace,
        **query_write_receipts(
            str(workspace_file),
            layer=layer,
            action=action,
            scope=scope,
            task_id=task_id,
            session_id=session_id,
            limit=limit,
        ),
    }


def workspace_replay_write_chain(
    workspace_file: str | Path,
    task_id: str = "",
    session_id: str = "",
    limit: int = 100,
) -> dict[str, Any]:
    config, _ = load_context(workspace_file)
    result = timeline_query(str(workspace_file), task_id=task_id, session_id=session_id, kinds=["write_receipt", "handoff"], limit=limit)
    receipts = result.get("timeline", [])
    timeline = [
        {
            "index": idx + 1,
            "layer": row.get("layer", ""),
            "action": row.get("action", ""),
            "scope": row.get("scope", ""),
            "target": row.get("target", ""),
            "task_id": row.get("task_id", ""),
            "session_id": row.get("session_id", ""),
            "receipt_ref": row.get("receipt_ref", ""),
            "kind": row.get("kind", ""),
            "created_at": row.get("created_at", ""),
        }
        for idx, row in enumerate(receipts)
    ]
    return with_schema(
        "timeline_result",
        {
            "workspace": config.workspace,
            "task_id": task_id,
            "session_id": session_id,
            "timeline": timeline,
            "summary": {
                **result.get("summary", {}),
                "timeline_count": len(timeline),
            },
            "filters": {
                "task_id": task_id,
                "session_id": session_id,
                "kinds": ["write_receipt", "handoff"],
                "limit": limit,
            },
        },
    )
