"""case 热度分(设计参考 OpenViking retrieve/memory_lifecycle 的 hotness_score)。

纯函数:频率分量 sigmoid(log1p(active_count)) 与指数时间衰减(默认半衰期
7 天)相乘,输出 0.0-1.0。不依赖模型、不碰存储;调用方负责从检索日志统计
active_count 并提供 updated_at。

MC 的用途:给 L1 case 排序加有界热度权重,让高频命中且最近仍被使用的
case 排前,长期未命中的 case 自然沉底——不引入第二套计数 schema,直接
复用已有 session events / guidance 记录。
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

DEFAULT_HALF_LIFE_DAYS = 7.0


def hotness_score(
    active_count: int,
    updated_at: datetime | str | None,
    now: datetime | None = None,
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
) -> float:
    """Compute a 0.0-1.0 hotness score from access count and recency.

    - frequency: sigmoid(log1p(active_count)) in (0, 1);0 次命中也不为 0,
      保证新 case 仍能参与排序。
    - recency: exponential decay with configurable half-life;无时间戳时
      返回 0.0(与 OV 同语义:没有时间证据就没有热度)。
    """
    if now is None:
        now = datetime.now(timezone.utc)

    # 零命中没有真实访问证据，必须是零热度；否则 sigmoid(0) 会产生
    # 0.5，使直接调用者与 case 排序的零命中语义不一致。
    if int(active_count or 0) <= 0:
        return 0.0

    freq = 1.0 / (1.0 + math.exp(-math.log1p(max(int(active_count or 0), 0))))

    if updated_at is None:
        return 0.0
    if isinstance(updated_at, str):
        try:
            updated_at = datetime.fromisoformat(updated_at)
        except ValueError:
            return 0.0
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    age_days = max((now - updated_at).total_seconds() / 86400.0, 0.0)
    decay_rate = math.log(2) / max(half_life_days, 1e-6)
    recency = math.exp(-decay_rate * age_days)
    return freq * recency


def case_last_hit(events: list[dict[str, Any]], case_task: str) -> tuple[int, str]:
    """从 session events 中统计某条 case(按 task 标识)的命中次数与最近命中时间。

    命中信号(全部为既有记录,不新增 schema):
    - event_type == "agent_guidance" 且 payload 含 case task 文本;
    - event_type == "case_hit" (留作未来显式记录)。
    返回 (hit_count, last_hit_created_at);无命中返回 (0, "")。
    """
    needle = str(case_task or "").strip().lower()
    if not needle:
        return 0, ""
    hits = 0
    last_at = ""
    for event in events:
        event_type = str(event.get("event_type", "") or "")
        if event_type not in {"agent_guidance", "case_hit"}:
            continue
        payload = event.get("payload", {})
        if not isinstance(payload, dict):
            continue
        haystack = ""
        query = payload.get("query")
        if isinstance(query, str):
            haystack = query.lower()
        else:
            import json as _json

            haystack = _json.dumps(payload, ensure_ascii=False).lower()
        if needle in haystack:
            hits += 1
            created_at = str(event.get("created_at", "") or "")
            if created_at > last_at:
                last_at = created_at
    return hits, last_at


def rank_cases_by_hotness(
    cases: list[dict[str, Any]],
    events: list[dict[str, Any]],
    *,
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """按热度分降序返回 case 列表(稳定排序:同分保持原顺序)。

    每个 case 附加 `hotness` 与 `hit_count` 字段(additive);排序不改变
    返回集合本身,只改变顺序。
    """
    if not cases:
        return []
    current_time = now or datetime.now(timezone.utc)
    scored: list[tuple[float, int, dict[str, Any]]] = []
    for index, case in enumerate(cases):
        task = str(case.get("task", "") or "")
        hits, last_at = case_last_hit(events, task)
        # 时间锚优先用最近命中时间;无命中时不使用 valid_from——否则微秒级
        # 创建时间差会让同分 case 被"最新创建优先"重排,破坏调用方的原序语义
        # (评估与既有排序都依赖稳定顺序)。无命中 → 热度记 0,保持原位。
        anchor = last_at or None
        if hits <= 0:
            enriched = {**case, "hotness": 0.0, "hit_count": 0}
            scored.append((0.0, index, enriched))
            continue
        score = hotness_score(hits, anchor, now=current_time, half_life_days=half_life_days)
        enriched = {**case, "hotness": round(score, 4), "hit_count": hits}
        scored.append((score, index, enriched))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in scored]


__all__ = [
    "DEFAULT_HALF_LIFE_DAYS",
    "hotness_score",
    "case_last_hit",
    "rank_cases_by_hotness",
]
