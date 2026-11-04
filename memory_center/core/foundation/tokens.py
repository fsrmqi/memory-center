"""Token estimation and payload measurement utilities.

Adapted from rtk-ai/rtk's token estimation approach: approximately 4 characters
per token for GPT-style BPE tokenization.
"""
from __future__ import annotations

import json
import os
from typing import Any


def estimate_tokens(text: str) -> int:
    """Estimate token count from text length.

    Uses the rtk heuristic: ~4 chars per token for GPT-style BPE tokenization.
    """
    return (len(text) + 3) // 4


def measure_payload_size(payload: dict[str, Any]) -> dict[str, int]:
    """Measure char and estimated token count of a JSON payload."""
    text = json.dumps(payload, ensure_ascii=False)
    chars = len(text)
    tokens = estimate_tokens(text)
    return {"chars": chars, "tokens": tokens}


def compute_savings(raw_tokens: int, compact_tokens: int) -> dict[str, Any]:
    """Compute token savings between raw and compact payloads."""
    saved = raw_tokens - compact_tokens
    pct = (saved / raw_tokens * 100) if raw_tokens > 0 else 0.0
    return {
        "raw_tokens": raw_tokens,
        "compact_tokens": compact_tokens,
        "saved_tokens": saved,
        "savings_pct": round(pct, 1),
    }


def measure_compact_gain(raw_result: dict[str, Any], compact_result: dict[str, Any]) -> dict[str, Any]:
    """按环境开关计算紧凑视图的 Token 收益，不依赖编排层。"""
    if os.getenv("MEMORY_CENTER_MEASURE_COMPACT_GAIN", "").strip().lower() not in {"1", "true", "yes"}:
        return {"raw_tokens": 0, "compact_tokens": 0, "saved_tokens": 0, "reduction_rate": 0.0, "measured": False}
    return {**compute_savings(estimate_tokens(json.dumps(raw_result, ensure_ascii=False)), estimate_tokens(json.dumps(compact_result, ensure_ascii=False))), "measured": True}
