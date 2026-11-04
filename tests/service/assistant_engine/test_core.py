import hashlib
from pathlib import Path

import pytest

from memory_center.platform.assistant import core


def make_wiki(root: Path) -> None:
    (root / "工作/acme/项目资料").mkdir(parents=True)
    (root / "技术/项目").mkdir(parents=True)
    (root / "模块注册表.md").write_text(
        """---
title: 模块注册表
module: system
owner: test
created: 2026-08-20
updated: 2026-08-20
version: v1.0
status: 生效
---

| module 短码 | 领域 |
|---|---|
| `system` | 系统 |
| `acme` | acme 公司级业务 |

| 公司 | 目录 |
|---|---|
| acme | `工作/acme/` |
""",
        encoding="utf-8",
    )


def test_read_is_paginated_and_confined(tmp_path: Path) -> None:
    make_wiki(tmp_path)
    note = tmp_path / "技术/项目/note.md"
    note.write_text("第一行\n第二行\n第三行\n", encoding="utf-8")

    result = core.read(tmp_path, "技术/项目/note.md", start_line=2, max_chars=4)

    assert result["content"] == "第二行\n"
    assert result["next_start_line"] == 3
    with pytest.raises(core.WikiError, match="相对路径"):
        core.read(tmp_path, "/etc/hosts")


def test_lookup_validates_scope_and_limit(tmp_path: Path) -> None:
    make_wiki(tmp_path)
    with pytest.raises(core.WikiError, match="scope 未登记"):
        core.lookup(tmp_path, "项目", scope="不存在")
    with pytest.raises(core.WikiError, match="limit"):
        core.lookup(tmp_path, "项目", limit=0)


def test_read_rejects_symlink(tmp_path: Path) -> None:
    make_wiki(tmp_path)
    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    outside.write_text("secret", encoding="utf-8")
    link = tmp_path / "技术/项目/outside.txt"
    link.symlink_to(outside)

    with pytest.raises(core.WikiError, match="符号链接"):
        core.read(tmp_path, "技术/项目/outside.txt")


def test_archive_requires_preview_confirmation_and_allowlist(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    source_root = tmp_path / "sources"
    source_root.mkdir()
    make_wiki(wiki)
    source = source_root / "资料.md"
    source.write_text("# 资料\n", encoding="utf-8")

    preview = core.archive(
        wiki,
        str(source),
        company="acme",
        allowed_source_roots=(source_root,),
    )
    target = wiki / "工作/acme/项目资料/资料.md"
    assert preview["status"] == "需要确认"
    assert not target.exists()

    result = core.archive(
        wiki,
        str(source),
        company="acme",
        confirm=True,
        allowed_source_roots=(source_root,),
    )
    assert result["mode"] == "copy"
    assert target.read_text(encoding="utf-8") == "# 资料\n"


def test_archive_rejects_sensitive_files(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    source_root = tmp_path / "sources"
    source_root.mkdir()
    make_wiki(wiki)
    secret = source_root / ".env"
    secret.write_text("TOKEN=x\n", encoding="utf-8")

    with pytest.raises(core.WikiError, match="L1"):
        core.archive(wiki, str(secret), allowed_source_roots=(source_root,))


def test_archive_rejects_source_code_and_archives(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    source_root = tmp_path / "sources"
    source_root.mkdir()
    make_wiki(wiki)
    source = source_root / "Example.java"
    source.write_text("class Example {}\n", encoding="utf-8")

    with pytest.raises(core.WikiError, match="白名单内文档"):
        core.archive(wiki, str(source), allowed_source_roots=(source_root,))


def test_archive_rejects_directory_symlink(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    source_root = tmp_path / "sources"
    docs = source_root / "docs"
    outside = source_root / "outside"
    docs.mkdir(parents=True)
    outside.mkdir()
    make_wiki(wiki)
    (outside / "Example.java").write_text("class Example {}\n", encoding="utf-8")
    (docs / "external").symlink_to(outside, target_is_directory=True)

    with pytest.raises(core.WikiError, match="包含符号链接"):
        core.archive(wiki, str(docs), allowed_source_roots=(source_root,))


def test_archive_requires_explicit_route_and_rejects_unknown_binary(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    source_root = tmp_path / "sources"
    source_root.mkdir()
    make_wiki(wiki)
    note = source_root / "资料.md"
    note.write_text("# 文档\n", encoding="utf-8")
    with pytest.raises(core.WikiError, match="必须显式提供"):
        core.archive(wiki, str(note), allowed_source_roots=(source_root,))
    binary = source_root / "dump.db"
    binary.write_bytes(b"data")
    with pytest.raises(core.WikiError, match="白名单"):
        core.archive(
            wiki, str(binary), destination="技术/参考资料/文档",
            allowed_source_roots=(source_root,),
        )


def test_promote_requires_confirmation_and_writes_governed_knowledge(tmp_path: Path) -> None:
    make_wiki(tmp_path)
    preview = core.promote(
        tmp_path, title="稳定结论", content="已验证。", source="memory-center://task/1",
        source_refs=["delivery-evidence:receipt-1"],
    )
    assert preview["status"] == "需要确认"
    assert preview["schema_version"] == 2
    assert preview["knowledge_id"].startswith("pawiki-")
    assert preview["path"] == preview["target"]
    assert preview["source_refs"] == ["memory-center://task/1", "delivery-evidence:receipt-1"]
    assert not list((tmp_path / "知识沉淀").rglob("*.md"))
    result = core.promote(
        tmp_path, title="稳定结论", content="已验证。", source="memory-center://task/1",
        source_refs=["delivery-evidence:receipt-1"], confirm=True,
    )
    target = tmp_path / result["target"]
    assert target.is_file()
    text = target.read_text(encoding="utf-8")
    assert "knowledge_type: 事实" in text
    assert 'source_refs: ["memory-center://task/1", "delivery-evidence:receipt-1"]' in text
    assert result["knowledge_id"] == preview["knowledge_id"]
    assert result["content_sha256"] == hashlib.sha256(target.read_bytes()).hexdigest()


@pytest.fixture(autouse=True)
def _neutral_profile_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """默认使用中性（空）profile；需要 profile 的用例显式 setenv 覆盖。"""
    monkeypatch.delenv("MEMORY_CENTER_PROFILE", raising=False)
    monkeypatch.delenv("MEMORY_CENTER_PROFILE_DIR", raising=False)


def _profile_file(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "profile.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_promote_empty_profile_does_not_rewrite_alias_like_modules(tmp_path: Path) -> None:
    """空 profile：没有任何公司别名机制，模块保持原样且错误提示无兜底文案。"""
    make_wiki(tmp_path)
    preview = core.promote(tmp_path, title="系统结论", content="已验证。", source="task:1", module="system")
    assert preview["module"] == "system"
    assert "module_routing" not in preview
    with pytest.raises(core.WikiError) as exc_info:
        core.promote(tmp_path, title="别名模块", content="待归类。", source="task:1", module="website")
    message = str(exc_info.value)
    assert "module 未在 模块注册表.md 登记：website" in message
    assert "acme" not in message
    assert "兜底" not in message


def test_promote_uses_profile_module_aliases(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """有 profile：别名生效，routing 使用中性 reason ``module_alias``。"""
    make_wiki(tmp_path)
    profile = _profile_file(
        tmp_path,
        "default_scope: acme\n"
        "module_aliases:\n"
        "  website: acme\n"
        "  media: acme\n"
        "module_alias_until: 2099-12-31\n",
    )
    monkeypatch.setenv("MEMORY_CENTER_PROFILE", str(profile))
    for alias in ("website", "media"):
        preview = core.promote(
            tmp_path, title=f"{alias} 公司业务", content="已确认归属。", source="task:alias", module=alias,
        )
        assert preview["module"] == "acme"
        assert preview["module_routing"] == {
            "requested": alias,
            "resolved": "acme",
            "reason": "module_alias",
            "valid_until": "2099-12-31",
        }


def test_promote_profile_alias_expires_after_valid_until(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``module_alias_until`` 过期后别名失效；profile 的 hint 仍可追加到错误提示。"""
    make_wiki(tmp_path)
    profile = _profile_file(
        tmp_path,
        "module_aliases:\n"
        "  website: acme\n"
        "module_alias_until: 2000-01-01\n"
        "module_alias_hint: 请在 workspace profile 中补登记该 module\n",
    )
    monkeypatch.setenv("MEMORY_CENTER_PROFILE", str(profile))
    with pytest.raises(core.WikiError) as exc_info:
        core.promote(tmp_path, title="过期别名", content="待归类。", source="task:1", module="website")
    message = str(exc_info.value)
    assert "module 未在 模块注册表.md 登记：website" in message
    assert "请在 workspace profile 中补登记该 module" in message


def test_incremental_index_and_brief(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_wiki(tmp_path)
    monkeypatch.setenv("PERSONAL_ASSISTANT_WIKI_CACHE_DIR", str(tmp_path / "cache"))
    note = tmp_path / "技术/项目/架构说明.md"
    note.write_text("# 架构说明\n\n任务接力使用上下文存储。\n", encoding="utf-8")
    first = core.indexer.build_index(tmp_path)
    second = core.indexer.build_index(tmp_path)
    assert first["added"] >= 2
    assert second["unchanged"] == first["total"]
    result = core.lookup(tmp_path, "任务接力")
    assert any(hit["path"].endswith("架构说明.md") for hit in result["hits"])
    context = core.brief(tmp_path, "任务接力")
    assert context["source_count"] >= 1


def test_lookup_automatically_builds_missing_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_wiki(tmp_path)
    monkeypatch.setenv("PERSONAL_ASSISTANT_WIKI_CACHE_DIR", str(tmp_path / "cache"))
    note = tmp_path / "技术/项目/自动索引.md"
    note.write_text("# 自动索引\n\n查询前会自动刷新全文索引。\n", encoding="utf-8")

    result = core.lookup(tmp_path, "自动刷新")

    assert result["hits"]
    assert result["index_refresh"]["mode"] == "initial"
    assert result["index_refresh"]["build"]["added"] >= 1


def test_initialize_builds_index_and_analyzes_structure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_wiki(tmp_path)
    monkeypatch.setenv("PERSONAL_ASSISTANT_WIKI_CACHE_DIR", str(tmp_path / "cache"))
    constitution = tmp_path / "助手规则/最高宪法.md"
    constitution.parent.mkdir(parents=True)
    constitution.write_text(
        "---\ntitle: 最高宪法\nmodule: system\nowner: test\ncreated: 2026-08-21\n"
        "updated: 2026-08-21\nversion: v1.0\nstatus: 生效\n---\n",
        encoding="utf-8",
    )
    (tmp_path / "研究/技术研究").mkdir(parents=True)
    (tmp_path / "研究/技术研究/说明.md").write_text("# 技术研究\n", encoding="utf-8")
    external = tmp_path / ".external"
    external.mkdir()
    (tmp_path / "工作/acme/项目资料/源文档").symlink_to(external, target_is_directory=True)

    result = core.initialize(tmp_path)

    assert result["index_build"]["total"] >= 3
    analysis = result["analysis"]
    assert analysis["index"]["exists"] is True
    assert analysis["index"]["by_top_level"]["研究"] == 1
    assert analysis["structure"]["research_directions"] == ["技术研究"]
    assert analysis["external_links"]["count"] == 1
    assert analysis["external_links"]["items"][0]["available"] is True


def test_validate_checks_governed_docs_but_not_imported_docs(tmp_path: Path) -> None:
    make_wiki(tmp_path)
    governed = tmp_path / "个人档案/索引.md"
    governed.parent.mkdir()
    governed.write_text("# missing frontmatter\n", encoding="utf-8")
    imported = tmp_path / "工作/acme/项目资料/历史.md"
    imported.write_text("# imported without frontmatter\n", encoding="utf-8")

    result = core.validate(tmp_path)

    paths = {item["path"] for item in result["frontmatter_issues"]}
    assert "个人档案/索引.md" in paths
    assert "工作/acme/项目资料/历史.md" not in paths


def test_validate_neutral_when_profile_has_no_governance_paths(tmp_path: Path) -> None:
    """空 profile：没有必填治理文件，不得把「未配置」误报成缺失。"""
    make_wiki(tmp_path)

    result = core.validate(tmp_path)

    assert result["governance_issue_count"] == 0
    assert result["governance_issues"] == []


def test_validate_and_analyze_follow_profile_wiki_topology(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """有 profile：治理文件与顶层目录校验都按 profile 声明执行。"""
    make_wiki(tmp_path)
    profile = _profile_file(
        tmp_path,
        "wiki:\n"
        "  governance_paths:\n"
        "    - 助手规则/最高宪法.md\n"
        "  top_level_dirs:\n"
        "    - 工作\n"
        "    - 研究\n",
    )
    monkeypatch.setenv("MEMORY_CENTER_PROFILE", str(profile))

    missing = core.validate(tmp_path)
    assert missing["governance_issue_count"] == 1
    assert missing["governance_issues"][0]["path"] == "助手规则/最高宪法.md"

    constitution = tmp_path / "助手规则/最高宪法.md"
    constitution.parent.mkdir(parents=True)
    constitution.write_text(
        "---\ntitle: 最高宪法\nmodule: system\nowner: test\ncreated: 2026-08-21\n"
        "updated: 2026-08-21\nversion: v1.0\nstatus: 生效\n---\n",
        encoding="utf-8",
    )
    assert core.validate(tmp_path)["governance_issue_count"] == 0

    analysis = core.analyze(tmp_path)
    assert analysis["structure"]["missing_top_level"] == ["研究"]
    assert set(analysis["structure"]["unexpected_top_level"]) == {"技术", "助手规则"}


def test_analyze_skips_topology_checks_without_profile(tmp_path: Path) -> None:
    """空 profile：不得把全部顶层目录报成 unexpected，也不报 missing。"""
    make_wiki(tmp_path)
    (tmp_path / "研究").mkdir()

    analysis = core.analyze(tmp_path)

    assert analysis["structure"]["missing_top_level"] == []
    assert analysis["structure"]["unexpected_top_level"] == []
    assert not any("顶层目录" in warning for warning in analysis["warnings"])


def test_clean_rejects_unknown_scope(tmp_path: Path) -> None:
    make_wiki(tmp_path)
    with pytest.raises(core.WikiError, match="business 或 full"):
        core.clean(tmp_path, "typo")


def test_clean_full_includes_收件箱_and_知识沉淀(tmp_path: Path) -> None:
    make_wiki(tmp_path)
    (tmp_path / "收件箱/target").mkdir(parents=True)
    (tmp_path / "知识沉淀/target").mkdir(parents=True)
    (tmp_path / "工作/target").mkdir(parents=True)

    result = core.clean(tmp_path, "full")

    paths = {item["path"] for item in result["dirs"]}
    assert "工作/target" in paths
    assert "收件箱/target" in paths
    assert "知识沉淀/target" in paths


def test_promote_task_id_anchor_recorded_and_brief_protocol_updated(tmp_path: Path) -> None:
    """Session-first 约定：promote 可选 task_id 进 frontmatter 与 metadata；
    brief 协议含"无可信锚点仅作背景浏览"条款。"""
    make_wiki(tmp_path)
    preview = core.promote(
        tmp_path, title="锚点结论", content="已验证。", source="memory-center:acme:task:t1",
        confirm=False, task_id="task-anchor-1",
    )
    assert preview["task_id"] == "task-anchor-1"
    assert "task_id" not in preview or preview.get("confirmed") is False
    result = core.promote(
        tmp_path, title="锚点结论", content="已验证。", source="memory-center:acme:task:t1",
        confirm=True, task_id="task-anchor-1",
    )
    text = (tmp_path / result["target"]).read_text(encoding="utf-8")
    assert "task_id: task-anchor-1" in text
    assert result["task_id"] == "task-anchor-1"
    # 不传 task_id 时 frontmatter 不含该字段（additive 兼容）
    result2 = core.promote(
        tmp_path, title="无锚点结论", content="已验证。", source="memory-center:acme:task:t2",
        confirm=True,
    )
    text2 = (tmp_path / result2["target"]).read_text(encoding="utf-8")
    assert "task_id:" not in text2
    assert "task_id" not in result2
    # brief 返回的 assistant_protocol 携带锚点约定
    brief = core.brief(tmp_path, "测试任务描述")
    assert any("背景浏览" in item for item in brief["assistant_protocol"])
