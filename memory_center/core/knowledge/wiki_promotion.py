"""Two-phase promotion of verified DSH delivery summaries into Personal Wiki.

契约（docs/KNOWLEDGE_LINK_INTEGRATION_PLAN.md Write path）：
- preview 只读，产出 delivery candidate 并附带非空 `evidence_refs`（session 引用为底线，task 引用可用时必须附带）；
- confirm 是唯一写 Wiki 的动作（显式人工确认）；任一 Wiki 写入失败即停止，不做补偿式写入；
- 晋升成功后在 Memory Center 登记 KnowledgeLink（不复制正文），`binding_mode=shadow_only`
  的会话强制 workspace-scoped（不得创建 task-scoped 链接），并记录 promotion_confirmed 事件。
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


def wiki_promotion_preview(workspace_file: str | Path, session_id: str, *, wiki_root: str | Path) -> dict[str, Any]:
    from memory_center.core.orchestrator.session import workspace_session_summary

    session = workspace_session_summary(workspace_file, session_id)
    payloads = [
        event.get("payload", {})
        for event in session.get("events", [])
        if event.get("event_type") == "dsh_delivery_summary" and isinstance(event.get("payload", {}), dict)
    ]
    payload = next((item for item in reversed(payloads) if str(item.get("summary", "")).strip()), {})
    summary = str(payload.get("summary", "")).strip()
    if not summary:
        return {"ready": False, "reason": "delivery_summary_missing", "next_action": "先完成一次 DSH 交付摘要捕获，再生成 Wiki 晋升预览。"}
    source_session_id = str(payload.get("source_session_id", "") or session_id)
    task_id = str(payload.get("task_id", "") or "")
    evidence_refs = [f"session:{source_session_id}"]
    if task_id:
        evidence_refs.append(f"task:{task_id}")
    content = summary[:1400]
    return {
        "ready": True,
        "title": content.split("。", 1)[0][:100] or "DSH 交付经验",
        "content": content,
        "source": f"memory-center:{Path(workspace_file).name}:session:{session_id}",
        "source_session_id": session_id,
        "task_id": task_id,
        "evidence_refs": evidence_refs,
        "module": "kaipuyun",
        "knowledge_type": "事实",
        "source_refs": [f"session:{session_id}"],
        "wiki_root": str(Path(wiki_root)),
        "next_action": "预览仅供确认；使用 wiki-promotion-confirm 才会写入 Personal Wiki。",
    }


def confirm_wiki_promotion(
    workspace_file: str | Path,
    session_id: str,
    *,
    wiki_root: str | Path,
    owner: str,
    binding_mode: str = "",
) -> dict[str, Any]:
    from memory_center.core.knowledge.knowledge_events import record_knowledge_event
    from memory_center.core.knowledge.wiki_bridge import register_knowledge_link

    preview = wiki_promotion_preview(workspace_file, session_id, wiki_root=wiki_root)
    if not preview.get("ready"):
        return preview
    evidence_refs = [str(item).strip() for item in preview.get("evidence_refs", []) if str(item).strip()]
    if not evidence_refs:
        return {"ready": False, "reason": "evidence_refs_missing", "next_action": "无证据引用的 delivery candidate 不得晋升。"}
    command = [
        "personal-assistant-wiki-bridge",
        "--knowledge-root", str(wiki_root),
        "promote",
        "--title", preview["title"],
        "--content", preview["content"],
        "--source", preview["source"],
        "--module", preview["module"],
        "--knowledge-type", preview["knowledge_type"],
        "--confirm",
    ]
    for ref in preview["source_refs"]:
        command.extend(["--source-ref", ref])
    result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=20)
    promoted = json.loads(result.stdout)
    from memory_center.application.task_shadow_flow import session_task_binding

    # CLI/plugin input is untrusted: only the immutable session decision may
    # authorize a task-scoped KnowledgeLink.
    decision = session_task_binding(workspace_file, session_id)
    binding_mode = str(decision.get("mode", "shadow_only"))
    task_id = str(decision.get("task_id", "") or "")
    link = register_knowledge_link(
        workspace_file,
        relative_path=str(promoted.get("path", "")),
        title=str(preview.get("title", "")),
        owner=owner,
        wiki_root=wiki_root,
        scope=str(preview.get("module", "kaipuyun")),
        task_id=task_id,
        binding_mode=str(binding_mode).strip(),
        relation_reason=f"DSH 交付摘要经人工确认晋升（session {session_id}）。",
        evidence_refs=evidence_refs,
        actor=owner,
    )
    record_knowledge_event(
        workspace_file,
        event_type="promotion_confirmed",
        payload={
            "session_id": session_id,
            "knowledge_id": link["knowledge_id"],
            "task_id": task_id,
            "path": str(promoted.get("path", ""))[:200],
        },
        actor=owner,
    )
    return {
        "promoted": True,
        "wiki": promoted,
        "knowledge_link": link,
        "next_action": "Wiki 已晋升并登记为 KnowledgeLink；漂移检测自动纳入该链接。",
    }
