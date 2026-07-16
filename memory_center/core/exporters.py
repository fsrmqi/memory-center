from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from .store import WorkspaceStore


def _nav_sidebar_html(workspace_param: str) -> str:
    """Generate a shared navigation sidebar HTML fragment with bilingual labels."""
    ws = html.escape(workspace_param)
    links = [
        ("/ui", "Workbench / 工作台"),
        ("/ui/dashboard", "Dashboard / 总面板"),
        ("/ui/continuity", "Continuity / 连续性"),
        ("/ui/task", "Focus Task / 焦点任务"),
        ("/ui/timeline", "Timeline / 时间线"),
        ("/ui/receipts", "Receipts / 写入回执"),
        ("/ui/usage", "Usage / 使用报告"),
        ("/ui/backend", "Backend / 后端"),
        ("/ui/index-freshness", "Freshness / 索引新鲜度"),
    ]
    items = "".join(
        f'<li><a href="{path}?workspace={ws}" style="display:block;padding:6px 8px;color:var(--ink);text-decoration:none;border-radius:6px;">{label}</a></li>'
        for path, label in links
    )
    return (
        '<nav style="position:fixed;top:0;left:0;width:220px;height:100vh;'
        'background:var(--panel);border-right:1px solid var(--line);'
        'padding:18px 12px;font-size:14px;z-index:100;overflow-y:auto;">'
        '<div style="font-weight:700;margin-bottom:14px;color:var(--accent);">Memory Center</div>'
        f'<ul style="list-style:none;padding:0;margin:0;">{items}</ul>'
        '</nav>'
    )


def _next_action_hero_html(dashboard: dict[str, Any], focus_task: dict[str, Any]) -> str:
    """Render a prominent Next Action hero card on the dashboard."""
    workspace_param = html.escape(str(dashboard.get("workspace", "")))
    focus_eval = dashboard.get("focus_resume_eval") or {}
    continuity = dashboard.get("continuity_overview") or {}
    resume_packet = continuity.get("resume_packet") or {}
    next_actions = continuity.get("next_actions") or resume_packet.get("next_recommended_actions") or []
    unresolved = continuity.get("unresolved_items") or resume_packet.get("unresolved_items") or []
    quality = focus_eval.get("quality", "")
    score = focus_eval.get("score", 0)

    if unresolved:
        action_text = html.escape(str(unresolved[0].get("description", "") or str(unresolved[0])))
        action_label = "Resolve unresolved item / 解决未完成项"
    elif next_actions:
        action_text = html.escape(str(next_actions[0].get("description", "") or str(next_actions[0])))
        action_label = "Continue next action / 继续下一步"
    elif focus_task:
        task_title = html.escape(str(focus_task.get("title", "") or focus_task.get("task_id", "None")))
        action_text = f"Resume focus task: {task_title}"
        action_label = "Resume focus task / 恢复焦点任务"
    else:
        action_text = "No active focus task. Start a new task with mc_start."
        action_label = "No focus task / 无焦点任务"

    if focus_task:
        task_id = html.escape(str(focus_task.get("task_id", "")))
        link = f"/ui/task?task_id={task_id}&workspace={workspace_param}"
    else:
        link = f"/ui/continuity?workspace={workspace_param}"

    quality_chip = ""
    if quality:
        quality_chip = f'<span class="chip">quality={html.escape(quality)}</span>'
    if score:
        quality_chip += f'<span class="chip">score={html.escape(str(score))}</span>'

    return f"""
    <section style="margin-bottom:22px;padding:22px;background:var(--panel);border:2px solid var(--accent);border-radius:18px;">
      <h2 style="margin:0 0 8px;color:var(--accent);">Next Action / 下一步</h2>
      <div style="font-size:16px;font-weight:600;margin-bottom:6px;">{html.escape(action_label)}</div>
      <div class="muted" style="font-size:14px;">{action_text}</div>
      {quality_chip}
      <a href="{link}" class="cross-link" style="display:inline-block;margin-top:10px;">Go → / 前往 →</a>
    </section>
    """


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
    from .orchestrator import workspace_dashboard

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


def export_workspace_dashboard_html(workspace_file: str | Path, intent: str = "", limit: int = 10, view: str = "compact", budget: str = "medium") -> str:
    from .orchestrator import workspace_dashboard

    dashboard = workspace_dashboard(workspace_file, intent=intent, limit=limit, view=view, budget=budget)
    focus_task = dashboard.get("focus_task") or {}
    focus_eval = dashboard.get("focus_resume_eval") or {}
    workspace_param = str(Path(workspace_file).resolve())
    sidebar = _nav_sidebar_html(workspace_param)
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
    .wrap {{ max-width: 1180px; margin-left: 240px; padding: 28px; }}
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
    .cross-link {{ display:inline-block; color:var(--accent); text-decoration:none; font-weight:600; }}
    .filter-form {{ display:flex; gap:10px; align-items:center; margin-bottom:18px; padding:14px; background:var(--panel); border:1px solid var(--line); border-radius:12px; }}
    .filter-form input, .filter-form select, .filter-form button {{ font-family:inherit; font-size:14px; padding:6px 12px; border:1px solid var(--line); border-radius:8px; background:var(--bg); color:var(--ink); }}
    .filter-form select {{ cursor:pointer; }}
    .filter-form button {{ background:var(--accent); color:#fff; border:none; cursor:pointer; }}
    .filter-form button:hover {{ background:#a05838; }}
  </style>
</head>
<body>
  {sidebar}
  <div class="wrap">
    <form class="filter-form" method="get" action="/ui/dashboard">
      <input name="workspace" value="{html.escape(workspace_param)}" type="hidden">
      <input name="intent" placeholder="Intent / 查询意图">
      <input name="limit" type="number" value="{limit}" min="1" max="100">
      <select name="view">
        <option value="compact" {"selected" if view == "compact" else ""}>Compact</option>
        <option value="full" {"selected" if view == "full" else ""}>Full</option>
      </select>
      <select name="budget">
        <option value="small" {"selected" if budget == "small" else ""}>Small</option>
        <option value="medium" {"selected" if budget == "medium" else ""}>Medium</option>
        <option value="large" {"selected" if budget == "large" else ""}>Large</option>
      </select>
      <button type="submit">Refresh / 刷新</button>
    </form>
    <section class="hero">
      <h1>Workspace Dashboard</h1>
      <div class="meta">
        <span>Workspace: {html.escape(str(dashboard.get('workspace', '')))}</span>
        <span>Focus: {html.escape(str(focus_task.get('title', '') or focus_task.get('task_id', 'None')))}</span>
        <span>Active: {len(dashboard.get('active_tasks', []))}</span>
        <span>Blocked: {len(dashboard.get('blocked_tasks', []))}</span>
      </div>
    </section>
    {_next_action_hero_html(dashboard, focus_task)}
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
    view: str = "compact",
    budget: str = "medium",
) -> str:
    from .orchestrator import workspace_continuity_dashboard

    dashboard = workspace_continuity_dashboard(workspace_file, intent=intent, task_id=task_id, session_id=session_id, limit=limit, view=view, budget=budget)
    focus_task = dashboard.get("focus_task") or {}
    resume_packet = dashboard.get("resume_packet") or {}
    workspace_param = str(Path(workspace_file).resolve())
    sidebar = _nav_sidebar_html(workspace_param)
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
    .wrap {{ max-width: 1080px; margin-left: 240px; padding: 28px; }}
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
    .filter-form {{ display:flex; gap:10px; align-items:center; margin-bottom:18px; padding:14px; background:var(--panel); border:1px solid var(--line); border-radius:12px; }}
    .filter-form input, .filter-form select, .filter-form button {{ font-family:inherit; font-size:14px; padding:6px 12px; border:1px solid var(--line); border-radius:8px; background:var(--bg); color:var(--ink); }}
    .filter-form select {{ cursor:pointer; }}
    .filter-form button {{ background:var(--accent); color:#fff; border:none; cursor:pointer; }}
    .filter-form button:hover {{ background:#2e7578; }}
  </style>
</head>
<body>
  {sidebar}
  <div class="wrap">
    <form class="filter-form" method="get" action="/ui/continuity">
      <input name="workspace" value="{html.escape(workspace_param)}" type="hidden">
      <input name="intent" placeholder="Intent / 查询意图">
      <input name="task_id" placeholder="Task ID" value="{html.escape(task_id)}">
      <input name="session_id" placeholder="Session ID" value="{html.escape(session_id)}">
      <input name="limit" type="number" value="{limit}" min="1" max="100">
      <select name="view">
        <option value="compact" {"selected" if view == "compact" else ""}>Compact</option>
        <option value="full" {"selected" if view == "full" else ""}>Full</option>
      </select>
      <select name="budget">
        <option value="small" {"selected" if budget == "small" else ""}>Small</option>
        <option value="medium" {"selected" if budget == "medium" else ""}>Medium</option>
        <option value="large" {"selected" if budget == "large" else ""}>Large</option>
      </select>
      <button type="submit">Refresh / 刷新</button>
    </form>
    <section class="hero">
      <h1>Continuity Dashboard</h1>
      <div class="meta">
        <span>Workspace: {html.escape(str(dashboard.get('workspace', '')))}</span>
        <span>Focus: {html.escape(str(focus_task.get('title', '') or focus_task.get('task_id', 'None')))}</span>
        <span>Phase: {html.escape(str(resume_packet.get('current_phase', '')))}</span>
        {f'<span><a class="cross-link" href="/ui/task?task_id={html.escape(str(focus_task.get("task_id", "")))}&workspace={html.escape(workspace_param)}">View Focus Task →</a></span>' if focus_task.get('task_id') else ''}
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
    topology = store.read_json_prefer_backend("service-topology.json", {})
    service_count = len(topology.get("services", []))
    workspace_param = str(Path(workspace_file).resolve())
    sidebar = _nav_sidebar_html(workspace_param)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Memory Center Workbench</title>
  <style>
    :root {{
      --bg: #f7f1ea;
      --panel: #fffdf9;
      --ink: #211c17;
      --muted: #6f6559;
      --line: #ddd2c4;
      --accent: #8c4b2f;
    }}
    body {{ margin: 0; font-family: Georgia, 'Noto Serif SC', serif; background: var(--bg); color: var(--ink); }}
    .wrap {{ max-width: 980px; margin-left: 240px; padding: 32px; }}
    .hero {{ margin-bottom: 22px; }}
    .grid {{ display:grid; grid-template-columns: repeat(auto-fit,minmax(220px,1fr)); gap:18px; }}
    .card {{ display:block; text-decoration:none; color:inherit; padding:20px; background:var(--panel); border:1px solid var(--line); border-radius:16px; }}
    h1,h2 {{ margin:0 0 10px; }}
    p {{ margin:0; color:var(--muted); }}
    /* Tour overlay */
    .tour-overlay {{ display:none; position:fixed; inset:0; background:rgba(0,0,0,.45); z-index:900; }}
    .tour-overlay.active {{ display:flex; align-items:center; justify-content:center; }}
    .tour-box {{ background:var(--panel); border:2px solid var(--accent); border-radius:20px; padding:28px 32px; max-width:540px; box-shadow:0 20px 60px rgba(0,0,0,.2); }}
    .tour-box h2 {{ color:var(--accent); }}
    .tour-box .step {{ font-size:13px; color:var(--muted); margin-bottom:6px; }}
    .tour-box p {{ font-size:15px; line-height:1.6; }}
    .tour-box .nav {{ display:flex; gap:10px; margin-top:18px; }}
    .tour-box button {{ font-family:inherit; font-size:14px; padding:8px 18px; border:1px solid var(--line); border-radius:10px; cursor:pointer; }}
    .tour-box .next {{ background:var(--accent); color:#fff; border-color:var(--accent); }}
    .tour-box .skip {{ background:var(--bg); color:var(--muted); }}
  </style>
</head>
<body>
  {sidebar}
  <!-- Guided tour overlay -->
  <div class="tour-overlay" id="tourOverlay">
    <div class="tour-box">
      <div class="step" id="tourStep"></div>
      <h2 id="tourTitle"></h2>
      <p id="tourDesc"></p>
      <div class="nav">
        <button class="skip" onclick="tourEnd()">Skip / 跳过</button>
        <button class="next" id="tourNext" onclick="tourNext()">Next →</button>
      </div>
    </div>
  </div>
  <script>
    const tourSteps = [
      {{ title: "Welcome / 欢迎", desc: "This workbench gives you a daily overview of your project memory. Let's walk through it in 5 steps.\\n\\n这个工作台每天给你项目记忆的全局概览。让我们用 5 步走一遍。" }},
      {{ title: "Dashboard / 总面板", desc: "The Dashboard shows your focus task, active tasks, recent handoffs, and write receipts. It's your starting point every day.\\n\\n总面板展示焦点任务、活跃任务、最近交接和写入回执。这是你每天的起点。" }},
      {{ title: "Continuity / 连续性", desc: "The Continuity page shows what to resume: your current summary, next actions, and unresolved items. Open this when you come back the next day.\\n\\n连续性页面展示要恢复什么：当前摘要、下一步动作、未解决事项。第二天回来时打开这个。" }},
      {{ title: "Timeline & Refs / 时间线与引用", desc: "Timeline shows all events and receipts in order. Any short ref can be expanded inline via the ▶ Expand button, or click through to /ui/ref for full detail — including a 'View in Timeline' reverse link.\\n\\n时间线按顺序展示所有事件和回执。任何短引用都可以通过 ▶ 展开按钮内联展开，或点击进入 /ui/ref 查看完整细节——包括反向'在时间线中查看'链接。" }},
      {{ title: "Lookup & Tools / 查询与工具", desc: "Use the sidebar to navigate to Usage Report (tool adoption), Index Freshness (stale checks), Backend (mirrored data), or the JSON status endpoint. You can also adjust view (compact/full) and budget (small/medium/large) on Dashboard and Continuity pages.\\n\\n用侧栏导航到使用率报告、索引新鲜度、后端数据或 JSON 状态端点。Dashboard 和 Continuity 页面还可以调整 view/budget。" }},
    ];
    let tourIdx = 0;
    function tourShow(i) {{
      document.getElementById('tourStep').textContent = 'Step ' + (i+1) + '/5';
      document.getElementById('tourTitle').textContent = tourSteps[i].title;
      document.getElementById('tourDesc').textContent = tourSteps[i].desc;
      document.getElementById('tourNext').textContent = i < tourSteps.length - 1 ? 'Next →' : 'Done ✓';
    }}
    function tourNext() {{
      if (tourIdx < tourSteps.length - 1) {{ tourIdx++; tourShow(tourIdx); }}
      else {{ tourEnd(); }}
    }}
    function tourEnd() {{
      document.getElementById('tourOverlay').classList.remove('active');
      localStorage.setItem('mc_tour_done', '1');
    }}
    if (!localStorage.getItem('mc_tour_done')) {{
      document.getElementById('tourOverlay').classList.add('active');
      tourShow(0);
    }}
  </script>
  <div class="wrap">
    <section class="hero">
      <h1>Memory Center Workbench</h1>
      <p>Services indexed: {service_count} · <button onclick="localStorage.removeItem('mc_tour_done');location.reload();" style="font-family:inherit;font-size:12px;padding:4px 12px;border:1px solid var(--line);border-radius:8px;background:var(--bg);cursor:pointer;">Replay Tour / 重播引导</button></p>
    </section>
    <section class="card" style="margin-bottom:22px;">
      <h2>Quick Start / 快速入门</h2>
      <ol style="margin:0;padding-left:18px;color:var(--muted);">
        <li><strong>Start a task</strong>: <code>work-start --intent "your task"</code></li>
        <li><strong>Find symbols</strong>: <code>lookup-hint --query "ArticleService"</code></li>
        <li><strong>Partial reindex</strong>: <code>reindex --changed-only --scope staged</code></li>
        <li><strong>Resume next day</strong>: <code>work-resume --task-id your-task</code></li>
        <li><strong>Handoff to another model</strong>: <code>work-handoff --target-model claude-code</code></li>
        <li><strong>Close and record</strong>: <code>work-close --session-id your-session</code></li>
      </ol>
    </section>
    <div class="grid">
      <a class="card" href="/ui/dashboard"><h2>Workspace Dashboard</h2><p>Focus task, receipts, handoffs, adoption.</p></a>
      <a class="card" href="/ui/continuity"><h2>Continuity Dashboard</h2><p>Resume packet, unresolved items, recent evidence.</p></a>
      <a class="card" href="/ui/task"><h2>Focus Task</h2><p>Current summary, next actions, and unresolved items.</p></a>
      <a class="card" href="/ui/timeline"><h2>Timeline</h2><p>Recent receipts, handoffs, and evidence refs.</p></a>
      <a class="card" href="/ui/receipts"><h2>Receipts</h2><p>Recent write receipts and receipt summaries.</p></a>
      <a class="card" href="/ui/usage"><h2>Usage Report</h2><p>Lookup adoption and suspected bypasses.</p></a>
      <a class="card" href="/ui/backend"><h2>Memory Backend</h2><p>Mirrored SQLite collections, records, and refs.</p></a>
      <a class="card" href="/ui/index-freshness"><h2>Index Freshness</h2><p>Stale index signals and semantic readiness.</p></a>
      <a class="card" href="/workspace/status?view=compact&budget=medium"><h2>Workspace Status JSON</h2><p>Compact machine-readable status.</p></a>
    </div>
  </div>
</body>
</html>
"""


def export_focus_task_html(workspace_file: str | Path, intent: str = "", task_id: str = "", limit: int = 10) -> str:
    from .artifacts import get_task_artifact
    from .orchestrator import workspace_continuity_dashboard

    dashboard = workspace_continuity_dashboard(workspace_file, intent=intent, task_id=task_id, limit=limit, view="compact", budget="medium")
    focus = dashboard.get("focus_task") or {}
    resolved_task_id = str(focus.get("task_id", "") or "")
    current_summary = (
        get_task_artifact(workspace_file, resolved_task_id, "current_summary", max_bytes=16 * 1024).get("content", "")
        if resolved_task_id
        else ""
    )
    workspace_param = str(Path(workspace_file).resolve())
    sidebar = _nav_sidebar_html(workspace_param)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Focus Task</title>
  <style>
    :root {{
      --bg: #f6f1e8;
      --panel: #fffdf8;
      --ink: #1e1a16;
      --muted: #6d6357;
      --line: #d9cfc1;
      --accent: #8c4b2f;
      --accent-2: #2f6b5a;
    }}
    body {{ margin:0; font-family: Georgia, 'Noto Serif SC', serif; background:var(--bg); color:var(--ink); }}
    .wrap {{ max-width: 980px; margin-left: 240px; padding: 28px; }}
    .hero,.card {{ background:var(--panel); border:1px solid var(--line); border-radius:16px; }}
    .hero {{ padding:24px; margin-bottom:18px; }}
    .grid {{ display:grid; grid-template-columns: repeat(auto-fit,minmax(280px,1fr)); gap:18px; }}
    .card {{ padding:18px; }}
    .muted {{ color:var(--muted); }}
    ul {{ margin:8px 0 0; padding-left:18px; }}
    .cross-link {{ display:inline-block; margin-top:14px; padding:8px 14px; background:var(--accent-2); color:#fff; border-radius:8px; text-decoration:none; font-size:14px; }}
    .cross-link:hover {{ background:#3a8068; }}
  </style>
</head>
<body>
  {sidebar}
  <div class="wrap">
    <section class="hero">
      <h1>{html.escape(str(focus.get('title', '') or focus.get('task_id', 'Focus Task')))}</h1>
      <div class="muted">{html.escape(str(focus.get('focus_reason', '')))}</div>
      <a class="cross-link" href="/ui/timeline?workspace={html.escape(workspace_param)}&task_id={html.escape(resolved_task_id)}">View Timeline → / 查看时间线</a>
      <a class="cross-link" href="/ui/receipts?workspace={html.escape(workspace_param)}" style="margin-left:8px;">View Receipts → / 查看回执</a>
    </section>
    <div class="grid">
      <section class="card"><h2>Next Actions</h2>{_render_simple_list_html(dashboard.get('next_actions', []))}</section>
      <section class="card"><h2>Unresolved Items</h2>{_render_simple_list_html(dashboard.get('unresolved_items', []))}</section>
      <section class="card"><h2>Recent Evidence</h2>{_render_ref_list_html(dashboard.get('recent_evidence', []))}</section>
      <section class="card"><h2>Current Summary</h2><div class="muted">{html.escape(str(current_summary))}</div></section>
    </div>
  </div>
</body>
</html>
"""


def export_timeline_html(workspace_file: str | Path, intent: str = "", limit: int = 20) -> str:
    from .orchestrator import memory_backend_query, workspace_replay_write_chain, workspace_status

    workspace_param = str(Path(workspace_file).resolve())
    sidebar = _nav_sidebar_html(workspace_param)
    focus = workspace_status(workspace_file, view="compact", budget="medium").get("current_focus_task") or {}
    task_id = str(focus.get("task_id", "") or "")
    timeline = workspace_replay_write_chain(workspace_file, task_id=task_id, limit=limit).get("timeline", [])
    backend = memory_backend_query(workspace_file, collection="write-receipts.jsonl", limit=min(limit, 10))
    items = "".join(
        f"<li><strong>{html.escape(str(item.get('kind', '')))}</strong> "
        f"<span class='chip'>{html.escape(str(item.get('action', '')))}</span> "
        f"<a href='/ui/ref?workspace={html.escape(workspace_param)}&ref_id={html.escape(str(item.get('ref_id', '')))}' style='color:var(--accent);text-decoration:none;'>"
        f"<span class='muted'>{html.escape(str(item.get('target', '')))}</span></a>"
        f"<details><summary>Expand / 展开</summary><pre>{html.escape(json.dumps(item, ensure_ascii=False, indent=2))}</pre></details></li>"
        for item in timeline
    ) or "<div class='muted'>None</div>"
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Timeline</title>
  <style>
    :root {{
      --bg: #f6f1e8;
      --panel: #fffdf8;
      --ink: #1e1a16;
      --muted: #6d6357;
      --line: #d9cfc1;
      --accent: #8c4b2f;
    }}
    body {{ margin:0; font-family: Georgia, 'Noto Serif SC', serif; background:var(--bg); color:var(--ink); }}
    .wrap {{ max-width: 980px; margin-left: 240px; padding: 28px; }}
    .card {{ background:var(--panel); border:1px solid var(--line); border-radius:16px; padding:18px; }}
    .chip {{ display:inline-block; padding:4px 10px; border-radius:999px; background:#efe3d4; color:var(--accent); font-size:12px; margin-right:8px; }}
    .muted {{ color:var(--muted); }}
    ul {{ margin:8px 0 0; padding-left:18px; }}
    li {{ margin:6px 0; }}
    details {{ margin:4px 0; }}
    details summary {{ cursor:pointer; color:var(--accent); font-size:13px; }}
    details pre {{ background:#f2ece3; padding:10px; border-radius:10px; font-size:12px; }}
  </style>
</head>
<body>
  {sidebar}
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

    workspace_param = str(Path(workspace_file).resolve())
    sidebar = _nav_sidebar_html(workspace_param)
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
    :root {{
      --bg: #f6f1e8;
      --panel: #fffdf8;
      --ink: #1e1a16;
      --muted: #6d6357;
      --line: #d9cfc1;
      --accent: #8c4b2f;
    }}
    body {{ margin:0; font-family: Georgia, 'Noto Serif SC', serif; background:var(--bg); color:var(--ink); }}
    .wrap {{ max-width: 980px; margin-left: 240px; padding: 28px; }}
    .grid {{ display:grid; grid-template-columns: repeat(auto-fit,minmax(220px,1fr)); gap:18px; }}
    .card {{ background:var(--panel); border:1px solid var(--line); border-radius:16px; padding:18px; }}
    .muted {{ color:var(--muted); }}
    ul {{ margin:8px 0 0; padding-left:18px; }}
    li {{ margin:6px 0; }}
    details {{ margin:4px 0; }}
    details summary {{ cursor:pointer; color:var(--accent); font-size:13px; }}
    details pre {{ background:#f2ece3; padding:10px; border-radius:10px; font-size:12px; }}
  </style>
</head>
<body>
  {sidebar}
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


def export_receipts_html(workspace_file: str | Path, limit: int = 20) -> str:
    from .orchestrator import workspace_write_receipts

    workspace_param = str(Path(workspace_file).resolve())
    sidebar = _nav_sidebar_html(workspace_param)
    payload = workspace_write_receipts(workspace_file, limit=limit)
    rows = payload.get("receipts", [])
    items = "".join(
        f"<li><strong>{html.escape(str(item.get('receipt_id', '')))}</strong> "
        f"<span class='muted'>{html.escape(str(item.get('summary', '')))}</span>"
        f"<details><summary>Expand / 展开</summary><pre>{html.escape(json.dumps(item, ensure_ascii=False, indent=2))}</pre></details></li>"
        for item in rows
    ) or "<div class='muted'>None</div>"
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Receipts</title>
  <style>
    :root {{
      --bg: #f6f1e8;
      --panel: #fffdf8;
      --ink: #1e1a16;
      --muted: #6d6357;
      --line: #d9cfc1;
      --accent: #8c4b2f;
    }}
    body {{ margin:0; font-family: Georgia, 'Noto Serif SC', serif; background:var(--bg); color:var(--ink); }}
    .wrap {{ max-width: 980px; margin-left: 240px; padding: 28px; }}
    .card {{ background:var(--panel); border:1px solid var(--line); border-radius:16px; padding:18px; }}
    .muted {{ color:var(--muted); }}
    ul {{ margin:8px 0 0; padding-left:18px; }}
    li {{ margin:6px 0; }}
    details {{ margin:4px 0; }}
    details summary {{ cursor:pointer; color:var(--accent); font-size:13px; }}
    details pre {{ background:#f2ece3; padding:10px; border-radius:10px; font-size:12px; }}
    .filter-form {{ display:flex; gap:10px; align-items:center; margin-bottom:18px; padding:14px; background:var(--panel); border:1px solid var(--line); border-radius:12px; }}
    .filter-form input, .filter-form select, .filter-form button {{ font-family:inherit; font-size:14px; padding:6px 12px; border:1px solid var(--line); border-radius:8px; background:var(--bg); color:var(--ink); }}
    .filter-form select {{ cursor:pointer; }}
    .filter-form button {{ background:var(--accent); color:#fff; border:none; cursor:pointer; }}
    .filter-form button:hover {{ background:#a05838; }}
  </style>
</head>
<body>
  {sidebar}
  <div class="wrap">
    <form class="filter-form" method="get" action="/ui/receipts">
      <input name="workspace" value="{html.escape(workspace_param)}" type="hidden">
      <select name="layer"><option value="">All</option><option>L0_session_events</option><option>L1_case_atoms</option><option>L2_task_spaces</option><option>L3_workspace_profile</option></select>
      <select name="action"><option value="">All</option><option>workspace_record_case</option><option>workspace_log_session_event</option><option>update_task_artifact</option><option>sync_sniff_artifacts</option></select>
      <input name="limit" type="number" value="{limit}" min="1" max="100">
      <button type="submit">Filter / 篮选</button>
    </form>
    <section class="card">
      <h1>Receipts</h1>
      <div class="muted">Total: {payload.get('summary', {}).get('total', 0)}</div>
      <ul>{items}</ul>
    </section>
  </div>
</body>
</html>
"""


def export_index_freshness_html(workspace_file: str | Path) -> str:
    from .orchestrator import memory_eval_index_freshness

    workspace_param = str(Path(workspace_file).resolve())
    sidebar = _nav_sidebar_html(workspace_param)
    payload = memory_eval_index_freshness(workspace_file, scope="all")
    findings = "".join(
        f"<li><strong>{html.escape(str(item.get('severity', '')))}</strong> "
        f"<span class='muted'>{html.escape(str(item.get('message', '')))}</span></li>"
        for item in payload.get("findings", [])
    ) or "<div class='muted'>None</div>"
    stale = "".join(f"<li>{html.escape(str(item))}</li>" for item in payload.get("stale_changed_files", [])) or "<div class='muted'>None</div>"
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Index Freshness</title>
  <style>
    :root {{
      --bg: #f6f1e8;
      --panel: #fffdf8;
      --ink: #1e1a16;
      --muted: #6d6357;
      --line: #d9cfc1;
      --accent: #8c4b2f;
    }}
    body {{ margin:0; font-family: Georgia, 'Noto Serif SC', serif; background:var(--bg); color:var(--ink); }}
    .wrap {{ max-width: 980px; margin-left: 240px; padding: 28px; }}
    .grid {{ display:grid; grid-template-columns: repeat(auto-fit,minmax(260px,1fr)); gap:18px; }}
    .card {{ background:var(--panel); border:1px solid var(--line); border-radius:16px; padding:18px; }}
    .muted {{ color:var(--muted); }}
    ul {{ margin:8px 0 0; padding-left:18px; }}
    li {{ margin:6px 0; }}
    details {{ margin:4px 0; }}
    details summary {{ cursor:pointer; color:var(--accent); font-size:13px; }}
    details pre {{ background:#f2ece3; padding:10px; border-radius:10px; font-size:12px; }}
  </style>
</head>
<body>
  {sidebar}
  <div class="wrap">
    <h1>Index Freshness</h1>
    <div class="grid">
      <section class="card"><h2>Summary</h2><div class="muted">Quality: {payload.get('quality', '')}</div><div class="muted">Score: {payload.get('score', 0)}</div><div class="muted">Changed files: {payload.get('changed_file_count', 0)}</div></section>
      <section class="card"><h2>Stale Changed Files</h2><ul>{stale}</ul></section>
      <section class="card"><h2>Findings</h2><ul>{findings}</ul></section>
    </div>
  </div>
</body>
</html>
"""


def export_memory_backend_html(workspace_file: str | Path, limit: int = 20) -> str:
    store = WorkspaceStore(workspace_file)
    workspace_param = str(Path(workspace_file).resolve())
    sidebar = _nav_sidebar_html(workspace_param)
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
    :root {{
      --bg: #f6f1e8;
      --panel: #fffdf8;
      --ink: #1e1a16;
      --muted: #6d6357;
      --line: #d9cfc1;
      --accent: #8c4b2f;
    }}
    body {{ margin:0; font-family: Georgia, 'Noto Serif SC', serif; background:var(--bg); color:var(--ink); }}
    .wrap {{ max-width: 1080px; margin-left: 240px; padding: 28px; }}
    .grid {{ display:grid; grid-template-columns: repeat(auto-fit,minmax(260px,1fr)); gap:18px; }}
    .card {{ background:var(--panel); border:1px solid var(--line); border-radius:16px; padding:18px; }}
    .muted {{ color:var(--muted); }}
    ul {{ margin:8px 0 0; padding-left:18px; }}
    li {{ margin:6px 0; }}
    details {{ margin:4px 0; }}
    details summary {{ cursor:pointer; color:var(--accent); font-size:13px; }}
    details pre {{ background:#f2ece3; padding:10px; border-radius:10px; font-size:12px; }}
    .filter-form {{ display:flex; gap:10px; align-items:center; margin-bottom:18px; padding:14px; background:var(--panel); border:1px solid var(--line); border-radius:12px; }}
    .filter-form input, .filter-form select, .filter-form button {{ font-family:inherit; font-size:14px; padding:6px 12px; border:1px solid var(--line); border-radius:8px; background:var(--bg); color:var(--ink); }}
    .filter-form select {{ cursor:pointer; }}
    .filter-form button {{ background:var(--accent); color:#fff; border:none; cursor:pointer; }}
    .filter-form button:hover {{ background:#a05838; }}
  </style>
</head>
<body>
  {sidebar}
  <div class="wrap">
    <form class="filter-form" method="get" action="/ui/backend">
      <input name="workspace" value="{html.escape(workspace_param)}" type="hidden">
      <select name="collection">
        <option value="">All collections</option>
        <option value="session-events.jsonl">session-events.jsonl</option>
        <option value="write-receipts.jsonl">write-receipts.jsonl</option>
        <option value="session-summaries.jsonl">session-summaries.jsonl</option>
        <option value="handoff-history.jsonl">handoff-history.jsonl</option>
        <option value="cross-service-task-memory.jsonl">cross-service-task-memory.jsonl</option>
      </select>
      <input name="project" placeholder="Project / 项目">
      <input name="limit" type="number" value="{limit}" min="1" max="100">
      <button type="submit">Filter / 篮选</button>
    </form>
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


def export_ref_html(workspace_file: str | Path, ref_id: str) -> str:
    from .orchestrator import memory_ref_get

    workspace_param = str(Path(workspace_file).resolve())
    sidebar = _nav_sidebar_html(workspace_param)
    payload = memory_ref_get(workspace_file, ref_id)
    raw = payload.get("raw")
    raw_text = html.escape(json.dumps(raw, ensure_ascii=False, indent=2) if raw is not None else "null")
    timeline_link = ""
    timeline_ref = payload.get("timeline_ref")
    if timeline_ref:
        timeline_link = f'<a class="cross-link" href="{timeline_ref}&workspace={html.escape(workspace_param)}">View in Timeline → / 在时间线中查看 →</a>'
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Reference Detail</title>
  <style>
    :root {{
      --bg: #f6f1e8;
      --panel: #fffdf8;
      --ink: #1e1a16;
      --muted: #6d6357;
      --line: #d9cfc1;
      --accent: #8c4b2f;
    }}
    body {{ margin:0; font-family: Georgia, 'Noto Serif SC', serif; background:var(--bg); color:var(--ink); }}
    .wrap {{ max-width: 1080px; margin-left: 240px; padding: 28px; }}
    .card {{ background:var(--panel); border:1px solid var(--line); border-radius:16px; padding:18px; }}
    .muted {{ color:var(--muted); }}
    .cross-link {{ display:inline-block; margin:8px 0; color:var(--accent); text-decoration:none; font-weight:600; }}
    pre {{ white-space: pre-wrap; word-break: break-word; background:#f2ece3; padding:14px; border-radius:12px; }}
  </style>
</head>
<body>
  {sidebar}
  <div class="wrap">
    <section class="card">
      <h1>{html.escape(str(payload.get('ref_id', 'Reference')))}</h1>
      <div class="muted">{html.escape(str(payload.get('summary', '')))}</div>
      {timeline_link}
      <pre>{raw_text}</pre>
    </section>
  </div>
</body>
</html>
"""


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
    return [
        f"- {item.get('layer', '')} | {item.get('action', '')} | {item.get('target', '')}"
        for item in rows
    ]


def _render_task_list_html(tasks: list[dict[str, Any]]) -> str:
    if not tasks:
        return "<div class='muted'>None</div>"
    items = "".join(
        f"<li><strong><a href=\"/ui/task?task_id={html.escape(str(item.get('task_id', '')))}\">{html.escape(str(item.get('title', item.get('task_id', ''))))}</a></strong> "
        f"<span class='chip'>{html.escape(str(item.get('status', '')))}</span> "
        f"<span class='chip'>quality={html.escape(str(item.get('quality', '')))}</span> "
        f"<span class='chip'>score={html.escape(str(item.get('score', '')))}</span>"
        f"<details><summary>Expand / 展开</summary><pre>{html.escape(json.dumps(item, ensure_ascii=False, indent=2))}</pre></details></li>"
        for item in tasks
    )
    return f"<ul>{items}</ul>"


def _render_handoff_list_html(rows: list[dict[str, Any]]) -> str:
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


def _render_receipt_list_html(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "<div class='muted'>None</div>"
    items = "".join(
        f"<li><strong>{html.escape(str(item.get('layer', '')))}</strong> "
        f"<span class='chip'>{html.escape(str(item.get('action', '')))}</span> "
        f"<span class='muted'>{html.escape(str(item.get('target', '')))}</span>"
        f"<details><summary>Expand / 展开</summary><pre>{html.escape(json.dumps(item, ensure_ascii=False, indent=2))}</pre></details></li>"
        for item in rows
    )
    return f"<ul>{items}</ul>"


def _render_simple_list_html(rows: list[str]) -> str:
    if not rows:
        return "<div class='muted'>None</div>"
    return "<ul>" + "".join(f"<li>{html.escape(str(item))}</li>" for item in rows) + "</ul>"


def _render_ref_list_html(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "<div class='muted'>None</div>"
    items = "".join(
        f"<li><strong><a href=\"/ui/ref?ref_id={html.escape(str(item.get('ref_id', '')))}\">{html.escape(str(item.get('ref_id', '')))}</a></strong> "
        f"<span class='muted'>{html.escape(str(item.get('summary', '')))}</span>"
        f"<details><summary>Expand / 展开</summary><pre>{html.escape(json.dumps(item, ensure_ascii=False, indent=2))}</pre></details></li>"
        for item in rows
    )
    return f"<ul>{items}</ul>"
