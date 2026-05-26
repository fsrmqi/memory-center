"""Token estimation and payload measurement utilities.

Adapted from rtk-ai/rtk's token estimation approach: approximately 4 characters
per token for GPT-style BPE tokenization.
"""
from __future__ import annotations

import json
from typing import Any, Dict


def estimate_tokens(text: str) -> int:
    """Estimate token count from text length.

    Uses the rtk heuristic: ~4 chars per token for GPT-style BPE tokenization.
    """
    return (len(text) + 3) // 4


def measure_payload_size(payload: Dict[str, Any]) -> Dict[str, int]:
    """Measure char and estimated token count of a JSON payload."""
    text = json.dumps(payload, ensure_ascii=False)
    chars = len(text)
    tokens = estimate_tokens(text)
    return {"chars": chars, "tokens": tokens}


def compute_savings(raw_tokens: int, compact_tokens: int) -> Dict[str, Any]:
    """Compute token savings between raw and compact payloads."""
    saved = raw_tokens - compact_tokens
    pct = (saved / raw_tokens * 100) if raw_tokens > 0 else 0.0
    return {
        "raw_tokens": raw_tokens,
        "compact_tokens": compact_tokens,
        "saved_tokens": saved,
        "savings_pct": round(pct, 1),
    }