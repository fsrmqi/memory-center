"""Governed reverse links from Personal Assistant Wiki into a workspace."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .assets import register_collaboration_asset

_DEFAULT_DOCUMENTS = (
    "工作/开普云/索引.md",
    "工作/开普云/项目/众包平台.md",
    "技术/项目/MemoryCenter.md",
    "技术/项目/PersonalAssistantWikiMCP.md",
)


def sync_personal_wiki_assets(
    workspace_file: str | Path,
    *,
    wiki_root: str | Path,
    owner: str,
    scope: str = "kaipuyun",
    documents: list[str] | None = None,
) -> dict[str, Any]:
    """Register selected Personal Wiki entries as links, never copied bodies."""
    root = Path(wiki_root).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("wiki_root must be an existing directory")
    selected = documents or list(_DEFAULT_DOCUMENTS)
    assets: list[dict[str, Any]] = []
    skipped: list[str] = []
    for relative in selected[:20]:
        path = (root / relative).resolve()
        if root not in path.parents or not path.is_file() or path.suffix.lower() not in {".md", ".markdown"}:
            skipped.append(relative)
            continue
        raw = path.read_bytes()
        title = _title(raw.decode("utf-8", errors="replace"), path.stem)
        content_hash = hashlib.sha256(raw).hexdigest()
        knowledge_id = f"pawiki-{hashlib.sha256(relative.encode('utf-8')).hexdigest()[:16]}"
        result = register_collaboration_asset(
            workspace_file,
            kind="wiki",
            title=title,
            owner=owner,
            source_ref=f"pawiki:{relative}",
            visibility="private",
            tags=["personal-wiki", scope, "ucap"],
            context_excerpt="Personal Assistant Wiki 长期知识入口；正文保留在 Wiki，仅通过来源引用按需读取。",
            metadata={
                "knowledge_id": knowledge_id,
                "content_sha256": content_hash,
                "scope": scope,
                "source_task_id": "",
                "evidence_refs": [],
                "bridge": "personal_assistant_wiki",
            },
            asset_id=f"asset-wiki-{knowledge_id}",
            actor=owner,
        )
        assets.append(result["asset"])
    return {
        "synced": True,
        "scope": scope,
        "assets": assets,
        "skipped": skipped,
        "next_action": "DSH 的知识页可展示这些 Wiki 反向链接；Wiki 正文仍留在 Personal Assistant Wiki。",
    }


def _title(text: str, fallback: str) -> str:
    for line in text.splitlines()[:80]:
        if line.startswith("#"):
            title = line.lstrip("#").strip()
            if title:
                return title[:200]
    return fallback[:200]
