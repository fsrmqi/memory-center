from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from ..evals import EvalResultBuilder
from ..schemas import with_schema
from ..semantic import semantic_index_stats
from ..token_utils import estimate_tokens
from .common import (
    LAYER_L0,
    LAYER_L1,
    LAYER_L2,
    LAYER_L3,
    _load_eval_rules,
    load_context,
)
from .write import workspace_replay_write_chain


def memory_eval_write_quality(
    workspace_file: str | Path,
    task_id: str = "",
    session_id: str = "",
    intent: str = "",
    limit: int = 100,
) -> Dict[str, Any]:
    config, store = load_context(workspace_file)
    replay = workspace_replay_write_chain(workspace_file, task_id=task_id, session_id=session_id, limit=limit)
    receipts = replay.get("timeline", [])
    layers = {item.get("layer", "") for item in receipts}
    builder = EvalResultBuilder()
    penalties = (_load_eval_rules(store).get("write_quality", {}) or {}).get("penalties", {})
    rule_keywords = [str(item).lower() for item in ((_load_eval_rules(store).get("write_quality", {}) or {}).get("rule_intent_keywords", []) or [])]

    has_l0 = LAYER_L0 in layers
    has_l1 = LAYER_L1 in layers
    has_l2 = LAYER_L2 in layers
    has_l3 = LAYER_L3 in layers

    if session_id and not has_l0:
        builder.add("medium", "missing_l0", "存在 session_id，但没有对应的 L0 会话事件写入。", int(penalties.get("missing_l0", 20)))
    if task_id and not has_l2:
        builder.add("high", "missing_l2", "存在 task_id，但没有对应的 L2 任务空间写入。", int(penalties.get("missing_l2", 30)))
    if session_id and not has_l1:
        builder.add("medium", "missing_l1", "存在 session_id，但没有沉淀为 L1 case memory。", int(penalties.get("missing_l1", 15)))
    if any(keyword in intent.lower() for keyword in rule_keywords):
        if not has_l3:
            builder.add("medium", "missing_l3", "意图看起来属于规则/规范类，但没有对应的 L3 核心记忆块写入。", int(penalties.get("missing_l3", 20)))
    if not receipts:
        builder.add("high", "no_receipts", "没有找到任何 write receipts，无法证明记忆写入链路已执行。", int(penalties.get("no_receipts", 100)))

    return builder.finalize(
        workspace=config.workspace,
        task_id=task_id,
        session_id=session_id,
        intent=intent,
        receipt_count=len(receipts),
        layers_present=sorted(layer for layer in layers if layer),
        replay_summary=replay.get("summary", {}),
    )


def memory_eval_resume(
    workspace_file: str | Path,
    task_id: str = "",
    session_id: str = "",
    intent: str = "",
    limit: int = 20,
) -> Dict[str, Any]:
    from .resume import workspace_resume_packet  # lazy import

    config, store = load_context(workspace_file)
    packet = workspace_resume_packet(workspace_file, task_id=task_id, session_id=session_id, intent=intent, limit=limit)
    builder = EvalResultBuilder()
    penalties = (_load_eval_rules(store).get("resume", {}) or {}).get("penalties", {})

    if not packet.get("current_summary"):
        builder.add("high", "missing_current_summary", "恢复包缺少 current_summary。", int(penalties.get("missing_current_summary", 30)))
    if not packet.get("next_recommended_actions"):
        builder.add("medium", "missing_next_actions", "恢复包缺少 next_recommended_actions。", int(penalties.get("missing_next_actions", 20)))
    if "unresolved_items" not in packet:
        builder.add("medium", "missing_unresolved_items", "恢复包缺少 unresolved_items。", int(penalties.get("missing_unresolved_items", 15)))
    if packet.get("verification_pending") and not packet.get("unresolved_items"):
        builder.add("low", "verification_flag_without_items", "verification_pending 为真，但没有明确未解决事项。", int(penalties.get("verification_flag_without_items", 10)))
    if not packet.get("resume_rule_profile"):
        builder.add("low", "missing_resume_rule_profile", "恢复包未声明命中的规则画像。", int(penalties.get("missing_resume_rule_profile", 10)))

    return builder.finalize(
        workspace=config.workspace,
        task_id=packet.get("task_id", ""),
        session_id=session_id,
        intent=intent,
        resume_rule_profile=packet.get("resume_rule_profile", ""),
    )


def memory_eval_handoff(
    workspace_file: str | Path,
    target_model: str,
    task_id: str = "",
    session_id: str = "",
    intent: str = "",
    limit: int = 20,
) -> Dict[str, Any]:
    from .resume import workspace_handoff_packet  # lazy import

    config, store = load_context(workspace_file)
    packet = workspace_handoff_packet(
        workspace_file,
        target_model=target_model,
        task_id=task_id,
        session_id=session_id,
        intent=intent,
        limit=limit,
    )
    handoff_body = packet.get("handoff_packet", {})
    builder = EvalResultBuilder()
    penalties = (_load_eval_rules(store).get("handoff", {}) or {}).get("penalties", {})

    if not handoff_body.get("minimal_required_context"):
        builder.add("high", "missing_minimal_context", "交接包缺少 minimal_required_context。", int(penalties.get("missing_minimal_context", 30)))
    if not handoff_body.get("what_to_check_next"):
        builder.add("medium", "missing_next_checks", "交接包缺少 what_to_check_next。", int(penalties.get("missing_next_checks", 20)))
    if not handoff_body.get("what_not_to_repeat"):
        builder.add("medium", "missing_do_not_repeat", "交接包缺少 what_not_to_repeat。", int(penalties.get("missing_do_not_repeat", 15)))
    if not packet.get("handoff_rule_profile"):
        builder.add("low", "missing_handoff_rule_profile", "交接包未声明命中的 handoff 规则画像。", int(penalties.get("missing_handoff_rule_profile", 10)))
    if not packet.get("model_profile", {}).get("normalized_model"):
        builder.add("low", "missing_model_profile", "交接包缺少标准化模型画像。", int(penalties.get("missing_model_profile", 10)))

    return builder.finalize(
        workspace=config.workspace,
        target_model=target_model,
        task_id=packet.get("task_id", ""),
        session_id=session_id,
        handoff_rule_profile=packet.get("handoff_rule_profile", ""),
        normalized_model=packet.get("model_profile", {}).get("normalized_model", ""),
    )


def memory_eval_regression_suite(
    workspace_file: str | Path,
    *,
    task_id: str = "",
    session_id: str = "",
    intent: str = "",
    target_model: str = "codex",
    limit: int = 20,
) -> Dict[str, Any]:
    config, _ = load_context(workspace_file)
    write_eval = memory_eval_write_quality(workspace_file, task_id=task_id, session_id=session_id, intent=intent, limit=limit)
    resume_eval = memory_eval_resume(workspace_file, task_id=task_id, session_id=session_id, intent=intent, limit=limit)
    handoff_eval = memory_eval_handoff(
        workspace_file,
        target_model=target_model,
        task_id=task_id,
        session_id=session_id,
        intent=intent,
        limit=limit,
    )
    components = {
        "write_quality": write_eval,
        "resume": resume_eval,
        "handoff": handoff_eval,
    }
    scores = [int(item.get("score", 0) or 0) for item in components.values()]
    avg_score = int(sum(scores) / len(scores)) if scores else 0
    suite = with_schema(
        "eval_result",
        {
            "workspace": config.workspace,
            "score": avg_score,
            "quality": "high" if avg_score >= 85 else ("medium" if avg_score >= 60 else "low"),
            "findings": [finding for result in components.values() for finding in result.get("findings", [])],
            "components": components,
            "suite_name": "memory_eval_regression_suite",
            "target_model": target_model,
        },
    )
    return suite


def memory_eval_index_freshness(
    workspace_file: str | Path,
    scope: str = "all",
) -> Dict[str, Any]:
    from .impact import memory_detect_changes  # lazy import

    config, store = load_context(workspace_file)
    builder = EvalResultBuilder()
    changed = memory_detect_changes(workspace_file, scope=scope)
    changed_files = changed.get("changed_files", []) or []
    semantic = semantic_index_stats(workspace_file)
    index_files = [
        store.index_dir / "file-index.json",
        store.index_dir / "java-symbol-index.json",
        store.index_dir / "api-index.json",
        store.index_dir / "feign-index.json",
        store.index_dir / "mq-index.json",
        store.index_dir / "config-index.json",
        store.index_dir / "service-topology.json",
        store.index_dir / "semantic-node-index.json",
        store.graph_dir / "graph.db",
    ]
    existing = [path for path in index_files if path.exists()]
    latest_index_mtime = max((path.stat().st_mtime for path in existing), default=0.0)
    stale_changed_files = []
    for rel in changed_files[:200]:
        matched = next((row for row in store.read_json_prefer_backend("file-index.json", []) if row.get("path") == rel), None)
        abs_path = Path(matched.get("abs_path", "")) if matched and matched.get("abs_path") else None
        if abs_path and abs_path.exists() and abs_path.stat().st_mtime > latest_index_mtime:
            stale_changed_files.append(rel)
    if changed_files and stale_changed_files:
        builder.add("high", "stale_index_after_changes", "存在变更文件比当前索引更新，建议执行增量或全量 reindex。", 35)
    if not semantic.get("ready"):
        builder.add("medium", "semantic_not_ready", "语义索引未就绪，query/context/impact 的召回质量会下降。", 20)
    if not existing:
        builder.add("high", "missing_index_files", "未发现任何索引文件，workspace 处于未初始化索引状态。", 100)
    return builder.finalize(
        workspace=config.workspace,
        scope=scope,
        changed_file_count=len(changed_files),
        stale_changed_files=stale_changed_files[:20],
        semantic_index=semantic,
        latest_index_mtime=latest_index_mtime,
    )


def memory_eval_tool_adoption(
    workspace_file: str | Path,
    limit: int = 200,
) -> Dict[str, Any]:
    from .query import memory_tool_usage_report  # lazy import

    config, _ = load_context(workspace_file)
    report = memory_tool_usage_report(workspace_file, limit=limit)
    summary = report.get("summary", {}) or {}
    builder = EvalResultBuilder()
    if float(summary.get("memory_center_ratio", 0.0)) < 0.25 and int(summary.get("total_tool_calls", 0)) > 0:
        builder.add("medium", "low_memory_center_ratio", "近期工具调用中 Memory Center 占比较低，模型可能仍主要依赖本地搜索。", 25)
    if int(summary.get("lookup_tool_total", 0)) == 0 and int(summary.get("total_tool_calls", 0)) > 0:
        builder.add("medium", "no_lookup_tool_usage", "近期没有使用 Memory Center lookup 工具，类/符号检索可能未按协议走。", 20)
    if int(summary.get("suspected_bypass_count", 0)) > 0:
        builder.add("high", "suspected_bypass_detected", "检测到疑似绕过 Memory Center 的检索行为。", min(40, int(summary.get("suspected_bypass_count", 0)) * 10))
    return builder.finalize(
        workspace=config.workspace,
        usage_report=report,
        total_tool_calls=summary.get("total_tool_calls", 0),
        memory_center_ratio=summary.get("memory_center_ratio", 0.0),
    )


def memory_eval_workflow_orchestration(
    workspace_file: str | Path,
    task_id: str = "",
    session_id: str = "",
    intent: str = "",
    limit: int = 20,
) -> Dict[str, Any]:
    from .evals import eval_workflow_orchestration
    from .session import workspace_recent_evidence

    config, store = load_context(workspace_file)
    evidence = workspace_recent_evidence(workspace_file, task_id=task_id, session_id=session_id, limit=limit, budget="large")
    events = evidence.get("evidence", [])
    return eval_workflow_orchestration(events, intent=intent)


def memory_eval_context_weight(
    workspace_file: str | Path,
    intent: str = "",
    limit: int = 8,
) -> Dict[str, Any]:
    from .resume import workspace_resume_packet  # lazy import
    from .workspace import workspace_dashboard, workspace_sniff  # lazy import

    config, _ = load_context(workspace_file)
    sniff_small = workspace_sniff(workspace_file, intent or "context weight", limit=limit, view="compact", budget="small")
    sniff_large = workspace_sniff(workspace_file, intent or "context weight", limit=limit, view="compact", budget="large")
    resume_small = workspace_resume_packet(workspace_file, intent=intent, limit=limit, view="compact", budget="small")
    dashboard_small = workspace_dashboard(workspace_file, intent=intent, limit=limit, view="compact", budget="small")
    builder = EvalResultBuilder()
    sniff_small_chars = len(json.dumps(sniff_small, ensure_ascii=False))
    sniff_large_chars = len(json.dumps(sniff_large, ensure_ascii=False))
    resume_small_chars = len(json.dumps(resume_small, ensure_ascii=False))
    dashboard_small_chars = len(json.dumps(dashboard_small, ensure_ascii=False))
    sniff_small_tokens = estimate_tokens(json.dumps(sniff_small, ensure_ascii=False))
    sniff_large_tokens = estimate_tokens(json.dumps(sniff_large, ensure_ascii=False))
    resume_small_tokens = estimate_tokens(json.dumps(resume_small, ensure_ascii=False))
    dashboard_small_tokens = estimate_tokens(json.dumps(dashboard_small, ensure_ascii=False))
    # Also get full-view token counts for savings comparison
    sniff_full = workspace_sniff(workspace_file, intent or "context weight", limit=limit, view="full", budget="large")
    sniff_full_tokens = estimate_tokens(json.dumps(sniff_full, ensure_ascii=False))
    sniff_savings_pct = round((1 - sniff_small_tokens / (sniff_full_tokens or 1)) * 100, 1)
    resume_full = workspace_resume_packet(workspace_file, intent=intent, limit=limit, view="full", budget="medium")
    resume_full_tokens = estimate_tokens(json.dumps(resume_full, ensure_ascii=False))
    resume_savings_pct = round((1 - resume_small_tokens / (resume_full_tokens or 1)) * 100, 1)
    dashboard_full = workspace_dashboard(workspace_file, intent=intent, limit=limit, view="full", budget="medium")
    dashboard_full_tokens = estimate_tokens(json.dumps(dashboard_full, ensure_ascii=False))
    dashboard_savings_pct = round((1 - dashboard_small_tokens / (dashboard_full_tokens or 1)) * 100, 1)
    if sniff_small_chars > 4500:
        builder.add("medium", "sniff_small_too_heavy", "sniff 在 small budget 下仍偏重，建议继续压缩字段或条目数。", 20)
    if resume_small_chars > 2800:
        builder.add("medium", "resume_small_too_heavy", "resume packet 在 small budget 下仍偏重。", 15)
    if dashboard_small_chars > 5200:
        builder.add("medium", "dashboard_small_too_heavy", "workspace dashboard 在 small budget 下仍偏重。", 20)
    if sniff_large_chars <= sniff_small_chars:
        builder.add("low", "budget_not_effective", "budget small/large 的输出规模没有明显拉开。", 10)
    if sniff_savings_pct < 40:
        builder.add("low", "sniff_savings_low", f"sniff compact 只省了 {sniff_savings_pct}% token，压缩效果不足。", 10)
    if resume_savings_pct < 40:
        builder.add("low", "resume_savings_low", f"resume compact 只省了 {resume_savings_pct}% token，压缩效果不足。", 10)
    return builder.finalize(
        workspace=config.workspace,
        intent=intent,
        sniff_small_chars=sniff_small_chars,
        sniff_large_chars=sniff_large_chars,
        resume_small_chars=resume_small_chars,
        dashboard_small_chars=dashboard_small_chars,
        sniff_small_tokens=sniff_small_tokens,
        sniff_large_tokens=sniff_large_tokens,
        sniff_full_tokens=sniff_full_tokens,
        sniff_savings_pct=sniff_savings_pct,
        resume_small_tokens=resume_small_tokens,
        resume_full_tokens=resume_full_tokens,
        resume_savings_pct=resume_savings_pct,
        dashboard_small_tokens=dashboard_small_tokens,
        dashboard_full_tokens=dashboard_full_tokens,
        dashboard_savings_pct=dashboard_savings_pct,
    )


def memory_eval_token_gain(
    workspace_file: str | Path,
    *,
    tool_name: str = "",
    budget: str = "",
    model: str = "",
    limit: int = 200,
) -> Dict[str, Any]:
    """Evaluate token savings from compact operations, similar to rtk's gain command."""
    from ..tracking import query_token_gain

    config, _ = load_context(workspace_file)
    gain_report = query_token_gain(
        workspace_file,
        tool_name=tool_name,
        budget=budget,
        model=model,
        limit=limit,
    )
    builder = EvalResultBuilder()
    overall_pct = gain_report.get("overall_savings_pct", 0)
    if overall_pct < 30 and gain_report.get("total_records", 0) > 5:
        builder.add("medium", "low_overall_savings", f"整体 compact savings 仅 {overall_pct}%，压缩效果不足。", 20)
    if gain_report.get("total_records", 0) == 0:
        builder.add("low", "no_gain_records", "尚未有任何 compact gain 记录，compact 视图可能未被调用。", 10)
    bottom = gain_report.get("bottom_5_savings", [])
    for entry in bottom[:3]:
        if entry.get("avg_savings_pct", 100) < 30:
            builder.add("low", f"low_savings_{entry.get('tool', '')}", f"{entry.get('tool')} compact 平均省 {entry.get('avg_savings_pct')}% token。", 10)
    return builder.finalize(
        workspace=config.workspace,
        overall_savings_pct=overall_pct,
        total_records=gain_report.get("total_records", 0),
        total_saved_tokens=gain_report.get("total_saved_tokens", 0),
        per_tool_stats=gain_report.get("per_tool_stats", {}),
        top_5_savings=gain_report.get("top_5_savings", []),
        bottom_5_savings=gain_report.get("bottom_5_savings", []),
    )
