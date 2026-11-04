"""类型化字段合并算子(case/schema 字段的更新纪律)。

设计参考 OpenViking 的 session/memory/merge_op 包:每个 schema 字段声明一个
合并算子,更新已有记忆时按算子纪律应用,而不是整体覆盖:

- immutable:禁止修改;尝试修改即报错(如 case name / task 标识)。
- replace:整体替换;None 视为"未提供",保留现值。
- append:列表字段追加去重项;字符串字段换行追加。
- sum:数值累计;无效输入保留现值(与 OV SumOp 同源的宽容语义)。
- patch:字符串 SEARCH/REPLACE 块;匹配失败时保守报错,绝不猜测重写。

所有算子都是纯函数;调用方(consolidation approve / 未来字段级更新入口)
负责在 workspace 锁内持久化结果。
"""
from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class MergeOp(str, Enum):
    IMMUTABLE = "immutable"
    REPLACE = "replace"
    APPEND = "append"
    SUM = "sum"
    PATCH = "patch"


class MergeOpError(ValueError):
    """合并纪律被违反(immutable 修改、patch 匹配失败等)。"""


# ---------------------------------------------------------------------------
# SEARCH/REPLACE 块(patch 字段的结构化更新格式)
# ---------------------------------------------------------------------------

SEARCH_START = "<<<<<<< SEARCH"
SEARCH_END = "=======REPLACE======="
REPLACE_END = ">>>>>>> END"


@dataclass(frozen=True)
class SearchReplaceBlock:
    search: str
    replace: str


@dataclass(frozen=True)
class StrPatch:
    blocks: list[SearchReplaceBlock] = field(default_factory=list)


def parse_str_patch(text: str) -> StrPatch:
    """解析 SEARCH/REPLACE 块文本;块内容按行剥离首尾换行。无有效块时返回空 patch。"""
    blocks: list[SearchReplaceBlock] = []
    pattern = re.compile(
        re.escape(SEARCH_START) + r"\n(.*?\n)" + re.escape(SEARCH_END) + r"\n(.*?\n)" + re.escape(REPLACE_END),
        re.DOTALL,
    )
    for match in pattern.finditer(text or ""):
        blocks.append(
            SearchReplaceBlock(
                search=match.group(1).strip("\n"),
                replace=match.group(2).strip("\n"),
            )
        )
    return StrPatch(blocks=blocks)


def apply_str_patch(current: str, patch: StrPatch) -> str:
    """按块顺序应用 SEARCH/REPLACE;任一块匹配失败即抛错,不做模糊猜测。"""
    result = current
    for index, block in enumerate(patch.blocks):
        search = block.search
        replace = block.replace
        if not search:
            continue
        if search in result:
            result = result.replace(search, replace, 1)
            continue
        # 行级宽容:SEARCH 只有一行且原文不含该行时,按行匹配替换该行。
        if "\n" not in search:
            lines = result.split("\n")
            for line_index, line in enumerate(lines):
                if line.strip() == search.strip():
                    lines[line_index] = replace
                    result = "\n".join(lines)
                    break
            else:
                raise MergeOpError(
                    f"patch block {index}: SEARCH 行未命中({search[:60]!r});"
                    "请阅读最新内容后重新生成 patch,不要猜测。"
                )
            continue
        raise MergeOpError(
            f"patch block {index}: SEARCH 文本未命中({search[:60]!r});"
            "请阅读最新内容后重新生成 patch,不要猜测。"
        )
    return result


# ---------------------------------------------------------------------------
# 字段算子
# ---------------------------------------------------------------------------


def apply_merge_op(
    op: MergeOp,
    field_name: str,
    current_value: Any,
    incoming_value: Any,
) -> Any:
    """对单个字段按算子纪律合并,返回新值。

    incoming_value 为 None 统一视为"未提供",保留现值(patch 除外:
    patch 用显式块表达"不改"),immutable 例外(提供不同值即违规)。
    """
    if op is MergeOp.IMMUTABLE:
        if incoming_value is None or incoming_value == current_value:
            return current_value
        raise MergeOpError(f"字段 {field_name} 为 immutable,不允许修改(现值与提供值不一致)")

    if incoming_value is None:
        return current_value

    if op is MergeOp.REPLACE:
        return incoming_value

    if op is MergeOp.APPEND:
        return _apply_append(field_name, current_value, incoming_value)

    if op is MergeOp.SUM:
        return _apply_sum(field_name, current_value, incoming_value)

    if op is MergeOp.PATCH:
        return _apply_patch(field_name, current_value, incoming_value)

    raise MergeOpError(f"未知合并算子: {op}")  # pragma: no cover - Enum 已穷举


def _apply_append(field_name: str, current_value: Any, incoming_value: Any) -> Any:
    if isinstance(current_value, list):
        additions = incoming_value if isinstance(incoming_value, list) else [incoming_value]
        merged = list(current_value)
        seen = {json_key(item) for item in merged}
        added = 0
        for item in additions:
            key = json_key(item)
            if key not in seen:
                merged.append(item)
                seen.add(key)
                added += 1
        if not isinstance(incoming_value, list) and added == 0:
            return current_value
        return merged
    if isinstance(current_value, str):
        addition = str(incoming_value)
        if not addition.strip() or addition in current_value:
            return current_value
        return current_value.rstrip() + "\n" + addition
    if current_value is None:
        return incoming_value
    raise MergeOpError(f"字段 {field_name} 类型不支持 append(现值类型 {type(current_value).__name__})")


def _apply_sum(field_name: str, current_value: Any, incoming_value: Any) -> Any:
    try:
        if current_value is None:
            return incoming_value
        if isinstance(current_value, float) or isinstance(incoming_value, float):
            return float(current_value) + float(incoming_value)
        return int(current_value) + int(incoming_value)
    except (TypeError, ValueError):
        return current_value


def _apply_patch(field_name: str, current_value: Any, incoming_value: Any) -> Any:
    if current_value is None:
        # 无原始内容时 patch 退化为整体写入(与 OV PatchOp 的 None 特例同语义)。
        return incoming_value if isinstance(incoming_value, str) else str(incoming_value)
    if not isinstance(current_value, str):
        raise MergeOpError(f"字段 {field_name} 不是字符串,不支持 patch")
    if isinstance(incoming_value, StrPatch):
        return apply_str_patch(current_value, incoming_value)
    text = str(incoming_value)
    if SEARCH_START in text:
        return apply_str_patch(current_value, parse_str_patch(text))
    # 无 SEARCH 块的裸字符串:保守视为全文替换(调用方模板已声明该字段允许)。
    return text


def json_key(item: Any) -> str:
    if isinstance(item, dict):
        return json.dumps(item, ensure_ascii=False, sort_keys=True)
    return json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)


def merge_case_record(base: dict[str, Any], updates: dict[str, Any], schema: dict[str, str]) -> dict[str, Any]:
    """按 schema 的字段级算子合并一条 case 记录,返回新 dict(不改 base)。

    schema: 字段名 -> MergeOp 值字符串。updates 中不存在(或值为 None)的
    字段保留现值;违反纪律(immutable 冲突、patch 失配)抛 MergeOpError。
    """
    merged = dict(base)
    for field_name, incoming in updates.items():
        op_name = schema.get(field_name)
        if op_name is None:
            # schema 未声明的字段遵循保守默认:replace(与记录整体写入同语义)。
            op_name = MergeOp.REPLACE.value
        merged[field_name] = apply_merge_op(MergeOp(op_name), field_name, base.get(field_name), incoming)
    return merged


def similar_enough(current: str, incoming: str, threshold: float = 0.5) -> bool:
    """patch 失配时的辅助判断:incoming 与 current 是否仍是同一主题。"""
    if not current or not incoming:
        return False
    return difflib.SequenceMatcher(None, current, incoming).ratio() >= threshold


__all__ = [
    "MergeOp",
    "MergeOpError",
    "SearchReplaceBlock",
    "StrPatch",
    "SEARCH_START",
    "SEARCH_END",
    "REPLACE_END",
    "parse_str_patch",
    "apply_str_patch",
    "apply_merge_op",
    "merge_case_record",
    "similar_enough",
]
