from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any


def slugify_walkthrough_symbol(symbol: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.#-]+", "-", symbol or "walkthrough").strip("-")
    slug = slug.replace("#", "__")
    return slug[:180] or "walkthrough"


def render_walkthrough_markdown(
    workspace: str,
    symbol: str,
    result: dict[str, Any],
    *,
    read_targets: str,
    title: str = "",
) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    heading = title.strip() or f"Walkthrough: {symbol}"
    body = result.get("answer_markdown", "") or "\n".join(result.get("summary_lines", []) or [])
    mermaid = result.get("mermaid_flow", "")
    quality = {
        "schema_version": result.get("schema_version", 0),
        "index_stale": (result.get("index_freshness", {}) or {}).get("index_stale", False),
        "cache": result.get("cache", {}),
    }
    parts = [
        f"# {heading}",
        "",
        f"- Workspace: `{workspace}`",
        f"- Symbol: `{symbol}`",
        f"- Generated: `{stamp}`",
        f"- Schema: `{quality['schema_version']}`",
        f"- Index stale: `{quality['index_stale']}`",
        "",
        body.strip(),
    ]
    if mermaid:
        parts.extend(["", "## Mermaid", "", "```mermaid", mermaid, "```"])
    parts.extend(["", "## Read Targets", "", read_targets or "- 无"])
    parts.extend(["", "## Quality Metadata", "", "```json", json.dumps(quality, ensure_ascii=False, indent=2), "```", ""])
    return "\n".join(parts)
