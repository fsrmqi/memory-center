from __future__ import annotations

from typing import List

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


def base_tokenize(text: str) -> List[str]:
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