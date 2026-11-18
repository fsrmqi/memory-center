"""Wiki 晋升的确认编排（application 层）。

晋升分两段：
- ``core.knowledge.wiki_promotion.wiki_promotion_preview`` 只读地产出 delivery candidate；
- 本模块的 ``confirm_wiki_promotion`` 负责确认后的编排——组装 bridge 命令、执行子进程、
  读取会话不可变决策，再登记 KnowledgeLink 与 ``promotion_confirmed`` 事件。

归属说明：确认编排同时需要 core 的预览/登记能力、application 的任务绑定决策（
``session_task_binding``）与共享异常 ``WikiError``。此前它位于
``core.knowledge.wiki_promotion``，导致 core 反向依赖 application 与 platform
（ADR-0001 明确禁止以延迟导入规避）。按分层方向上移到此处；``WikiError`` 已下沉到
``core.knowledge.wiki_errors``，平台侧 ``platform.assistant.core`` 保留再导出。
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from memory_center.application.task_shadow_flow import session_task_binding
from memory_center.core.knowledge.knowledge_events import record_knowledge_event
from memory_center.core.knowledge.wiki_bridge import register_knowledge_link
from memory_center.core.knowledge.wiki_errors import WikiError
from memory_center.core.knowledge.wiki_promotion import (
    build_promote_command,
    resolve_promotion_profile,
    wiki_promotion_preview,
)
from memory_center.core.profiles import Profile


def confirm_wiki_promotion(
    workspace_file: str | Path,
    session_id: str,
    *,
    wiki_root: str | Path,
    owner: str,
    binding_mode: str = "",
    profile: Profile | str | Path | None = None,
) -> dict[str, Any]:
    preview = wiki_promotion_preview(workspace_file, session_id, wiki_root=wiki_root, profile=profile)
    if not preview.get("ready"):
        return preview
    evidence_refs = [str(item).strip() for item in preview.get("evidence_refs", []) if str(item).strip()]
    if not evidence_refs:
        return {"ready": False, "reason": "evidence_refs_missing", "next_action": "无证据引用的 delivery candidate 不得晋升。"}
    prof = resolve_promotion_profile(workspace_file, profile)
    scope = str(preview.get("module") or prof.default_scope or "").strip()
    if not scope:
        # 预览可以中立展示，但写入必须有归属范围；给出可操作的配置指引。
        raise WikiError("未配置默认 scope：请先在 workspace profile 设置 default_scope（或携带 profile）再确认 Wiki 晋升。")
    command = build_promote_command(preview, wiki_root)
    result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=20, shell=False)
    promoted = json.loads(result.stdout)

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
        scope=scope,
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


__all__ = ["confirm_wiki_promotion"]
