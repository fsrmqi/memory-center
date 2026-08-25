"""Two-phase promotion of verified DSH delivery summaries into Personal Wiki."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


def wiki_promotion_preview(workspace_file: str | Path, session_id: str, *, wiki_root: str | Path) -> dict[str, Any]:
    from memory_center.core.orchestrator.session import workspace_session_summary

    session = workspace_session_summary(workspace_file, session_id)
    summaries = [event.get("payload", {}).get("summary", "") for event in session.get("events", []) if event.get("event_type") == "dsh_delivery_summary"]
    summary = next((str(item).strip() for item in reversed(summaries) if str(item).strip()), "")
    if not summary:
        return {"ready": False, "reason": "delivery_summary_missing", "next_action": "先完成一次 DSH 交付摘要捕获，再生成 Wiki 晋升预览。"}
    content = summary[:1400]
    return {
        "ready": True,
        "title": content.split("。", 1)[0][:100] or "DSH 交付经验",
        "content": content,
        "source": f"memory-center:{Path(workspace_file).name}:session:{session_id}",
        "source_session_id": session_id,
        "module": "kaipuyun",
        "knowledge_type": "事实",
        "source_refs": [f"session:{session_id}"],
        "wiki_root": str(Path(wiki_root)),
        "next_action": "预览仅供确认；使用 wiki-promotion-confirm 才会写入 Personal Wiki。",
    }


def confirm_wiki_promotion(workspace_file: str | Path, session_id: str, *, wiki_root: str | Path, owner: str) -> dict[str, Any]:
    preview = wiki_promotion_preview(workspace_file, session_id, wiki_root=wiki_root)
    if not preview.get("ready"):
        return preview
    command = ["personal-assistant-wiki-bridge", "--knowledge-root", str(wiki_root), "promote", "--title", preview["title"], "--content", preview["content"], "--source", preview["source"], "--module", preview["module"], "--knowledge-type", preview["knowledge_type"], "--confirm"]
    for ref in preview["source_refs"]:
        command.extend(["--source-ref", ref])
    result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=20)
    promoted = json.loads(result.stdout)
    from .wiki_bridge import sync_personal_wiki_assets

    synced = sync_personal_wiki_assets(workspace_file, wiki_root=wiki_root, owner=owner, documents=[promoted["path"]])
    return {"promoted": True, "wiki": promoted, "asset_sync": synced, "next_action": "Wiki 已晋升并登记为 Memory Center 资产。"}
