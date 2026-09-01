"""会话事件的滚动归档规划器(纯策略,无 IO/模型依赖)。

设计参考 OpenViking 的 session/retention:planner 刻意不接触文件系统和
模型,只对事件列表做"逻辑轮次聚合 + token 预算下的 archive/live 边界
选择"。执行(写归档文件、prune 原集合)由 orchestrator 侧完成,便于单测
与后续调整预算策略。

MC 的事件形态与 OV 不同:没有严格的 user/assistant 消息流,而是
event_type + payload 的追加日志。这里把"开启新逻辑轮次"的事件
(user_prompt / note / session_start)作为轮次边界,工具事件归属当前轮次。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from memory_center.core.foundation.tokens import estimate_tokens

RETENTION_MODE_TURN_BUDGET = "turn_budget"

# 默认保留的最近轮次数;归档边界始终落在轮次边界上,不切断一轮。
DEFAULT_KEEP_RECENT_TURNS = 3
DEFAULT_MAX_ARCHIVE_TOKENS = 20000
# 事件 payload 的 token 估算上限:超限时按上限计,避免单条巨型 payload
# 把整轮预算顶爆(真实 payload 已被 offload,事件内只是 compact 摘要)。
_PER_EVENT_TOKEN_CAP = 2000

# 开启新逻辑轮次的事件类型。
_TURN_BOUNDARY_EVENTS = frozenset({"user_prompt", "user_prompt_submit", "note", "session_start"})
# 结束会话后的系统事件,始终保留在 live 段(它们是恢复/审计锚点)。
_LIVE_ANCHOR_EVENTS = frozenset({"session_end", "session_close"})


@dataclass(frozen=True)
class TurnSegment:
    """一个逻辑轮次:边界事件 + 归属其后的工具事件。"""

    turn_index: int
    start_event_index: int
    end_event_index: int  # 含
    event_count: int
    tokens: int
    label: str


@dataclass(frozen=True)
class RetentionDecision:
    """归档规划结果:边界之前的轮次归档,之后(含)的轮次保留在 live。"""

    mode: str = RETENTION_MODE_TURN_BUDGET
    total_events: int = 0
    total_turns: int = 0
    total_tokens: int = 0
    archive_turns: int = 0
    archive_events: int = 0
    archive_tokens: int = 0
    keep_turns: int = 0
    keep_events: int = 0
    keep_tokens: int = 0
    boundary_event_index: int = 0  # 第一条保留事件的下标;== total_events 表示无可归档
    turns: list[TurnSegment] = field(default_factory=list)
    reason: str = ""


def _event_tokens(event: dict[str, Any]) -> int:
    text = json.dumps(event.get("payload", {}), ensure_ascii=False)
    return min(estimate_tokens(text) + 8, _PER_EVENT_TOKEN_CAP)


def _event_type(event: dict[str, Any]) -> str:
    return str(event.get("event_type", "") or "")


def _turn_label(event: dict[str, Any]) -> str:
    payload = event.get("payload", {})
    if isinstance(payload, dict):
        for key in ("intent", "query", "note", "prompt", "text", "summary"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:80]
    return _event_type(event)


def group_turns(events: list[dict[str, Any]]) -> list[TurnSegment]:
    """把扁平事件序列聚合为逻辑轮次;首个事件总是新轮次的开始。"""
    turns: list[TurnSegment] = []
    current: TurnSegment | None = None
    for index, event in enumerate(events):
        tokens = _event_tokens(event)
        is_boundary = _event_type(event) in _TURN_BOUNDARY_EVENTS
        if current is None or is_boundary:
            current = TurnSegment(
                turn_index=len(turns),
                start_event_index=index,
                end_event_index=index,
                event_count=1,
                tokens=tokens,
                label=_turn_label(event),
            )
            turns.append(current)
        else:
            current = TurnSegment(
                turn_index=current.turn_index,
                start_event_index=current.start_event_index,
                end_event_index=index,
                event_count=current.event_count + 1,
                tokens=current.tokens + tokens,
                label=current.label,
            )
            turns[-1] = current
    return turns


def plan_retention(
    events: list[dict[str, Any]],
    *,
    keep_recent_turns: int = DEFAULT_KEEP_RECENT_TURNS,
    max_archive_tokens: int = DEFAULT_MAX_ARCHIVE_TOKENS,
) -> RetentionDecision:
    """在 token 预算与轮次约束下选择 archive/live 边界。

    规则(与 OV 同源的保守取向):
    1. 归档候选只取"除最近 keep_recent_turns 轮之外"的旧轮次;
    2. 候选轮次从旧到新累加,直到达到 max_archive_tokens 或轮次耗尽;
    3. live 段锚点事件(session_end 等)永不归档——若落在归档边界内,
       边界收缩到锚点之后,保证恢复链路始终能看到结束标记;
    4. 不足 keep_recent_turns 轮时不归档(noop)。
    """
    if not events:
        return RetentionDecision(reason="no_events")
    turns = group_turns(events)
    total_tokens = sum(turn.tokens for turn in turns)
    if len(turns) <= keep_recent_turns:
        return RetentionDecision(
            total_events=len(events),
            total_turns=len(turns),
            total_tokens=total_tokens,
            keep_turns=len(turns),
            keep_events=len(events),
            keep_tokens=total_tokens,
            boundary_event_index=len(events),
            reason=f"below_keep_recent_turns({len(turns)}<={keep_recent_turns})",
        )

    if keep_recent_turns < 0:
        raise ValueError("keep_recent_turns must be >= 0")
    if max_archive_tokens < 0:
        raise ValueError("max_archive_tokens must be >= 0")

    archive_turns: list[TurnSegment] = []
    archive_tokens = 0
    candidate_turns = turns if keep_recent_turns == 0 else turns[:-keep_recent_turns]
    for turn in candidate_turns:
        # 锚点不能被拆出当前轮次：该轮及其后的事件全部保持 live，保证
        # archive/live 边界始终是完整轮次的边界。
        if any(_event_type(event) in _LIVE_ANCHOR_EVENTS for event in events[turn.start_event_index : turn.end_event_index + 1]):
            break
        if archive_tokens + turn.tokens > max_archive_tokens:
            break
        archive_turns.append(turn)
        archive_tokens += turn.tokens

    if not archive_turns:
        return RetentionDecision(
            total_events=len(events),
            total_turns=len(turns),
            total_tokens=total_tokens,
            keep_turns=len(turns),
            keep_events=len(events),
            keep_tokens=total_tokens,
            boundary_event_index=len(events),
            reason="archive_budget_exhausted",
        )

    boundary = archive_turns[-1].end_event_index + 1

    kept_events = len(events) - boundary
    kept_turns = len(turns) - len(archive_turns)
    kept_tokens = total_tokens - sum(turn.tokens for turn in archive_turns)
    return RetentionDecision(
        total_events=len(events),
        total_turns=len(turns),
        total_tokens=total_tokens,
        archive_turns=len(archive_turns),
        archive_events=boundary,
        archive_tokens=sum(turn.tokens for turn in archive_turns),
        keep_turns=kept_turns,
        keep_events=kept_events,
        keep_tokens=kept_tokens,
        boundary_event_index=boundary,
        turns=turns,
        reason="planned",
    )


__all__ = [
    "RETENTION_MODE_TURN_BUDGET",
    "DEFAULT_KEEP_RECENT_TURNS",
    "DEFAULT_MAX_ARCHIVE_TOKENS",
    "RetentionDecision",
    "TurnSegment",
    "group_turns",
    "plan_retention",
]
