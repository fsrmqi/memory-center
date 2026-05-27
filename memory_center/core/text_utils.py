from __future__ import annotations

from typing import List


def base_tokenize(text: str) -> List[str]:
    # Build tokens, inserting spaces between Chinese and ASCII boundaries
    raw = ""
    prev_is_cjk = False
    for ch in text:
        is_cjk = "一" <= ch <= "鿿"
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
    return sorted({item for item in raw.split() if len(item) >= 2 or ("一" <= item <= "鿿")})
