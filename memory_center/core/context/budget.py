"""Token budget allocator — trim context packs to fit model token budgets.

Provides utilities to estimate token counts and progressively trim context
packs so they fit within the model's context window.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List


# Approximate tokens per character for mixed CJK/English text
_TOKENS_PER_CHAR = 0.5


@dataclass
class TokenBudget:
    """Token budget allocation for a context pack."""
    total: int = 8000
    entrypoints: int = 2000
    relationships: int = 2000
    snippets: int = 2000
    risks: int = 1000
    checklist: int = 1000

    @property
    def remaining(self) -> int:
        return max(0, self.total - self.entrypoints - self.relationships - self.snippets - self.risks - self.checklist)

    def to_dict(self) -> Dict[str, int]:
        return {
            "total": self.total,
            "entrypoints": self.entrypoints,
            "relationships": self.relationships,
            "snippets": self.snippets,
            "risks": self.risks,
            "checklist": self.checklist,
            "remaining": self.remaining,
        }


def estimate_tokens(text: str) -> int:
    """Estimate token count for a string (mixed CJK/English)."""
    return max(1, int(len(text) * _TOKENS_PER_CHAR))


def estimate_dict_tokens(data: Any) -> int:
    """Estimate token count for a dict/list structure."""
    import json
    text = json.dumps(data, ensure_ascii=False)
    return estimate_tokens(text)


def trim_to_budget(items: List[Dict[str, Any]], budget_tokens: int, key: str = "node") -> List[Dict[str, Any]]:
    """Trim a list of items to fit within a token budget."""
    result = []
    used = 0
    for item in items:
        item_tokens = estimate_dict_tokens(item)
        if used + item_tokens > budget_tokens:
            break
        result.append(item)
        used += item_tokens
    return result


def allocate_budget(total: int = 8000) -> TokenBudget:
    """Allocate token budget across context sections."""
    return TokenBudget(
        total=total,
        entrypoints=int(total * 0.25),
        relationships=int(total * 0.25),
        snippets=int(total * 0.25),
        risks=int(total * 0.125),
        checklist=int(total * 0.125),
    )
