"""共享工件与任务空间 CLI 命令。"""
from __future__ import annotations

# Typer evaluates command annotations at runtime in Python 3.9 environments.
# ruff: noqa: UP006,UP045
import typing

import typer
from rich import print

from memory_center.application.tasks import execute_task_repair
from memory_center.core.tasks.artifacts import (
    append_change_log,
    append_task_change_log,
    archive_task_space,
    artifact_context,
    artifact_outline,
    auto_archive_task_spaces,
    compact_change_log,
    create_task_space,
    get_artifact,
    get_task_artifact,
    list_artifacts,
    list_task_spaces,
    resolve_task_space,
    task_space_health,
    task_space_repair_plan,
    task_spaces_health,
    touch_task_activity,
    update_artifact,
    update_task_artifact,
    update_task_status,
)


def register_artifact_commands(app: typer.Typer) -> None:
    """向 artifact 子应用注册共享工件和任务空间命令。"""

    @app.command("list")
    def artifact_list_cmd(workspace: str = typer.Option(...)):
        """列出共享工作区工件。"""
        print(list_artifacts(workspace))

    @app.command("get")
    def artifact_get_cmd(workspace: str = typer.Option(...), name: str = typer.Option(...)):
        """读取一个共享工件。"""
        print(get_artifact(workspace, name))

    @app.command("outline")
    def artifact_outline_cmd(workspace: str = typer.Option(...), name: str = typer.Option(...)):
        """只读取一个工件的大纲。"""
        print(artifact_outline(workspace, name))

    @app.command("context")
    def artifact_context_cmd(workspace: str = typer.Option(...), intent: str = typer.Option(...), limit: int = typer.Option(6)):
        """按当前意图检索相关工件片段。"""
        print(artifact_context(workspace, intent, limit=limit))

    @app.command("update")
    def artifact_update_cmd(workspace: str = typer.Option(...), name: str = typer.Option(...), content: str = typer.Option(...)):
        """替换一个共享工件内容。"""
        print(update_artifact(workspace, name, content))

    @app.command("append-change-log")
    def artifact_append_change_log_cmd(workspace: str = typer.Option(...), entry: str = typer.Option(...)):
        """向 change-log.md 追加带时间戳的记录。"""
        print(append_change_log(workspace, entry))

    @app.command("compact-change-log")
    def artifact_compact_change_log_cmd(workspace: str = typer.Option(...), keep_recent: int = typer.Option(30)):
        """归档较早的变更记录，避免共享上下文过大。"""
        print(compact_change_log(workspace, keep_recent=keep_recent))

    @app.command("create-task")
    def artifact_create_task_cmd(
        workspace: str = typer.Option(...),
        title: str = typer.Option(""),
        intent: str = typer.Option(""),
        owner: str = typer.Option(""),
        tag: typing.Optional[typing.List[str]] = typer.Option(None),  # noqa: B008
        priority: str = typer.Option("medium"),
    ):
        """根据标题或意图创建任务专属工件空间。"""
        print(create_task_space(workspace, title=title, intent=intent, owner=owner, tags=tag, priority=priority))

    @app.command("list-tasks")
    def artifact_list_tasks_cmd(workspace: str = typer.Option(...), include_archived: bool = typer.Option(False)):
        """列出活跃或已归档的任务工件空间。"""
        print(list_task_spaces(workspace, include_archived=include_archived))

    @app.command("health-task")
    def artifact_health_task_cmd(workspace: str = typer.Option(...), task_id: str = typer.Option(...)):
        """检查一个任务空间的健康状态和修复建议。"""
        print(task_space_health(workspace, task_id))

    @app.command("health-tasks")
    def artifact_health_tasks_cmd(workspace: str = typer.Option(...), include_archived: bool = typer.Option(False), limit: int = typer.Option(50)):
        """检查工作区内多个任务空间的健康状态。"""
        print(task_spaces_health(workspace, include_archived=include_archived, limit=limit))

    @app.command("repair-plan-task")
    def artifact_repair_plan_task_cmd(workspace: str = typer.Option(...), task_id: str = typer.Option(...)):
        """生成一个任务空间的只读修复计划。"""
        print(task_space_repair_plan(workspace, task_id))

    @app.command("repair-task")
    def artifact_repair_task_cmd(
        workspace: str = typer.Option(...),
        task_id: str = typer.Option(...),
        apply: bool = typer.Option(False, "--apply/--dry-run", help="执行支持的低风险修复，默认仅预览。"),
        intent: str = typer.Option("", help="通过 sync-sniff-artifacts 修复 current_summary 时必填。"),
    ):
        """预览或执行支持的低风险任务空间修复。"""
        print(execute_task_repair(workspace, task_id, apply=apply, intent=intent))

    @app.command("resolve-task")
    def artifact_resolve_task_cmd(
        workspace: str = typer.Option(...),
        intent: str = typer.Option(...),
        title: str = typer.Option(""),
        create_if_missing: bool = typer.Option(True),
        include_archived: bool = typer.Option(False),
        limit_candidates: int = typer.Option(3),
        score_threshold: int = typer.Option(3, help="自动匹配已有任务空间的最低分。"),
    ):
        """从自然语言解析任务空间，必要时创建一个新空间。"""
        print(resolve_task_space(workspace, intent=intent, title=title, create_if_missing=create_if_missing, include_archived=include_archived, limit_candidates=limit_candidates, score_threshold=score_threshold))

    @app.command("get-task")
    def artifact_get_task_cmd(workspace: str = typer.Option(...), task_id: str = typer.Option(...), name: str = typer.Option(...)):
        """读取一个任务空间工件。"""
        print(get_task_artifact(workspace, task_id, name))

    @app.command("update-task")
    def artifact_update_task_cmd(workspace: str = typer.Option(...), task_id: str = typer.Option(...), name: str = typer.Option(...), content: str = typer.Option(...)):
        """替换一个任务空间工件内容。"""
        print(update_task_artifact(workspace, task_id, name, content))

    @app.command("append-task-change-log")
    def artifact_append_task_change_log_cmd(workspace: str = typer.Option(...), task_id: str = typer.Option(...), entry: str = typer.Option(...), keep_recent: int = typer.Option(30)):
        """向任务空间变更日志追加一条记录。"""
        print(append_task_change_log(workspace, task_id, entry, keep_recent=keep_recent))

    @app.command("archive-task")
    def artifact_archive_task_cmd(workspace: str = typer.Option(...), task_id: str = typer.Option(...), reason: str = typer.Option("")):
        """手动归档一个任务工件空间。"""
        print(archive_task_space(workspace, task_id, reason=reason))

    @app.command("update-task-status")
    def artifact_update_task_status_cmd(workspace: str = typer.Option(...), task_id: str = typer.Option(...), status: str = typer.Option(...)):
        """更新任务空间状态：draft/active/blocked/done/archived。"""
        print(update_task_status(workspace, task_id, status))

    @app.command("auto-archive-tasks")
    def artifact_auto_archive_tasks_cmd(workspace: str = typer.Option(...), retention_days: int = typer.Option(30)):
        """按保留天数自动归档不活跃任务空间。"""
        print(auto_archive_task_spaces(workspace, retention_days=retention_days))

    @app.command("touch-task-activity")
    def artifact_touch_task_activity_cmd(workspace: str = typer.Option(...), task_id: str = typer.Option(...), source: str = typer.Option(..., help="调用来源，例如 sync-sniff、sync-case、mcp。")):
        """记录任务空间的最近活动来源。"""
        print(touch_task_activity(workspace, task_id, source))
