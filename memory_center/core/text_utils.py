from __future__ import annotations

from typing import List


def base_tokenize(text: str) -> List[str]:
    raw = "".join(ch.lower() if ch.isalnum() or "一" <= ch <= "鿿" else " " for ch in text)
    return sorted({item for item in raw.split() if len(item) >= 2})
