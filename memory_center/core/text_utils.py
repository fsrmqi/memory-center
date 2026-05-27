from __future__ import annotations

from typing import List


def base_tokenize(text: str) -> List[str]:
    raw = ""
    prev_is_cjk = False
    for ch in text:
        is_cjk = (
            "一" <= ch <= "鿿"   # CJK Unified Ideographs
            or "㐀" <= ch <= "䶿"  # CJK Extension A
            or "豈" <= ch <= "﫿"  # CJK Compatibility Ideographs
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
    cjk_range_start = "㐀"
    cjk_range_end = "﫿"
    return sorted({item for item in raw.split() if len(item) >= 2 or (cjk_range_start <= item <= cjk_range_end)})
