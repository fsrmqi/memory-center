"""Claim-boundary reason codes shared by chain gating and freshness contracts.

``mc_lookup(mode="chain")`` 的空结果可能只是锚定失败或范围缺失的副作用，不能当作
"目标没有调用方"的证据。这里集中定义这组 reason code 的映射，供 orchestration
层的门禁投影与 core/freshness 的契约装配共同使用；两侧都不得反向依赖对方。

Chain-gate status and claim-boundary reason codes are deliberately separate
vocabularies: ``"mismatch"`` describes the gate, ``"anchor_mismatch"`` is the
reason code surfaced to callers.
"""
from __future__ import annotations

from typing import Any

ANCHOR_MATCHED_STATUS = "matched"
REASON_ANCHOR_MISMATCH = "anchor_mismatch"
REASON_SCOPE_INCOMPLETE = "scope_incomplete"


def gate_reasons_from_chain(chain_gate: dict[str, Any] | None) -> list[str]:
    """Map chain anchor/scope validation onto claim-boundary reason codes."""
    if not isinstance(chain_gate, dict):
        return []
    reasons: list[str] = []
    if str(chain_gate.get("anchor_status", "")) != ANCHOR_MATCHED_STATUS:
        reasons.append(REASON_ANCHOR_MISMATCH)
    if chain_gate.get("scope_incomplete"):
        reasons.append(REASON_SCOPE_INCOMPLETE)
    return reasons
