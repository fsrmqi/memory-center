"""Session-first 焦点改造回归（docs/FOCUS_TASK_SESSION_FIRST_PROPOSAL.md P0）。

覆盖三道 P0 门禁：
- P0-1: ``sync_task_space=false`` 不得产生任何隐式 L2 绑定；
- P0-2: 焦点只能来自显式 task、可信 session 绑定或 Task Shadow，
  禁止回退 ``active_tasks[0]``；
- P0-3: workbench-summary 等读模型接收 session_id 并输出 additive ``focus``。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from memory_center.application.task_start import start_task
from memory_center.core.orchestrator import resolve_session_focus, workspace_status
from memory_center.core.orchestrator.workspace_ops import (
    workspace_continuity_dashboard,
    workspace_workbench_summary,
)
from memory_center.core.tasks.artifacts import create_task_space
from tests.fixtures import setup_demo_workspace


@pytest.fixture()
def workspace_file(tmp_path: Path) -> str:
    return str(setup_demo_workspace(tmp_path))


def test_start_task_sync_false_never_binds_even_with_direct_anchor(workspace_file: str) -> None:
    """P0-1: sync_task_space=false + title_exact 候选 => shadow_only，无绑定。"""
    create_task_space(workspace_file, title="预警发送-消息推送架构治理", tags=["预警发送"])
    result = start_task(
        workspace_file,
        intent="继续 预警发送-消息推送架构治理 的工作",
        limit=8,
        auto_sync_mode="balanced",
        sync_task_space=False,
        budget="small",
        deadline_ms=3_000,
        request_tier="fast",
    )
    assert result["bound_task_id"] == ""
    binding = result["task_binding"]
    assert binding["mode"] == "shadow_only"
    assert binding["task_id"] == ""
    assert binding["binding_reason_code"] in {"auto_binding_disabled", "ambiguous_candidate", "no_session_context"}
    assert result["sync_sniff"] is None
    # session metadata 不得携带 task 绑定
    session_meta_task_id = result["session"].get("task_id")
    assert not session_meta_task_id
    # Shadow 不得被绑定到 L2
    shadow = result["task_shadow"]
    assert shadow.get("binding_status") != "bound"


def test_start_task_sync_true_with_direct_anchor_binds(workspace_file: str) -> None:
    """P0-1: sync_task_space=true + title_exact 仍允许 auto_direct_anchor。"""
    create_task_space(workspace_file, title="预警发送-消息推送架构治理", tags=["预警发送"])
    result = start_task(
        workspace_file,
        intent="继续 预警发送-消息推送架构治理 的工作",
        limit=8,
        auto_sync_mode="balanced",
        sync_task_space=True,
        budget="small",
        deadline_ms=3_000,
        request_tier="fast",
    )
    binding = result["task_binding"]
    if binding["mode"] == "auto_direct_anchor":
        assert result["bound_task_id"]
        assert binding["binding_reason_code"] == "explicit_task_id"
        assert result["task_shadow"]["binding_status"] == "bound"
    else:
        # title_exact 未命中时必须落在 shadow_only，不得走第三条路
        assert binding["mode"] == "shadow_only"
        assert result["bound_task_id"] == ""


def test_workbench_summary_without_session_has_no_focus(workspace_file: str) -> None:
    """P0-2: 未传 session_id 的 workbench summary 不得从活跃任务补焦点。"""
    create_task_space(workspace_file, title="legacy alpha")
    create_task_space(workspace_file, title="legacy beta")
    summary = workspace_workbench_summary(workspace_file, limit=5)
    assert summary["focus"]["kind"] == "none"
    assert summary["focus"]["task_id"] == ""
    assert summary["focus_task"] is None
    # 旧任务只出现在可恢复列表
    assert len(summary["resumable_tasks"]) == 2


def test_workbench_summary_with_explicit_task_uses_it(workspace_file: str) -> None:
    """P0-2: 显式 task_id 优先，且即使它不是最近更新任务。"""
    first = create_task_space(workspace_file, title="task-one")["task_id"]
    second = create_task_space(workspace_file, title="task-two")["task_id"]
    summary = workspace_workbench_summary(workspace_file, limit=5, task_id=first)
    assert summary["focus"]["kind"] == "task"
    assert summary["focus"]["task_id"] == first
    assert summary["focus"]["binding_mode"] == "explicit"
    assert (summary["focus_task"] or {}).get("task_id") == first
    assert second


def test_workbench_summary_bound_session_returns_bound_task(workspace_file: str) -> None:
    """P0-2: 已绑定 session 只返回绑定的 L2，即使另一任务更新更晚。"""
    bound = create_task_space(workspace_file, title="session-bound-task")["task_id"]
    other = create_task_space(workspace_file, title="newer-task")
    from memory_center.core.orchestrator import workspace_start_session

    session = workspace_start_session(
        workspace_file,
        intent="处理会话绑定任务",
        metadata={
            "task_id": bound,
            "task_binding": {"mode": "explicit", "task_id": bound, "reason": "user"},
        },
    )
    summary = workspace_workbench_summary(
        workspace_file, limit=5, session_id=str(session["session_id"])
    )
    assert summary["focus"]["kind"] == "task"
    assert summary["focus"]["task_id"] == bound
    assert (summary["focus_task"] or {}).get("task_id") == bound
    assert other["task_id"] != bound


def test_workbench_summary_unbound_session_returns_shadow_none_task(workspace_file: str) -> None:
    """P0-2: 未绑定 session 返回 Shadow 焦点，next_actions 不借用任何 L2。"""
    create_task_space(workspace_file, title="gamma legacy")
    from memory_center.core.orchestrator import workspace_start_session
    from memory_center.core.tasks.shadow import ensure_shadow_for_session

    session = workspace_start_session(workspace_file, intent="只读排查")
    shadow = ensure_shadow_for_session(workspace_file, str(session["session_id"]), intent="只读排查")
    summary = workspace_workbench_summary(
        workspace_file, limit=5, session_id=str(session["session_id"])
    )
    assert summary["focus"]["kind"] == "shadow"
    assert summary["focus"]["shadow_id"] == shadow["shadow_id"]
    assert summary["focus"]["binding_mode"] == "shadow_only"
    assert summary["focus_task"] is None
    assert summary["next_actions"] == []


def test_continuity_dashboard_without_anchor_returns_no_focus(workspace_file: str) -> None:
    """P0-2: 未传 session/task 的 continuity dashboard 不得补全局焦点。"""
    create_task_space(workspace_file, title="delta legacy")
    dashboard = workspace_continuity_dashboard(workspace_file)
    assert dashboard["focus"]["kind"] == "none"
    assert dashboard["focus_task"] is None


def test_workspace_status_keeps_workspace_level_semantics(workspace_file: str) -> None:
    """workspace_status 的 current_focus_task 降级为 resumable_head 语义。"""
    create_task_space(workspace_file, title="head-task")
    status = workspace_status(workspace_file, view="compact", budget="small")
    assert status.get("current_focus_task_semantics") == "resumable_head"
    assert status["focus"]["kind"] == "none"
    assert status["continuity_overview"]["focus_task_id"] == ""
    assert status["continuity_overview"]["resumable_head_task_id"]


def test_resolve_session_focus_never_falls_back_to_active_tasks(workspace_file: str) -> None:
    """P0-2 核心不变量：active_tasks 非空也不能成为焦点。"""
    first = create_task_space(workspace_file, title="candidate-one")["task_id"]
    focus = resolve_session_focus(
        workspace_file,
        task_id="",
        session_id="",
        active_tasks=[{"task_id": first, "title": "候选一"}],
    )
    assert focus["kind"] == "none"
    assert focus["task_id"] == ""
    assert focus["binding_reason_code"] == "no_session_context"


def test_resolve_session_shadow_supports_dsh_source_kind(workspace_file: str) -> None:
    """DSH bridge 透传的 session 经 source kind=dsh 解析到同一 Shadow。"""
    from memory_center.core.tasks.shadow import ensure_shadow_for_session, register_shadow_source
    from memory_center.core.storage.workspace import WorkspaceStore
    from memory_center.core.workspace.config import load_workspace_config

    _, store = load_workspace_config(workspace_file), WorkspaceStore(workspace_file)
    register_shadow_source(store, "dsh", "dsh-session-1", "shadow:dsh-task-shadow@dsh-session-1")
    from memory_center.core.orchestrator.workspace_ops import _resolve_session_shadow

    assert _resolve_session_shadow(workspace_file, "dsh-session-1") == "shadow:dsh-task-shadow@dsh-session-1"
    assert _resolve_session_shadow(workspace_file, "unknown-session") == ""


def test_delivery_capture_without_anchor_rejected_then_shadow_bound_used(workspace_file: str) -> None:
    """P0-3：delivery capture 无锚点拒绝；Shadow 已显式绑定时复用其 task。"""
    from memory_center.core.orchestrator import workspace_capture_dsh_delivery_summary
    from memory_center.core.storage.workspace import WorkspaceStore
    from memory_center.core.tasks.artifacts import get_task_artifact
    from memory_center.core.tasks.shadow import bind_shadow_to_task, ensure_shadow_for_session
    from memory_center.core.workspace.config import load_workspace_config

    task_id = create_task_space(workspace_file, title="delivery anchored task")["task_id"]
    # 1) 无任何绑定时拒绝写入
    result = workspace_capture_dsh_delivery_summary(
        workspace_file, "session-x", "交付摘要：完成 A。", turn=1, step=2
    )
    assert result["captured"] is False and result["reason"] == "task_id_required"
    # 2) Shadow 显式绑定后，同 source 的 capture 复用绑定的 task
    _, store = load_workspace_config(workspace_file), WorkspaceStore(workspace_file)
    shadow = ensure_shadow_for_session(workspace_file, "session-x", intent="交付")
    bind_shadow_to_task(workspace_file, shadow["shadow_id"], task_id, source="explicit")
    result2 = workspace_capture_dsh_delivery_summary(
        workspace_file, "session-x", "交付摘要：完成 A。", turn=1, step=2
    )
    assert result2["captured"] is True and result2["task_id"] == task_id
    assert result2["session_id"] == "dsh-delivery:session-x:1:2"


def test_knowledge_summary_requires_explicit_anchor(workspace_file: str) -> None:
    """P0-2 侧链路：知识页不再从 current_focus_task 借锚点。"""
    create_task_space(workspace_file, title="historical knowledge task")
    from memory_center.core.knowledge.projection import workspace_knowledge_summary

    # 无 task_id：空状态，不检索历史任务关键词
    unbound = workspace_knowledge_summary(workspace_file, scope="kaipuyun")
    assert unbound["anchor_state"] == "unbound"
    assert unbound["related_wiki"] == []
    assert unbound["focus"]["kind"] == "none"
    # 显式 task_id：按该任务检索
    tid = create_task_space(workspace_file, title="anchor knowledge task")["task_id"]
    bound = workspace_knowledge_summary(workspace_file, scope="kaipuyun", task_id=tid)
    assert bound["anchor_state"] == "bound"
    assert bound["focus"]["task_id"] == tid


def test_resume_packet_never_falls_back_to_workspace_head(workspace_file: str) -> None:
    """P0-2 侧链路：恢复包只认显式 task_id 或 session 可信绑定。"""
    create_task_space(workspace_file, title="head resumable task")
    from memory_center.core.orchestrator import workspace_resume_packet, workspace_start_session

    # 无 session/task：不锚定任何任务
    empty = workspace_resume_packet(workspace_file, limit=5)
    assert not empty.get("task_id")
    # session 可信绑定：解析到绑定任务而非排序首位
    tid = create_task_space(workspace_file, title="bound resume task")["task_id"]
    sess = workspace_start_session(
        workspace_file,
        intent="explicit",
        metadata={"task_id": tid, "task_binding": {"mode": "explicit", "task_id": tid}},
    )
    bound = workspace_resume_packet(workspace_file, session_id=str(sess["session_id"]), limit=5)
    assert bound.get("task_id") == tid


def test_delivery_overview_without_task_returns_unbound(workspace_file: str) -> None:
    """task-delivery-overview 无显式 task 时返回空投影而非借用焦点。"""
    from memory_center.core.orchestrator import workspace_task_delivery_overview

    create_task_space(workspace_file, title="epsilon legacy")
    overview = workspace_task_delivery_overview(workspace_file)
    assert overview["stage"] == "unbound"
    assert overview["task_id"] == ""
    assert overview["timeline"] == []
    assert overview["resumable_tasks"]
