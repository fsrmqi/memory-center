from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from memory_center.core.storage.workspace import WorkspaceStore


def export_mermaid(workspace_file: str | Path) -> str:
    """Export a coarse service topology diagram in Mermaid format."""
    store = WorkspaceStore(workspace_file)
    topology = store.read_json_prefer_backend("service-topology.json", {})
    lines: list[str] = ["flowchart LR"]

    services = topology.get("services", [])
    for svc in services:
        name = _node(svc.get("name") or svc.get("service_name") or "unknown")
        label = svc.get("name") or svc.get("service_name") or "unknown"
        lines.append(f'  {name}["{label}"]')

    for edge in topology.get("feign_edges", []):
        src = _node(edge.get("caller_project") or edge.get("from_project") or "unknown")
        dst = _node(edge.get("target_service") or edge.get("to_service") or edge.get("to_project") or "unknown")
        label = edge.get("client", "Feign")
        lines.append(f'  {src} -- "Feign: {label}" --> {dst}')

    mq_topics = topology.get("mq_topics", {})
    topic_items = (
        mq_topics.items() if isinstance(mq_topics, dict) else [(x.get("topic", "unknown"), x) for x in mq_topics]
    )
    for topic, data in topic_items:
        topic_node = _node(f"topic_{topic}")
        lines.append(f'  {topic_node}(["Topic: {topic}"])')
        for producer in data.get("producers", []):
            producer_project = producer.get("project") if isinstance(producer, dict) else str(producer)
            lines.append(f'  {_node(producer_project)} -- "produce" --> {topic_node}')
        for consumer in data.get("consumers", []):
            consumer_project = consumer.get("project") if isinstance(consumer, dict) else str(consumer)
            lines.append(f'  {topic_node} -- "consume" --> {_node(consumer_project)}')

    return "\n".join(lines) + "\n"


def topology_summary(workspace_file: str | Path) -> dict[str, Any]:
    store = WorkspaceStore(workspace_file)
    topology = store.read_json_prefer_backend("service-topology.json", {})
    return {
        "service_count": len(topology.get("services", [])),
        "feign_edge_count": len(topology.get("feign_edges", [])),
        "mq_topic_count": len(topology.get("mq_topics", [])),
        "services": topology.get("services", []),
    }


def export_workspace_dashboard_markdown(workspace_file: str | Path, intent: str = "", limit: int = 10) -> str:
    from memory_center.core.orchestrator import workspace_dashboard

    dashboard = workspace_dashboard(workspace_file, intent=intent, limit=limit)
    lines: list[str] = [
        "# Workspace Dashboard / 工作区总面板",
        "",
        f"- Workspace: {dashboard.get('workspace', '')}",
        f"- Focus task: {(dashboard.get('focus_task') or {}).get('title', '') or (dashboard.get('focus_task') or {}).get('task_id', 'None')}",
        f"- Active tasks: {len(dashboard.get('active_tasks', []))}",
        f"- Resumable tasks: {len(dashboard.get('resumable_tasks', []))}",
        f"- Blocked tasks: {len(dashboard.get('blocked_tasks', []))}",
        "",
        "## Focus Resume Eval",
        "",
    ]
    focus_eval = dashboard.get("focus_resume_eval") or {}
    if focus_eval:
        lines.extend(
            [
                f"- Quality: {focus_eval.get('quality', '')}",
                f"- Score: {focus_eval.get('score', 0)}",
                f"- Resume rule profile: {focus_eval.get('resume_rule_profile', '')}",
            ]
        )
    else:
        lines.append("- None")
    lines.extend(["", "## Active Tasks", ""])
    lines.extend(_render_task_lines(dashboard.get("active_tasks", [])) or ["- None"])
    lines.extend(["", "## Low Quality Tasks", ""])
    lines.extend(_render_task_lines(dashboard.get("low_quality_tasks", [])) or ["- None"])
    lines.extend(["", "## Recent Handoffs", ""])
    lines.extend(_render_handoff_lines(dashboard.get("recent_handoffs", [])) or ["- None"])
    lines.extend(["", "## Recent Receipts", ""])
    lines.extend(_render_receipt_lines(dashboard.get("recent_receipts", [])) or ["- None"])
    return "\n".join(lines).rstrip() + "\n"
def _node(value: str) -> str:
    return "n_" + "".join(ch if ch.isalnum() else "_" for ch in value)


def _render_task_lines(tasks: list[dict[str, Any]]) -> list[str]:
    return [
        f"- {item.get('title', item.get('task_id', ''))} | status={item.get('status', '')} | quality={item.get('quality', '')} | score={item.get('score', '')}"
        for item in tasks
    ]


def _render_handoff_lines(rows: list[dict[str, Any]]) -> list[str]:
    return [
        f"- {item.get('normalized_model', '')} | phase={item.get('current_phase', '')} | quality={item.get('quality', '')} | score={item.get('score', '')}"
        for item in rows
    ]


def _render_receipt_lines(rows: list[dict[str, Any]]) -> list[str]:
    return [f"- {item.get('layer', '')} | {item.get('action', '')} | {item.get('target', '')}" for item in rows]


    if not rows:
        return "<div class='muted'>None</div>"
    items = "".join(
        f"<li><strong>{html.escape(str(item.get('normalized_model', '')))}</strong> "
        f"<span class='chip'>phase={html.escape(str(item.get('current_phase', '')))}</span> "
        f"<span class='chip'>quality={html.escape(str(item.get('quality', '')))}</span>"
        f"<details><summary>Expand / 展开</summary><pre>{html.escape(json.dumps(item, ensure_ascii=False, indent=2))}</pre></details></li>"
        for item in rows
    )
    return f"<ul>{items}</ul>"


    if not rows:
        return "<div class='muted'>None</div>"
    return "<ul>" + "".join(f"<li>{html.escape(str(item))}</li>" for item in rows) + "</ul>"


