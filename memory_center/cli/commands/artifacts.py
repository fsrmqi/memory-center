"""共享工件与任务空间 CLI 命令。"""
from __future__ import annotations

# Typer evaluates command annotations at runtime in Python 3.9 environments.
# ruff: noqa: UP006,UP045
import json
import typing

import typer
from rich import print

from memory_center.application.tasks import execute_task_repair
from memory_center.core.indexing.control_plane import index_control_status
from memory_center.core.indexing.shards import cleanup_generations
from memory_center.core.knowledge.assets import (
    approve_collaboration_asset,
    bind_collaboration_asset,
    collaboration_asset_loadout,
    collaboration_asset_status,
    ingest_wiki_document_asset,
    register_collaboration_asset,
    submit_asset_for_sharing,
    sync_workspace_collaboration_assets,
)
from memory_center.core.storage.maintenance import (
    cleanup_legacy_memory_store,
    compact_semantic_runtime_state,
    sparsify_static_assertions,
    vacuum_runtime_store,
)
from memory_center.core.storage.workspace import WorkspaceStore
from memory_center.core.tasks.artifacts import (
    append_change_log,
    append_task_change_log,
    archive_task_space,
    artifact_context,
    artifact_outline,
    auto_archive_task_spaces,
    compact_change_log,
    compact_task_artifacts,
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
from memory_center.core.tasks.delivery import (
    delivery_matrix,
    delivery_policy_status,
    delivery_skill_candidate,
    delivery_skill_replay_set,
    delivery_skill_status,
    delivery_workflow_status,
    derive_delivery_failure_candidates,
    execute_delivery_validation,
    initialize_delivery_workflow,
    propose_delivery_breakdown,
    publish_delivery_skill,
    recommend_delivery_skills,
    record_delivery_skill_observation,
    record_delivery_validation,
    rollback_delivery_skill,
    start_delivery_skill_canary,
    synthesize_delivery_skill_trajectories,
    transition_delivery_stage,
    update_delivery_contract,
    update_delivery_policy,
    update_delivery_skill_contract,
    update_delivery_subtask_status,
)
from memory_center.core.tasks.skill_up import initialize_skill_up_eval, run_skill_up_eval, skill_up_status


def register_artifact_commands(app: typer.Typer) -> None:
    """向 artifact 子应用注册共享工件和任务空间命令。"""

    @app.command("list")
    def artifact_list_cmd(workspace: str = typer.Option(...)):
        """列出共享工作区工件。"""
        print(list_artifacts(workspace))

    @app.command("asset-status")
    def artifact_asset_status_cmd(workspace: str = typer.Option(...), limit: int = typer.Option(100)):
        """查看任务、Skill、Wiki、CodeGraph 协作资产及审批状态。"""
        print(collaboration_asset_status(workspace, limit=limit))

    @app.command("asset-sync")
    def artifact_asset_sync_cmd(workspace: str = typer.Option(...), owner: str = typer.Option("")):
        """将当前任务、已发布 Skill 和活跃代码图谱登记为协作资产。"""
        print(sync_workspace_collaboration_assets(workspace, owner=owner))

    @app.command("asset-register")
    def artifact_asset_register_cmd(workspace: str = typer.Option(...), payload: str = typer.Option(..., help="JSON asset payload"), actor: str = typer.Option(..., help="Must match payload owner")):
        """显式登记一个本地协作资产。"""
        print(register_collaboration_asset(workspace, **{**json.loads(payload), "actor": actor}))

    @app.command("asset-share")
    def artifact_asset_share_cmd(workspace: str = typer.Option(...), asset_id: str = typer.Option(...), visibility: str = typer.Option("team"), actor: str = typer.Option(...), agents: str = typer.Option("[]"), roles: str = typer.Option("[]")):
        """提交资产共享申请；共享资产不会自动进入 Agent 上下文。"""
        print(submit_asset_for_sharing(workspace, asset_id, visibility=visibility, actor=actor, allowed_agents=json.loads(agents), allowed_roles=json.loads(roles)))

    @app.command("asset-approve")
    def artifact_asset_approve_cmd(workspace: str = typer.Option(...), asset_id: str = typer.Option(...), approved: bool = typer.Option(...), actor: str = typer.Option(...), note: str = typer.Option("")):
        """审批或拒绝已提交的团队协作资产。"""
        print(approve_collaboration_asset(workspace, asset_id, approved=approved, actor=actor, note=note))

    @app.command("asset-bind")
    def artifact_asset_bind_cmd(workspace: str = typer.Option(...), asset_id: str = typer.Option(...), actor: str = typer.Option(...), agents: str = typer.Option("[]"), roles: str = typer.Option("[]")):
        """将已激活资产绑定到指定 Agent 或角色。"""
        print(bind_collaboration_asset(workspace, asset_id, actor=actor, agents=json.loads(agents), roles=json.loads(roles)))

    @app.command("asset-loadout")
    def artifact_asset_loadout_cmd(workspace: str = typer.Option(...), agent_id: str = typer.Option(""), role: str = typer.Option(""), limit: int = typer.Option(12)):
        """查看指定 Agent 或角色会装载的有界资产。"""
        print(collaboration_asset_loadout(workspace, agent_id=agent_id, role=role, limit=limit))

    @app.command("wiki-document-ingest")
    def artifact_wiki_document_ingest_cmd(workspace: str = typer.Option(...), document_path: str = typer.Option(...), owner: str = typer.Option(...), visibility: str = typer.Option("private"), tags: str = typer.Option("[]")):
        """登记工作区内文档的 Wiki 节点、链接与代码证据。"""
        print(ingest_wiki_document_asset(workspace, document_path, owner=owner, visibility=visibility, tags=json.loads(tags)))

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

    @app.command("delivery-init")
    def artifact_delivery_init_cmd(workspace: str = typer.Option(...), task_id: str = typer.Option(...), actor: str = typer.Option("")):
        """初始化需求交付状态机及其结构化工件。"""
        print(initialize_delivery_workflow(workspace, task_id, actor=actor))

    @app.command("delivery-status")
    def artifact_delivery_status_cmd(workspace: str = typer.Option(...), task_id: str = typer.Option(...)):
        """读取需求交付阶段、门禁和下一步动作。"""
        print(delivery_workflow_status(workspace, task_id))

    @app.command("delivery-contract")
    def artifact_delivery_contract_cmd(workspace: str = typer.Option(...), task_id: str = typer.Option(...), kind: str = typer.Option(..., help="requirements|subtasks|acceptance"), items: str = typer.Option(..., help="JSON 数组"), actor: str = typer.Option("")):
        """写入需求、子任务或验收标准契约。"""
        parsed = json.loads(items)
        if not isinstance(parsed, list):
            raise typer.BadParameter("items 必须是 JSON 数组")
        print(update_delivery_contract(workspace, task_id, kind=kind, items=parsed, actor=actor))

    @app.command("delivery-subtask-status")
    def artifact_delivery_subtask_status_cmd(workspace: str = typer.Option(...), task_id: str = typer.Option(...), subtask_id: str = typer.Option(...), status: str = typer.Option(...), actor: str = typer.Option("")):
        """更新一个子任务的定位或实现状态。"""
        print(update_delivery_subtask_status(workspace, task_id, subtask_id, status, actor=actor))

    @app.command("delivery-record-validation")
    def artifact_delivery_validation_cmd(workspace: str = typer.Option(...), task_id: str = typer.Option(...), status: str = typer.Option(...), summary: str = typer.Option(""), command: str = typer.Option(""), exit_code: typing.Optional[int] = typer.Option(None), acceptance_ids: str = typer.Option("[]", help="JSON 数组"), evidence_refs: str = typer.Option("[]", help="JSON 数组"), actor: str = typer.Option("")):
        """记录已执行的验证结果，不会执行传入命令。"""
        print(record_delivery_validation(workspace, task_id, status=status, summary=summary, command=command, exit_code=exit_code, acceptance_ids=json.loads(acceptance_ids), evidence_refs=json.loads(evidence_refs), actor=actor))

    @app.command("delivery-breakdown")
    def artifact_delivery_breakdown_cmd(workspace: str = typer.Option(...), task_id: str = typer.Option(...), source_refs: str = typer.Option("[]", help="JSON 数组"), summary: str = typer.Option("")):
        """生成不写入的需求拆解候选，确认后再更新 requirements。"""
        print(propose_delivery_breakdown(workspace, task_id, source_refs=json.loads(source_refs), summary=summary))

    @app.command("delivery-policy")
    def artifact_delivery_policy_cmd(workspace: str = typer.Option(...), policy: str = typer.Option("", help="JSON 对象；为空时仅查询"), actor: str = typer.Option("")):
        """查看或更新受限验证 profile 策略。"""
        print(update_delivery_policy(workspace, json.loads(policy), actor=actor) if policy else delivery_policy_status(workspace))

    @app.command("delivery-execute-validation")
    def artifact_delivery_execute_validation_cmd(workspace: str = typer.Option(...), task_id: str = typer.Option(...), profile_id: str = typer.Option(...), acceptance_ids: str = typer.Option("[]", help="JSON 数组"), actor: str = typer.Option("")):
        """执行工作区预注册验证 profile，不接受任意 shell 命令。"""
        print(execute_delivery_validation(workspace, task_id, profile_id=profile_id, acceptance_ids=json.loads(acceptance_ids), actor=actor))

    @app.command("delivery-matrix")
    def artifact_delivery_matrix_cmd(workspace: str = typer.Option(...), task_id: str = typer.Option(...), write: bool = typer.Option(True, "--write/--dry-run")):
        """生成需求到代码、验收与验证证据的派生矩阵和 TECH_SPEC。"""
        print(delivery_matrix(workspace, task_id, write=write))

    @app.command("delivery-transition")
    def artifact_delivery_transition_cmd(workspace: str = typer.Option(...), task_id: str = typer.Option(...), stage: str = typer.Option(...), actor: str = typer.Option(""), force: bool = typer.Option(False, help="仅用于已知例外；会保留强制推进历史。")):
        """按门禁将需求交付流程推进到下一阶段。"""
        print(transition_delivery_stage(workspace, task_id, stage, actor=actor, force=force))

    @app.command("delivery-skill-candidate")
    def artifact_delivery_skill_candidate_cmd(workspace: str = typer.Option(...), task_id: str = typer.Option(...)):
        """从已验证的关闭任务生成待审核交付 Skill 候选。"""
        print(delivery_skill_candidate(workspace, task_id))

    @app.command("delivery-skill-publish")
    def artifact_delivery_skill_publish_cmd(workspace: str = typer.Option(...), task_id: str = typer.Option(...)):
        """发布已通过灰度证据门槛的交付 Skill。"""
        print(publish_delivery_skill(workspace, task_id))

    @app.command("delivery-skill-status")
    def artifact_delivery_skill_status_cmd(workspace: str = typer.Option(...), task_id: str = typer.Option(...)):
        """查看一个任务的交付 Skill 候选和发布状态。"""
        print(delivery_skill_status(workspace, task_id))

    @app.command("delivery-skill-contract-update")
    def artifact_delivery_skill_contract_update_cmd(workspace: str = typer.Option(...), task_id: str = typer.Option(...), contract: str = typer.Option(..., help="JSON object: languages, preconditions, stop_conditions, input_contract, output_contract, replay_policy"), actor: str = typer.Option("")):
        """为已生成候选声明适用范围、停止条件和输入输出契约。"""
        try:
            payload = json.loads(contract)
        except json.JSONDecodeError as exc:
            raise typer.BadParameter("contract must be a JSON object") from exc
        if not isinstance(payload, dict):
            raise typer.BadParameter("contract must be a JSON object")
        print(update_delivery_skill_contract(workspace, task_id, contract=payload, actor=actor))

    @app.command("delivery-skill-replay")
    def artifact_delivery_skill_replay_cmd(workspace: str = typer.Option(...), skill_id: str = typer.Option(...), limit: int = typer.Option(100)):
        """读取一个 Skill 的脱敏 replay 集，不包含源码、需求或日志正文。"""
        print(delivery_skill_replay_set(workspace, skill_id=skill_id, limit=limit))

    @app.command("delivery-skill-canary")
    def artifact_delivery_skill_canary_cmd(workspace: str = typer.Option(...), task_id: str = typer.Option(...), actor: str = typer.Option("")):
        """显式将合格候选放入隔离灰度，不进入默认检索。"""
        print(start_delivery_skill_canary(workspace, task_id, actor=actor))

    @app.command("delivery-skill-observe")
    def artifact_delivery_skill_observe_cmd(workspace: str = typer.Option(...), skill_id: str = typer.Option(...), outcome: str = typer.Option(..., help="passed|failed|bypassed|unobservable"), evidence_refs: str = typer.Option("[]", help="JSON 数组；passed 必填"), latency_ms: typing.Optional[int] = typer.Option(None), token_count: typing.Optional[int] = typer.Option(None), actor: str = typer.Option("")):
        """记录脱敏、可引用的真实 Skill 使用结果，不接受模型自评。"""
        print(record_delivery_skill_observation(workspace, skill_id, outcome=outcome, evidence_refs=json.loads(evidence_refs), latency_ms=latency_ms, token_count=token_count, actor=actor))

    @app.command("delivery-skill-evaluate")
    def artifact_delivery_skill_evaluate_cmd(workspace: str = typer.Option(...), skill_id: str = typer.Option("")):
        """只读汇总 Skill 成功、失败、绕过、耗时与 Token 指标。"""
        from memory_center.core.tasks.delivery import evaluate_delivery_skill
        print(evaluate_delivery_skill(workspace, skill_id=skill_id))

    @app.command("delivery-skill-rollback")
    def artifact_delivery_skill_rollback_cmd(workspace: str = typer.Option(...), skill_id: str = typer.Option(...), reason: str = typer.Option(...), actor: str = typer.Option("")):
        """从默认推荐中回滚有问题的 canary 或正式 Skill，保留历史证据。"""
        print(rollback_delivery_skill(workspace, skill_id, reason=reason, actor=actor))

    @app.command("delivery-skill-recommend")
    def artifact_delivery_skill_recommend_cmd(workspace: str = typer.Option(...), intent: str = typer.Option(...), language: str = typer.Option(""), limit: int = typer.Option(5)):
        """按意图检索已发布的结构化交付 Skill。"""
        print(recommend_delivery_skills(workspace, intent, language=language, limit=limit))

    @app.command("delivery-failure-candidates")
    def artifact_delivery_failure_candidates_cmd(workspace: str = typer.Option(...), limit_tasks: int = typer.Option(200)):
        """离线聚类已验证失败，仅生成待审核反模式候选。"""
        print(derive_delivery_failure_candidates(workspace, limit_tasks=limit_tasks))

    @app.command("delivery-skill-synthesize")
    def artifact_delivery_skill_synthesize_cmd(workspace: str = typer.Option(...), min_support: int = typer.Option(3)):
        """离线归纳多个已验证交付的共同结构，不影响查询热路径。"""
        print(synthesize_delivery_skill_trajectories(workspace, min_support=min_support))

    @app.command("delivery-skill-eval-status")
    def artifact_delivery_skill_eval_status_cmd():
        """检查可选 skill-up 外部评测器是否可用。"""
        print(skill_up_status())

    @app.command("delivery-skill-eval-init")
    def artifact_delivery_skill_eval_init_cmd(workspace: str = typer.Option(...), skill_id: str = typer.Option(...), engine: str = typer.Option("codex")):
        """为已发布交付 Skill 生成脱敏 skill-up 评测骨架。"""
        print(initialize_skill_up_eval(workspace, skill_id=skill_id, engine=engine))

    @app.command("delivery-skill-eval-run")
    def artifact_delivery_skill_eval_run_cmd(workspace: str = typer.Option(...), skill_id: str = typer.Option(...), apply: bool = typer.Option(False, "--apply/--dry-run")):
        """显式运行固定 skill-up validate/run，不接受任意 shell 参数。"""
        print(run_skill_up_eval(workspace, skill_id=skill_id, apply=apply))

    @app.command("compact-task")
    def artifact_compact_task_cmd(workspace: str = typer.Option(...), task_id: str = typer.Option(...), threshold_mb: int = typer.Option(2), keep_kb: int = typer.Option(64)):
        """压缩归档超大任务工件，保留有界恢复摘要。"""
        print(compact_task_artifacts(workspace, task_id, threshold_bytes=max(1, threshold_mb) * 1024 * 1024, keep_bytes=max(1, keep_kb) * 1024))

    @app.command("generation-gc")
    def artifact_generation_gc_cmd(workspace: str = typer.Option(...), keep: int = typer.Option(2, min=2), apply: bool = typer.Option(False, "--apply/--dry-run", help="默认只预览；--apply 删除可回收的旧索引代际。")):
        """清理旧索引代际，始终保留当前和上一代。"""
        store = WorkspaceStore(workspace)
        control = index_control_status(store)
        print(cleanup_generations(store, active_generation=str(control.get("active_generation", "") or ""), previous_generation=str(control.get("previous_generation", "") or ""), keep=max(2, keep), apply=apply))

    @app.command("index-export-cleanup")
    def artifact_index_export_cleanup_cmd(workspace: str = typer.Option(...), apply: bool = typer.Option(False, "--apply/--dry-run", help="默认只预览；--apply 删除 SQLite 已覆盖的大型 JSON 索引导出。")):
        """清理 SQLite 运行时索引的重复 JSON 导出。"""
        print(WorkspaceStore(workspace).cleanup_runtime_only_index_exports(apply=apply))

    @app.command("storage-legacy-cleanup")
    def artifact_storage_legacy_cleanup_cmd(workspace: str = typer.Option(...), apply: bool = typer.Option(False, "--apply/--dry-run", help="默认只预览；--apply 删除未被当前运行时使用的旧 memory.db。")):
        """清理旧存储架构遗留的 memory/memory.db 副本。"""
        print(cleanup_legacy_memory_store(workspace, apply=apply))

    @app.command("assertion-sparsify")
    def artifact_assertion_sparsify_cmd(workspace: str = typer.Option(...), apply: bool = typer.Option(False, "--apply/--dry-run", help="默认只预览；--apply 删除可从图边派生的 EXTRACTED 断言副本。")):
        """迁移到图边派生静态断言，保留人工状态覆盖。"""
        print(sparsify_static_assertions(workspace, apply=apply))

    @app.command("assertion-vacuum")
    def artifact_assertion_vacuum_cmd(workspace: str = typer.Option(...), apply: bool = typer.Option(False, "--apply/--dry-run", help="默认只预览；--apply 独占重整 graph.db 并回收已删除页。")):
        """在断言稀疏化后显式回收 SQLite 页。"""
        print(vacuum_runtime_store(workspace, apply=apply))

    @app.command("semantic-index-compact")
    def artifact_semantic_index_compact_cmd(workspace: str = typer.Option(...), apply: bool = typer.Option(False, "--apply/--dry-run", help="默认只预览；--apply 删除被倒排和向量索引覆盖的旧语义文档镜像。")):
        """将旧语义全量镜像压缩为运行时索引元数据，不触发 reindex。"""
        print(compact_semantic_runtime_state(workspace, apply=apply))

    @app.command("storage-vacuum")
    def artifact_storage_vacuum_cmd(workspace: str = typer.Option(...), apply: bool = typer.Option(False, "--apply/--dry-run", help="默认只预览；--apply 独占重整 graph.db 并回收已删除页。")):
        """在任何大型存储清理后显式回收 SQLite 页。"""
        print(vacuum_runtime_store(workspace, apply=apply))
