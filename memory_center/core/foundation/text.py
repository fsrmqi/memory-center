from __future__ import annotations

import re

CJK_UNIFIED_START = "一"
CJK_UNIFIED_END = "鿿"
CJK_EXT_A_START = "㐀"
CJK_EXT_A_END = "䶿"
CJK_COMPAT_START = "豈"
CJK_COMPAT_END = "﫿"


def _is_single_cjk(item: str) -> bool:
    if len(item) != 1:
        return False
    ch = item
    return (
        CJK_UNIFIED_START <= ch <= CJK_UNIFIED_END
        or CJK_EXT_A_START <= ch <= CJK_EXT_A_END
        or CJK_COMPAT_START <= ch <= CJK_COMPAT_END
    )


def base_tokenize(text: str) -> list[str]:
    raw = ""
    prev_is_cjk = False
    for ch in text:
        is_cjk = (
            CJK_UNIFIED_START <= ch <= CJK_UNIFIED_END
            or CJK_EXT_A_START <= ch <= CJK_EXT_A_END
            or CJK_COMPAT_START <= ch <= CJK_COMPAT_END
        )
        is_alnum = ch.isalnum()
        if is_cjk or is_alnum:
            if is_cjk != prev_is_cjk and raw and raw[-1] != " ":
                raw += " "
            raw += ch.lower()
            prev_is_cjk = is_cjk
        else:
            if raw and raw[-1] != " ":
                raw += " "
            prev_is_cjk = False
    return list({item for item in raw.split() if len(item) >= 2 or _is_single_cjk(item)})


def merge_markdown_section(existing: str, section_title: str, body: str) -> str:
    marker = f"## {section_title}"
    replacement = f"{marker}\n\n{body.strip()}\n"
    if not existing.strip():
        return replacement

    lines = existing.splitlines()
    target_start = None
    target_end = None

    for idx, line in enumerate(lines):
        match = re.match(r"^(#{1,6})\s+(.*)$", line)
        if not match:
            continue
        level = len(match.group(1))
        title = match.group(2).strip()
        if target_start is None:
            if level == 2 and title == section_title:
                target_start = idx
            continue
        if level <= 2:
            target_end = idx
            break

    if target_start is None:
        return existing.rstrip() + f"\n\n{replacement}"

    if target_end is None:
        target_end = len(lines)

    prefix = "\n".join(lines[:target_start]).rstrip()
    suffix = "\n".join(lines[target_end:]).lstrip()

    parts = []
    if prefix:
        parts.append(prefix)
    parts.append(replacement.rstrip())
    if suffix:
        parts.append(suffix)
    return "\n\n".join(parts).rstrip() + "\n"
