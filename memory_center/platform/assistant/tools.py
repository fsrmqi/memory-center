"""Personal Assistant Wiki MCP 服务器。

把个人助手的长期知识、记忆写入和维护能力收敛为三个任务级入口：

  assistant_knowledge — search/read/brief/analyze/initialize：检索、读取、简报与索引分析
  assistant_memory    — log/archive：追加确认结论或显式归档资料
  assistant_admin     — validate/scan/index：校验知识库、扫描垃圾或维护原始索引

默认 ``assistant`` profile 同时开放知识与记忆；维护能力单独隔离。用户档案只是服务对象
上下文，不是 Agent 人格定义；工具可用也不代表已获得对外行动授权。
"""
from __future__ import annotations

from pathlib import Path

from memory_center.platform.assistant import core, skill_catalog

PROFILE_TOOLS = {
    "assistant": frozenset({"assistant_knowledge", "assistant_memory", "assistant_skill"}),
    "read-only": frozenset({"assistant_knowledge"}),
    "maintenance": frozenset({"assistant_admin"}),
}
PROFILE_TOOLS["full"] = frozenset().union(*PROFILE_TOOLS.values())


def create_server(
    knowledge_root: str,
    allowed_source_roots: tuple[str, ...] = (),
    profile: str = "assistant",
    candidate_skill_root: str = "~/.agents/skill-candidates",
    published_skill_root: str = "~/.agents/skills",
):
    try:
        from mcp.server.fastmcp import FastMCP
        from mcp.server.fastmcp.server import Settings
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("请先安装依赖：pip install -e .[mcp]") from exc

    # mcp 1.29 + pydantic-settings 2.15 需要在 FastMCP 定义完成后重建泛型 Settings，
    # 否则每次启动都会产生 lifespan forward-reference 警告。
    Settings.model_rebuild()

    root = Path(knowledge_root).expanduser()
    if not root.is_dir():
        raise RuntimeError(f"个人助手知识库不存在：{root}")
    if profile not in PROFILE_TOOLS:
        choices = ", ".join(PROFILE_TOOLS)
        raise RuntimeError(f"未知 profile：{profile}；可选值：{choices}")
    allowed_roots = tuple(Path(p).expanduser() for p in allowed_source_roots)
    candidates = Path(candidate_skill_root).expanduser()
    published_dir = Path(published_skill_root).expanduser()
    enabled_tools = PROFILE_TOOLS[profile]
    watcher = {"mode": "query_incremental", "managed_by": "Memory Center"}
    mcp = FastMCP(f"Personal Assistant Wiki ({profile})")

    if "assistant_knowledge" in enabled_tools:

        @mcp.tool()
        def assistant_knowledge(
            action: str,
            query: str = "",
            path: str = "",
            scope: str = "",
            limit: int = 10,
            start_line: int = 1,
            max_chars: int = 12000,
            force: bool = False,
        ) -> dict:
            """查询、读取、组装任务简报，或一键初始化索引并分析 Wiki 结构。

            源码调用链和代码影响分析仍应使用 Memory Center；这里的 analyze 是知识库结构、索引、
            治理状态和外部入口分析。用户档案是服务对象上下文，不是 Agent 人格定义。

            Args:
                action: search、read、brief、analyze、initialize 或 status
                query: search 的关键词或 brief 的任务描述；brief 的 query 建议来自
                    Memory Center 当前绑定任务的标题或 Shadow intent，不要使用
                    工作区任务排序候选（Session-first 约定）
                path: read 时的知识库相对路径
                scope: search 的可选公司范围
                limit: search 每类最多返回条数
                start_line: read 起始行，从 1 开始
                max_chars: read 本次最多返回字符数
                force: initialize 时是否强制重新抽取全部文档
            """
            if action == "search":
                if not query.strip():
                    raise core.WikiError("action=search 时 query 不能为空")
                return core.lookup(root, query, scope=scope, limit=limit)
            if action == "read":
                if not path.strip():
                    raise core.WikiError("action=read 时 path 不能为空")
                return core.read(root, path, start_line=start_line, max_chars=max_chars)
            if action == "brief":
                if not query.strip():
                    raise core.WikiError("action=brief 时 query 需填写任务描述")
                return core.brief(root, query, scope=scope, limit=limit)
            if action == "analyze":
                return core.analyze(root)
            if action == "initialize":
                return core.initialize(root, force=force)
            if action == "status":
                return {"watcher": core.indexer.watcher_status(root), "startup_watcher": watcher}
            raise core.WikiError("assistant_knowledge action 仅支持 search、read、brief、analyze、initialize 或 status")

    if "assistant_memory" in enabled_tools:

        @mcp.tool()
        def assistant_memory(
            action: str,
            title: str = "",
            content: str = "",
            source: str = "",
            knowledge_type: str = "事实",
            module: str = "system",
            source_refs: list[str] | None = None,
            source_path: str = "",
            destination: str = "",
            company: str = "",
            category: str = "项目资料",
            task_id: str = "",
            confirm: bool = False,
        ) -> dict:
            """晋升稳定长期知识或显式归档文档；两类写入默认只预检，确认后才执行。

            Args:
                action: promote 或 archive
                title/content/source/knowledge_type/module: promote 的长期知识字段
                source_refs: promote 的 Memory Center task、receipt 或其他可追溯来源引用
                task_id: promote 的可选 Memory Center 任务锚点；仅在存在可信任务绑定时传入
                source_path: archive 的绝对源路径
                destination 或 company/category: archive 的目标路由
                confirm: 二次确认后才执行写入
            """
            if action == "promote":
                return core.promote(
                    root, title=title, content=content, source=source,
                    knowledge_type=knowledge_type, module=module,
                    source_refs=source_refs, confirm=confirm, task_id=task_id,
                )
            if action == "archive":
                if not source_path.strip():
                    raise core.WikiError("action=archive 时 source_path 不能为空")
                return core.archive(
                    root,
                    source_path,
                    destination=destination,
                    company=company,
                    category=category,
                    confirm=confirm,
                    allowed_source_roots=allowed_roots,
                )
            raise core.WikiError("assistant_memory action 仅支持 promote 或 archive")

    if "assistant_skill" in enabled_tools:

        @mcp.tool()
        def assistant_skill(
            action: str,
            source_paths: list[str] | None = None,
            name: str = "",
            description: str = "",
            body: str = "",
            chapters: list[dict[str, str]] | None = None,
            glossary: str = "",
            patterns: str = "",
            cheatsheet: str = "",
            mode: str = "text",
            workdir: str = "",
            published: bool = False,
            evidence_refs: list[str] | None = None,
            confirm: bool = False,
        ) -> dict:
            """将受授权资料制作为私有候选 Skill，或审阅候选目录。

            action=analyze 只做确定性资料提取和有界预览；action=create 接收 Agent 编写的
            结构化内容，默认预检，confirm=true 才创建。生成内容是候选，不是 Wiki 事实，
            不得将自动生成内容直接视为长期事实或跳过人工审阅。

            Args:
                action: analyze、extract、create、list、inspect、validate、publish、published、export、read 或 remove
                source_paths: analyze/extract/create 的受授权文件、目录路径列表
                name: create/inspect/validate/read 的小写 Skill 名称
                description: create 的 Agent Skills 描述
                body: create 的正文，应提供 frameworks、decision_rules、anti_patterns 和按需 references
                chapters: create 的章节参考，每项包含 title 和 content，生成到 references/ 并按需加载
                glossary/patterns/cheatsheet: create 的可选术语表、模式清单和速查表
                mode: extract 时的 text 或 technical 提取模式
                workdir: extract 的空工作目录；留空则创建独立临时目录
                evidence_refs: publish 的任务验证证据引用，至少一条；Research Kit 护照快照仅可作为关联来源，仍需真实任务验证引用。发布产物会将二者分开固化为可移植 release manifest，但不会把它误标为普遍验证通过
                published: read/remove 时是否作用于已发布 Skill；默认 false 指候选目录
                confirm: create 时二次确认，默认仅预检
            """
            if action == "analyze":
                return skill_catalog.analyze_sources(root, source_paths or [], allowed_roots)
            if action == "extract":
                return skill_catalog.extract_sources(root, source_paths or [], allowed_roots, mode, workdir)
            if action == "create":
                return skill_catalog.create_candidate(
                    root, candidates, source_paths or [], name, description, body, allowed_roots, confirm,
                    chapters, glossary, patterns, cheatsheet,
                )
            if action == "list":
                return skill_catalog.list_candidates(candidates)
            if action == "inspect":
                return skill_catalog.inspect_candidate(candidates, name)
            if action == "validate":
                return skill_catalog.validate_candidate(candidates, name)
            if action == "publish":
                return skill_catalog.publish_candidate(candidates, published_dir, name, evidence_refs, confirm)
            raise core.WikiError("assistant_skill action 仅支持 analyze、extract、create、list、inspect、validate 或 publish")

    if "assistant_admin" in enabled_tools:

        @mcp.tool()
        def assistant_admin(action: str, scope: str = "business", force: bool = False) -> dict:
            """校验知识库契约、扫描编译垃圾或维护底层索引；扫描只报告，不删除。

            Args:
                action: validate、scan 或 index
                scope: scan 范围，business 或 full
                force: index 时强制重新抽取全部文档
            """
            if action == "validate":
                return core.validate(root)
            if action == "scan":
                return core.clean(root, scope=scope)
            if action == "index":
                return core.indexer.build_index(root, force=force)
            raise core.WikiError("assistant_admin action 仅支持 validate、scan 或 index")

    return mcp
