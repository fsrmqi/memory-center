"""Two-phase promotion of verified DSH delivery summaries into Personal Wiki.

契约（docs/KNOWLEDGE_LINK_INTEGRATION_PLAN.md Write path）：
- preview 只读，产出 delivery candidate 并附带非空 `evidence_refs`（session 引用为底线，task 引用可用时必须附带）；
- confirm 是唯一写 Wiki 的动作（显式人工确认）；任一 Wiki 写入失败即停止，不做补偿式写入；
- 晋升成功后在 Memory Center 登记 KnowledgeLink（不复制正文），`binding_mode=shadow_only`
  的会话强制 workspace-scoped（不得创建 task-scoped 链接），并记录 promotion_confirmed 事件。

归属：本模块只保留只读的 preview 与参数组装（纯 core 能力）。确认阶段的编排
（执行 bridge 子进程、读取会话不可变决策、登记 KnowledgeLink 与事件）已上移到
``memory_center.application.wiki_promotion``——它需要 application 的任务绑定决策，
留在 core 会构成反向依赖（ADR-0001）。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from memory_center.core.profiles import Profile, profile_for_workspace, resolve_profile
from memory_center.core.storage.workspace import WorkspaceStore

SESSION_EVENTS_FILE = "session-events.jsonl"


def resolve_promotion_profile(
    workspace_file: str | Path,
    profile: Profile | str | Path | None,
) -> Profile:
    """Explicit ``profile`` wins; otherwise honour the workspace ``profile:`` then env."""
    return resolve_profile(profile) if profile is not None else profile_for_workspace(workspace_file)


def wiki_promotion_preview(
    workspace_file: str | Path,
    session_id: str,
    *,
    wiki_root: str | Path,
    profile: Profile | str | Path | None = None,
) -> dict[str, Any]:
    # 直接读 session-events（与 workspace_session_summary 同源、同 50 条窗口）：
    # knowledge 属 core 引擎层，不得反向依赖 orchestrator（ADR-0002 §4.4）。
    store = WorkspaceStore(workspace_file)
    events = store.find_jsonl_via_backend(
        SESSION_EVENTS_FILE,
        lambda row: row.get("session_id") == session_id,
        limit=1000,
        session_id=session_id,
    )[-50:]
    payloads = [
        event.get("payload", {})
        for event in events
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
    prof = resolve_promotion_profile(workspace_file, profile)
    return {
        "ready": True,
        "title": content.split("。", 1)[0][:100] or "DSH 交付经验",
        "content": content,
        "source": f"memory-center:{Path(workspace_file).name}:session:{session_id}",
        "source_session_id": session_id,
        "task_id": task_id,
        "evidence_refs": evidence_refs,
        "module": prof.default_scope or "",
        "knowledge_type": "事实",
        "source_refs": [f"session:{session_id}"],
        "wiki_root": str(Path(wiki_root)),
        "next_action": "预览仅供确认；使用 wiki-promotion-confirm 才会写入 Personal Wiki。",
    }


def _clean_bridge_arg(value: Any, *, max_len: int = 1600) -> str:
    """清洗传给 personal-assistant-wiki-bridge 的参数值。

    ``subprocess.run(list, shell=False)`` 不经 shell，但 delivery payload 是
    会话内容，仍需剥离控制字符并去掉选项样前缀，防止下游 CLI 把内容误当 flag。
    """
    text = str(value or "")
    cleaned = "".join(ch for ch in text if ch.isprintable()).strip()
    cleaned = cleaned.lstrip("-")[:max_len]
    return cleaned


def build_promote_command(preview: dict[str, Any], wiki_root: str | Path) -> list[str]:
    """组装 promote 子命令参数；所有会话内容先经 ``_clean_bridge_arg`` 清洗。

    返回纯参数列表供 ``subprocess.run(..., shell=False)`` 使用，不经 shell。
    """
    args: list[str] = [
        "personal-assistant-wiki-bridge",
        "--knowledge-root", _clean_bridge_arg(wiki_root, max_len=1024),
        "promote",
        "--title", _clean_bridge_arg(preview.get("title", ""), max_len=120),
        "--content", _clean_bridge_arg(preview.get("content", ""), max_len=1600),
        "--source", _clean_bridge_arg(preview.get("source", ""), max_len=300),
        "--module", _clean_bridge_arg(preview.get("module", ""), max_len=60),
        "--knowledge-type", _clean_bridge_arg(preview.get("knowledge_type", ""), max_len=20),
        "--confirm",
    ]
    for ref in preview.get("source_refs", []):
        cleaned_ref = _clean_bridge_arg(ref, max_len=300)
        if cleaned_ref:
            args += ["--source-ref", cleaned_ref]
    # Session-first：delivery 锚点经清洗后作为审计标注传给 Wiki bridge；
    # task-scoped KnowledgeLink 的授权仍由 session 不可变决策决定。
    anchor_task_id = _clean_bridge_arg(preview.get("task_id", ""), max_len=120)
    if anchor_task_id:
        args += ["--task-id", anchor_task_id]
    return args


__all__ = [
    "SESSION_EVENTS_FILE",
    "resolve_promotion_profile",
    "wiki_promotion_preview",
    "build_promote_command",
]
