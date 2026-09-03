"""P1-B regression: task-space resolution conservative write gate.

来自真实会话复盘（docs/LOOKUP_ARCHITECTURE_HANDOFF_PLAN.md §5 P1-B）：
旧逻辑只把"完全同分"当歧义，低分且相近的候选会被自动选中，让
``mc_start`` / ``mc_close`` 写入错误 task space，污染 context.md、
design.md、current-summary.md 等追加保护工件。

门禁语义：
- 匹配来源分类（tag_exact / title_exact / intent_exact / signature_overlap /
  fuzzy_token）；top1 缺强证据、margin 不足、低于高置信阈值时不得自动写入；
- ``resolution_confidence`` + ``auto_write_allowed`` 必须出现在 resolve 结果；
- ``workspace_sync_*_to_artifacts`` 在 ``auto_write_allowed=false`` 时停止写入；
- 同 session start/close 默认复用同一 task。
"""
from __future__ import annotations

from pathlib import Path

from memory_center.core.tasks.artifacts import (
    create_task_space,
    resolve_task_space,
)


def _workspace(tmp_path: Path) -> Path:
    from tests.fixtures import copy_demo_workspace

    return copy_demo_workspace(tmp_path)


def test_tag_exact_beats_unrelated_token_score(tmp_path: Path):
    """tag 强匹配任务必须压过无关 token 高分任务。"""
    workspace = _workspace(tmp_path)
    tagged = create_task_space(workspace, title="订单服务重构", tags=["订单", "重构"])
    create_task_space(workspace, title="订单 网关 迁移 缓存 配置 优化 清理", tags=[])

    resolved = resolve_task_space(
        workspace,
        intent="重构订单服务",
        score_threshold=1,
    )
    assert resolved["resolved"] is True
    assert resolved["task_id"] == tagged["task_id"]


def test_low_score_fuzzy_top1_without_strong_evidence_is_not_auto_written(tmp_path: Path):
    """top1 只有 fuzzy token 命中（无 tag/title/intent 强证据）：不自动写入。"""
    workspace = _workspace(tmp_path)
    # 意图词拆出的 token 与两个任务都只是"出现"，不构成任何 title/tag 精确命中
    # （标题词与意图词无连续子串重叠，仅靠 artifact 正文与通用词得分）。
    create_task_space(workspace, title="数据归档专项", tags=[])
    create_task_space(workspace, title="报表性能巡检", tags=[])

    resolved = resolve_task_space(
        workspace,
        intent="归档 巡检 报表 数据 历史 清理",  # 各 token 分散命中两个任务
        create_if_missing=False,
        score_threshold=1,
    )
    assert resolved.get("auto_write_allowed") is not True
    assert resolved.get("resolution_confidence") in ("low", "medium")


def test_high_score_with_tag_title_exact_hit_allows_write(tmp_path: Path):
    """top1 高分、tag/title 精确命中：允许写入，resolution_confidence=high。"""
    workspace = _workspace(tmp_path)
    task = create_task_space(workspace, title="链路分析任务", tags=["链路分析"])

    resolved = resolve_task_space(
        workspace,
        intent="链路分析任务",
        score_threshold=1,
    )
    assert resolved["resolved"] is True
    assert resolved["task_id"] == task["task_id"]
    assert resolved.get("resolution_confidence") == "high"
    assert resolved.get("auto_write_allowed") is True


def test_close_tie_with_strong_overlap_is_ambiguous(tmp_path: Path):
    """完全同分依旧歧义（旧行为保持）。"""
    workspace = _workspace(tmp_path)
    create_task_space(workspace, title="会员积分迁移", tags=["会员"])
    create_task_space(workspace, title="会员积分迁移方案B", tags=["会员"])

    resolved = resolve_task_space(
        workspace,
        intent="会员积分迁移",
        create_if_missing=False,
        score_threshold=1,
    )
    assert resolved.get("resolution_status") == "ambiguous"
    assert resolved.get("auto_write_allowed") is False


def test_numeric_or_pinyin_fragment_contribution_is_capped(tmp_path: Path):
    """纯数字/拼音碎片提供边际分但拿不到强证据。"""
    workspace = _workspace(tmp_path)
    create_task_space(workspace, title="v2 优化", tags=[])

    resolved = resolve_task_space(
        workspace,
        intent="v2",
        create_if_missing=False,
        score_threshold=1,
    )
    # 一个 2 字符碎片不足以自动写入。
    assert resolved.get("auto_write_allowed") is False
