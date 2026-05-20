from __future__ import annotations

import html
from pathlib import Path
from typing import Any, Dict, List

from .store import WorkspaceStore


def export_mermaid(workspace_file: str | Path) -> str:
    """Export a coarse service topology diagram in Mermaid format."""
    store = WorkspaceStore(workspace_file)
    topology = store.read_json("service-topology.json", {})
    lines: List[str] = ["flowchart LR"]

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
    topic_items = mq_topics.items() if isinstance(mq_topics, dict) else [(x.get("topic", "unknown"), x) for x in mq_topics]
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


def topology_summary(workspace_file: str | Path) -> Dict[str, Any]:
    store = WorkspaceStore(workspace_file)
    topology = store.read_json("service-topology.json", {})
    return {
        "service_count": len(topology.get("services", [])),
        "feign_edge_count": len(topology.get("feign_edges", [])),
        "mq_topic_count": len(topology.get("mq_topics", {})),
        "services": topology.get("services", []),
    }


def export_workspace_dashboard_markdown(workspace_file: str | Path, intent: str = "", limit: int = 10) -> str:
    from .orchestrator import workspace_dashboard

    dashboard = workspace_dashboard(workspace_file, intent=intent, limit=limit)
    lines: List[str] = [
        f"# Workspace Dashboard / 工作区总面板",
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


def export_workspace_dashboard_html(workspace_file: str | Path, intent: str = "", limit: int = 10) -> str:
    from .orchestrator import workspace_dashboard

    dashboard = workspace_dashboard(workspace_file, intent=intent, limit=limit)
    focus_task = dashboard.get("focus_task") or {}
    focus_eval = dashboard.get("focus_resume_eval") or {}
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Workspace Dashboard</title>
  <style>
    :root {{
      --bg: #f6f1e8;
      --panel: #fffdf8;
      --ink: #1d1a16;
      --muted: #6d6357;
      --line: #d8cdbf;
      --accent: #8c4b2f;
      --accent-2: #2f6b5a;
    }}
    body {{ margin: 0; font-family: Georgia, 'Noto Serif SC', serif; background: linear-gradient(180deg, #efe6d8, var(--bg)); color: var(--ink); }}
    .wrap {{ max-width: 1180px; margin: 0 auto; padding: 28px; }}
    .hero {{ padding: 24px; background: var(--panel); border: 1px solid var(--line); border-radius: 18px; box-shadow: 0 12px 30px rgba(0,0,0,.05); }}
    h1,h2 {{ margin: 0 0 12px; }}
    .meta {{ color: var(--muted); display: flex; gap: 18px; flex-wrap: wrap; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit,minmax(260px,1fr)); gap: 18px; margin-top: 20px; }}
    .card {{ background: var(--panel); border: 1px solid var(--line); border-radius: 18px; padding: 18px; }}
    .chip {{ display:inline-block; padding:4px 10px; border-radius:999px; background:#f0e3d4; color:var(--accent); font-size:12px; margin-right:8px; }}
    ul {{ padding-left: 18px; margin: 10px 0 0; }}
    li {{ margin: 6px 0; }}
    .score {{ color: var(--accent-2); font-weight: 700; }}
    .muted {{ color: var(--muted); }}
  </style>
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <h1>Workspace Dashboard</h1>
      <div class="meta">
        <span>Workspace: {html.escape(str(dashboard.get('workspace', '')))}</span>
        <span>Focus: {html.escape(str(focus_task.get('title', '') or focus_task.get('task_id', 'None')))}</span>
        <span>Active: {len(dashboard.get('active_tasks', []))}</span>
        <span>Blocked: {len(dashboard.get('blocked_tasks', []))}</span>
      </div>
    </section>
    <div class="grid">
      <section class="card">
        <h2>Focus Resume Eval</h2>
        <div class="muted">Rule: {html.escape(str(focus_eval.get('resume_rule_profile', '')))}</div>
        <div class="score">Quality: {html.escape(str(focus_eval.get('quality', '')))} / Score: {html.escape(str(focus_eval.get('score', '')))}</div>
      </section>
      <section class="card">
        <h2>Active Tasks</h2>
        {_render_task_list_html(dashboard.get('active_tasks', []))}
      </section>
      <section class="card">
        <h2>Low Quality Tasks</h2>
        {_render_task_list_html(dashboard.get('low_quality_tasks', []))}
      </section>
      <section class="card">
        <h2>Recent Handoffs</h2>
        {_render_handoff_list_html(dashboard.get('recent_handoffs', []))}
      </section>
      <section class="card">
        <h2>Recent Receipts</h2>
        {_render_receipt_list_html(dashboard.get('recent_receipts', []))}
      </section>
    </div>
  </div>
</body>
</html>
"""


def _node(value: str) -> str:
    return "n_" + "".join(ch if ch.isalnum() else "_" for ch in value)


def _render_task_lines(tasks: List[Dict[str, Any]]) -> List[str]:
    return [
        f"- {item.get('title', item.get('task_id', ''))} | status={item.get('status', '')} | quality={item.get('quality', '')} | score={item.get('score', '')}"
        for item in tasks
    ]


def _render_handoff_lines(rows: List[Dict[str, Any]]) -> List[str]:
    return [
        f"- {item.get('normalized_model', '')} | phase={item.get('current_phase', '')} | quality={item.get('quality', '')} | score={item.get('score', '')}"
        for item in rows
    ]


def _render_receipt_lines(rows: List[Dict[str, Any]]) -> List[str]:
    return [
        f"- {item.get('layer', '')} | {item.get('action', '')} | {item.get('target', '')}"
        for item in rows
    ]


def _render_task_list_html(tasks: List[Dict[str, Any]]) -> str:
    if not tasks:
        return "<div class='muted'>None</div>"
    items = "".join(
        f"<li><strong>{html.escape(str(item.get('title', item.get('task_id', ''))))}</strong> "
        f"<span class='chip'>{html.escape(str(item.get('status', '')))}</span> "
        f"<span class='chip'>quality={html.escape(str(item.get('quality', '')))}</span> "
        f"<span class='chip'>score={html.escape(str(item.get('score', '')))}</span></li>"
        for item in tasks
    )
    return f"<ul>{items}</ul>"


def _render_handoff_list_html(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return "<div class='muted'>None</div>"
    items = "".join(
        f"<li><strong>{html.escape(str(item.get('normalized_model', '')))}</strong> "
        f"<span class='chip'>phase={html.escape(str(item.get('current_phase', '')))}</span> "
        f"<span class='chip'>quality={html.escape(str(item.get('quality', '')))}</span></li>"
        for item in rows
    )
    return f"<ul>{items}</ul>"


def _render_receipt_list_html(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return "<div class='muted'>None</div>"
    items = "".join(
        f"<li><strong>{html.escape(str(item.get('layer', '')))}</strong> "
        f"<span class='chip'>{html.escape(str(item.get('action', '')))}</span> "
        f"<span class='muted'>{html.escape(str(item.get('target', '')))}</span></li>"
        for item in rows
    )
    return f"<ul>{items}</ul>"
