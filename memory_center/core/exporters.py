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


def export_continuity_dashboard_html(
    workspace_file: str | Path,
    intent: str = "",
    task_id: str = "",
    session_id: str = "",
    limit: int = 10,
) -> str:
    from .orchestrator import workspace_continuity_dashboard

    dashboard = workspace_continuity_dashboard(workspace_file, intent=intent, task_id=task_id, session_id=session_id, limit=limit, view="compact", budget="medium")
    focus_task = dashboard.get("focus_task") or {}
    resume_packet = dashboard.get("resume_packet") or {}
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Continuity Dashboard</title>
  <style>
    :root {{
      --bg: #f4efe7;
      --panel: #fffdf9;
      --ink: #1f1b17;
      --muted: #6f6559;
      --line: #d9cfc1;
      --accent: #245d63;
      --accent-soft: #e1efef;
    }}
    body {{ margin: 0; font-family: Georgia, 'Noto Serif SC', serif; background: var(--bg); color: var(--ink); }}
    .wrap {{ max-width: 1080px; margin: 0 auto; padding: 28px; }}
    .hero, .card {{ background: var(--panel); border: 1px solid var(--line); border-radius: 16px; }}
    .hero {{ padding: 24px; }}
    .meta {{ color: var(--muted); display:flex; gap:16px; flex-wrap:wrap; }}
    .grid {{ display:grid; grid-template-columns: repeat(auto-fit,minmax(260px,1fr)); gap:18px; margin-top:20px; }}
    .card {{ padding: 18px; }}
    h1,h2 {{ margin: 0 0 12px; }}
    ul {{ margin: 8px 0 0; padding-left: 18px; }}
    li {{ margin: 6px 0; }}
    .chip {{ display:inline-block; padding:4px 10px; border-radius:999px; background:var(--accent-soft); color:var(--accent); font-size:12px; margin-right:8px; }}
    .muted {{ color: var(--muted); }}
  </style>
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <h1>Continuity Dashboard</h1>
      <div class="meta">
        <span>Workspace: {html.escape(str(dashboard.get('workspace', '')))}</span>
        <span>Focus: {html.escape(str(focus_task.get('title', '') or focus_task.get('task_id', 'None')))}</span>
        <span>Phase: {html.escape(str(resume_packet.get('current_phase', '')))}</span>
      </div>
    </section>
    <div class="grid">
      <section class="card">
        <h2>Resume Packet</h2>
        <div class="chip">{html.escape(str(resume_packet.get('resume_rule_profile', '')))}</div>
        <div class="muted">{html.escape(str(resume_packet.get('current_summary', '')))}</div>
      </section>
      <section class="card">
        <h2>Next Actions</h2>
        {_render_simple_list_html(dashboard.get('next_actions', []))}
      </section>
      <section class="card">
        <h2>Unresolved Items</h2>
        {_render_simple_list_html(dashboard.get('unresolved_items', []))}
      </section>
      <section class="card">
        <h2>Recent Evidence</h2>
        {_render_ref_list_html(dashboard.get('recent_evidence', []))}
      </section>
    </div>
  </div>
</body>
</html>
"""


def export_workbench_index_html(workspace_file: str | Path) -> str:
    store = WorkspaceStore(workspace_file)
    topology = store.read_json("service-topology.json", {})
    service_count = len(topology.get("services", []))
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Memory Center Workbench</title>
  <style>
    body {{ margin: 0; font-family: Georgia, 'Noto Serif SC', serif; background: #f7f1ea; color: #211c17; }}
    .wrap {{ max-width: 980px; margin: 0 auto; padding: 32px; }}
    .hero {{ margin-bottom: 22px; }}
    .grid {{ display:grid; grid-template-columns: repeat(auto-fit,minmax(220px,1fr)); gap:18px; }}
    .card {{ display:block; text-decoration:none; color:inherit; padding:20px; background:#fffdf9; border:1px solid #ddd2c4; border-radius:16px; }}
    h1,h2 {{ margin:0 0 10px; }}
    p {{ margin:0; color:#6f6559; }}
  </style>
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <h1>Memory Center Workbench</h1>
      <p>Services indexed: {service_count}</p>
    </section>
    <div class="grid">
      <a class="card" href="/ui/dashboard"><h2>Workspace Dashboard</h2><p>Focus task, receipts, handoffs, adoption.</p></a>
      <a class="card" href="/ui/continuity"><h2>Continuity Dashboard</h2><p>Resume packet, unresolved items, recent evidence.</p></a>
      <a class="card" href="/ui/task"><h2>Focus Task</h2><p>Current summary, next actions, and unresolved items.</p></a>
      <a class="card" href="/ui/timeline"><h2>Timeline</h2><p>Recent receipts, handoffs, and evidence refs.</p></a>
      <a class="card" href="/ui/usage"><h2>Usage Report</h2><p>Lookup adoption and suspected bypasses.</p></a>
      <a class="card" href="/ui/backend"><h2>Memory Backend</h2><p>Mirrored SQLite collections, records, and refs.</p></a>
      <a class="card" href="/workspace/status?view=compact&budget=medium"><h2>Workspace Status JSON</h2><p>Compact machine-readable status.</p></a>
    </div>
  </div>
</body>
</html>
"""


def export_focus_task_html(workspace_file: str | Path, intent: str = "", limit: int = 10) -> str:
    from .orchestrator import workspace_continuity_dashboard

    dashboard = workspace_continuity_dashboard(workspace_file, intent=intent, limit=limit, view="compact", budget="medium")
    focus = dashboard.get("focus_task") or {}
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Focus Task</title>
  <style>
    body {{ margin:0; font-family: Georgia, 'Noto Serif SC', serif; background:#f6f1e8; color:#1e1a16; }}
    .wrap {{ max-width: 980px; margin: 0 auto; padding: 28px; }}
    .hero,.card {{ background:#fffdf8; border:1px solid #d9cfc1; border-radius:16px; }}
    .hero {{ padding:24px; margin-bottom:18px; }}
    .grid {{ display:grid; grid-template-columns: repeat(auto-fit,minmax(280px,1fr)); gap:18px; }}
    .card {{ padding:18px; }}
    .muted {{ color:#6d6357; }}
    ul {{ margin:8px 0 0; padding-left:18px; }}
  </style>
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <h1>{html.escape(str(focus.get('title', '') or focus.get('task_id', 'Focus Task')))}</h1>
      <div class="muted">{html.escape(str(focus.get('focus_reason', '')))}</div>
    </section>
    <div class="grid">
      <section class="card"><h2>Next Actions</h2>{_render_simple_list_html(dashboard.get('next_actions', []))}</section>
      <section class="card"><h2>Unresolved Items</h2>{_render_simple_list_html(dashboard.get('unresolved_items', []))}</section>
      <section class="card"><h2>Recent Evidence</h2>{_render_ref_list_html(dashboard.get('recent_evidence', []))}</section>
    </div>
  </div>
</body>
</html>
"""


def export_timeline_html(workspace_file: str | Path, intent: str = "", limit: int = 20) -> str:
    from .orchestrator import memory_backend_query, workspace_replay_write_chain, workspace_status

    focus = workspace_status(workspace_file, view="compact", budget="medium").get("current_focus_task") or {}
    task_id = str(focus.get("task_id", "") or "")
    timeline = workspace_replay_write_chain(workspace_file, task_id=task_id, limit=limit).get("timeline", [])
    backend = memory_backend_query(workspace_file, collection="write-receipts.jsonl", limit=min(limit, 10))
    items = "".join(
        f"<li><strong>{html.escape(str(item.get('kind', '')))}</strong> "
        f"<span class='chip'>{html.escape(str(item.get('action', '')))}</span> "
        f"<span class='muted'>{html.escape(str(item.get('target', '')))}</span></li>"
        for item in timeline
    ) or "<div class='muted'>None</div>"
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Timeline</title>
  <style>
    body {{ margin:0; font-family: Georgia, 'Noto Serif SC', serif; background:#f6f1e8; color:#1e1a16; }}
    .wrap {{ max-width: 980px; margin: 0 auto; padding: 28px; }}
    .card {{ background:#fffdf8; border:1px solid #d9cfc1; border-radius:16px; padding:18px; }}
    .chip {{ display:inline-block; padding:4px 10px; border-radius:999px; background:#efe3d4; color:#8c4b2f; font-size:12px; margin-right:8px; }}
    .muted {{ color:#6d6357; }}
    ul {{ margin:8px 0 0; padding-left:18px; }}
    li {{ margin:6px 0; }}
  </style>
</head>
<body>
  <div class="wrap">
    <section class="card">
      <h1>Timeline</h1>
      <div class="muted">Focus task: {html.escape(task_id or 'None')}</div>
      <ul>{items}</ul>
      <div class="muted" style="margin-top:12px;">Mirrored backend receipts: {backend.get('records', {}).get('count', 0)}</div>
    </section>
  </div>
</body>
</html>
"""


def export_usage_report_html(workspace_file: str | Path, limit: int = 50) -> str:
    from .orchestrator import memory_backend_query, memory_tool_usage_report

    report = memory_tool_usage_report(workspace_file, limit=limit)
    backend = memory_backend_query(workspace_file, collection="session-events.jsonl", limit=min(limit, 10))
    summary = report.get("summary", {}) or {}
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Usage Report</title>
  <style>
    body {{ margin:0; font-family: Georgia, 'Noto Serif SC', serif; background:#f6f1e8; color:#1e1a16; }}
    .wrap {{ max-width: 980px; margin: 0 auto; padding: 28px; }}
    .grid {{ display:grid; grid-template-columns: repeat(auto-fit,minmax(220px,1fr)); gap:18px; }}
    .card {{ background:#fffdf8; border:1px solid #d9cfc1; border-radius:16px; padding:18px; }}
    .muted {{ color:#6d6357; }}
    ul {{ margin:8px 0 0; padding-left:18px; }}
    li {{ margin:6px 0; }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>Usage Report</h1>
    <div class="grid">
      <section class="card"><h2>Summary</h2><div class="muted">Total calls: {summary.get('total_tool_calls', 0)}</div><div class="muted">Memory Center ratio: {summary.get('memory_center_ratio', 0)}</div><div class="muted">Bypasses: {summary.get('suspected_bypass_count', 0)}</div><div class="muted">Mirrored session events: {backend.get('records', {}).get('count', 0)}</div></section>
      <section class="card"><h2>Adoption Hints</h2>{_render_simple_list_html(report.get('adoption_hints', []))}</section>
      <section class="card"><h2>Bypass Samples</h2>{_render_ref_list_html([{'ref_id': item.get('session_id', ''), 'summary': item.get('reason', '') + ' | ' + str(item.get('query', ''))} for item in report.get('suspected_bypass', [])])}</section>
    </div>
  </div>
</body>
</html>
"""


def export_memory_backend_html(workspace_file: str | Path, limit: int = 20) -> str:
    store = WorkspaceStore(workspace_file)
    stats = store.memory_backend_stats()
    records = store.memory_backend_query_records(limit=limit)
    refs = store.memory_backend_query_refs(limit=limit)
    record_items = "".join(
        f"<li><strong>{html.escape(str(item.get('collection', '')))}</strong> "
        f"<span class='muted'>{html.escape(str(item.get('record_id', '')))}</span></li>"
        for item in records.get("records", [])
    ) or "<div class='muted'>None</div>"
    ref_items = "".join(
        f"<li><strong>{html.escape(str(item.get('ref_path', '')))}</strong></li>"
        for item in refs.get("refs", [])
    ) or "<div class='muted'>None</div>"
    collections = "".join(
        f"<li><strong>{html.escape(name)}</strong>: {count}</li>"
        for name, count in (stats.get("collections", {}) or {}).items()
    ) or "<div class='muted'>None</div>"
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Memory Backend</title>
  <style>
    body {{ margin:0; font-family: Georgia, 'Noto Serif SC', serif; background:#f6f1e8; color:#1e1a16; }}
    .wrap {{ max-width: 1080px; margin: 0 auto; padding: 28px; }}
    .grid {{ display:grid; grid-template-columns: repeat(auto-fit,minmax(260px,1fr)); gap:18px; }}
    .card {{ background:#fffdf8; border:1px solid #d9cfc1; border-radius:16px; padding:18px; }}
    .muted {{ color:#6d6357; }}
    ul {{ margin:8px 0 0; padding-left:18px; }}
    li {{ margin:6px 0; }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>Memory Backend</h1>
    <div class="grid">
      <section class="card"><h2>Collections</h2><ul>{collections}</ul><div class="muted">Refs: {stats.get('ref_count', 0)}</div></section>
      <section class="card"><h2>Recent Records</h2><ul>{record_items}</ul></section>
      <section class="card"><h2>Recent Refs</h2><ul>{ref_items}</ul></section>
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


def _render_simple_list_html(rows: List[str]) -> str:
    if not rows:
        return "<div class='muted'>None</div>"
    return "<ul>" + "".join(f"<li>{html.escape(str(item))}</li>" for item in rows) + "</ul>"


def _render_ref_list_html(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return "<div class='muted'>None</div>"
    items = "".join(
        f"<li><strong>{html.escape(str(item.get('ref_id', '')))}</strong> "
        f"<span class='muted'>{html.escape(str(item.get('summary', '')))}</span></li>"
        for item in rows
    )
    return f"<ul>{items}</ul>"
