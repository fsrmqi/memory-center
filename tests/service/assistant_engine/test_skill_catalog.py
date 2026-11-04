import hashlib
import json
from pathlib import Path

import pytest
from test_core import make_wiki

from memory_center.platform.assistant import core, skill_catalog, skill_ingestion_adapter


def test_candidate_skill_requires_confirmation_and_keeps_hashed_sources(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    source_root = tmp_path / "sources"
    skill_root = tmp_path / "skills"
    source_root.mkdir()
    make_wiki(wiki)
    source = source_root / "runbook.md"
    source.write_text("# 发布 Runbook\n\n先验证，再回滚。\n", encoding="utf-8")

    preview = skill_catalog.create_candidate(
        wiki, skill_root, [str(source)], "release-runbook", "发布流程的受治理参考。",
        "## Decision rules\n\n- 先验证，再发布。\n", (source_root,),
    )
    assert preview["status"] == "需要确认"
    assert not (skill_root / "release-runbook").exists()

    created = skill_catalog.create_candidate(
        wiki, skill_root, [str(source)], "release-runbook", "发布流程的受治理参考。",
        "## Decision rules\n\n- 先验证，再发布。\n", (source_root,), confirm=True,
        chapters=[{"title": "验证", "content": "检查关键回执。"}], glossary="回执：可验证结果。", cheatsheet="先验证。",
    )
    target = Path(created["target"])
    assert (target / "SKILL.md").is_file()
    assert (target / "references/ch01-chapter-01.md").is_file()
    assert (target / "glossary.md").is_file()
    assert str(source) not in (target / "sources.json").read_text(encoding="utf-8")
    assert skill_catalog.validate_candidate(skill_root, "release-runbook")["valid"]
    assert skill_catalog.list_candidates(skill_root)["candidates"] == [
        {"name": "release-runbook", "status": "candidate", "source_count": 1}
    ]


def test_candidate_skill_rejects_unapproved_or_sensitive_sources(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    allowed = tmp_path / "allowed"
    denied = tmp_path / "denied"
    allowed.mkdir()
    denied.mkdir()
    make_wiki(wiki)
    (denied / "note.md").write_text("# no\n", encoding="utf-8")
    with pytest.raises(core.WikiError, match="已授权"):
        skill_catalog.analyze_sources(wiki, [str(denied / "note.md")], (allowed,))
    secret = allowed / ".env"
    secret.write_text("TOKEN=top-secret-value\n", encoding="utf-8")
    with pytest.raises(core.WikiError, match="凭据"):
        skill_catalog.analyze_sources(wiki, [str(secret)], (allowed,))


def test_candidate_validation_detects_untracked_skill_edits(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    source_root = tmp_path / "sources"
    skill_root = tmp_path / "skills"
    source_root.mkdir()
    make_wiki(wiki)
    source = source_root / "note.md"
    source.write_text("# 标准\n", encoding="utf-8")
    skill_catalog.create_candidate(
        wiki, skill_root, [str(source)], "standard", "标准参考。", "## Rules\n\n- 保持兼容。\n",
        (source_root,), confirm=True,
    )
    skill = skill_root / "standard/SKILL.md"
    skill.write_text(skill.read_text(encoding="utf-8") + "\n未登记修改。\n", encoding="utf-8")
    result = skill_catalog.validate_candidate(skill_root, "standard")
    assert not result["valid"]
    assert any("skill_sha256" in error for error in result["errors"])


def test_candidate_publish_requires_evidence_and_second_confirmation(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    source_root = tmp_path / "sources"
    candidates = tmp_path / "candidates"
    published = tmp_path / "published"
    source_root.mkdir()
    make_wiki(wiki)
    source = source_root / "note.md"
    source.write_text("# 标准\n", encoding="utf-8")
    skill_catalog.create_candidate(
        wiki, candidates, [str(source)], "release-safety", "发布安全参考。", "## Rules\n\n- 先验证。\n",
        (source_root,), confirm=True,
    )
    with pytest.raises(core.WikiError, match="至少一条"):
        skill_catalog.publish_candidate(candidates, published, "release-safety")
    with pytest.raises(core.WikiError, match="护照快照"):
        skill_catalog.publish_candidate(
            candidates, published, "release-safety", ["dsh-research-kit:run:research-42:passport:abc123"],
        )
    preview = skill_catalog.publish_candidate(
        candidates, published, "release-safety", [
            "memory-center:task:42:receipt:passed",
            "dsh-research-kit:run:research-42:passport:abc123",
        ],
    )
    assert preview["status"] == "需要确认"
    assert not (published / "release-safety").exists()
    result = skill_catalog.publish_candidate(
        candidates, published, "release-safety", [
            "memory-center:task:42:receipt:passed",
            "dsh-research-kit:run:research-42:passport:abc123",
        ], confirm=True,
    )
    assert result["status"] == "已发布"
    assert (published / "release-safety/SKILL.md").is_file()
    publication = json.loads((published / "release-safety/publication.json").read_text(encoding="utf-8"))
    candidate_manifest = json.loads((candidates / "release-safety/sources.json").read_text(encoding="utf-8"))
    expected_source_manifest_sha256 = hashlib.sha256(
        json.dumps(candidate_manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert publication["schema_version"] == 2
    assert publication["asset"] == {
        "kind": "agent_skill",
        "name": "release-safety",
        "version": f"sha256:{candidate_manifest['skill_sha256']}",
        "content_sha256": candidate_manifest["skill_sha256"],
        "source_manifest_sha256": expected_source_manifest_sha256,
    }
    assert publication["release"]["status"] == "published"
    assert publication["release"]["verification_status"] == "validation_referenced"
    assert publication["release"]["evidence_refs"] == [
        "memory-center:task:42:receipt:passed",
        "dsh-research-kit:run:research-42:passport:abc123",
    ]
    assert publication["release"]["validation_refs"] == ["memory-center:task:42:receipt:passed"]
    assert publication["release"]["snapshot_refs"] == ["dsh-research-kit:run:research-42:passport:abc123"]
    assert publication["provenance"]["source_count"] == 1
    assert "candidate_path" not in publication


def test_extract_sources_creates_isolated_artifacts_and_chapter_outline(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    source_root = tmp_path / "sources"
    workdir = tmp_path / "work"
    source_root.mkdir()
    make_wiki(wiki)
    source = source_root / "guide.md"
    source.write_text("# 前言\n\n内容。\n\n# Chapter 1 规划\n\n先确认边界。\n", encoding="utf-8")

    result = skill_catalog.extract_sources(
        wiki, [str(source)], (source_root,), mode="technical", workdir=str(workdir),
    )

    assert Path(result["text_file"]).is_file()
    assert Path(result["metadata_file"]).is_file()
    assert result["sources"][0]["name"] == "guide.md"
    assert any("Chapter 1" in chapter["title"] for chapter in result["chapters"])
    assert "SOURCE: guide.md" in Path(result["text_file"]).read_text(encoding="utf-8")


def test_extract_sources_supports_html_and_rejects_nonempty_workdir(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    source_root = tmp_path / "sources"
    workdir = tmp_path / "work"
    source_root.mkdir()
    workdir.mkdir()
    make_wiki(wiki)
    source = source_root / "guide.html"
    source.write_text("<html><head><title>x</title></head><body><h1>规则</h1><p>保留正文。</p></body></html>", encoding="utf-8")
    result = skill_catalog.extract_sources(wiki, [str(source)], (source_root,))
    assert "保留正文" in result["preview"]
    (workdir / "old.txt").write_text("old", encoding="utf-8")
    with pytest.raises(core.WikiError, match="非空"):
        skill_catalog.extract_sources(wiki, [str(source)], (source_root,), workdir=str(workdir))


def test_analyze_does_not_leave_extracted_source_text_in_tempdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    wiki = tmp_path / "wiki"
    source_root = tmp_path / "sources"
    temp_root = tmp_path / "temporary"
    source_root.mkdir()
    temp_root.mkdir()
    make_wiki(wiki)
    source = source_root / "guide.md"
    source.write_text("# 指南\n\n正文。\n", encoding="utf-8")
    monkeypatch.setattr(skill_ingestion_adapter.tempfile, "tempdir", str(temp_root))

    result = skill_catalog.analyze_sources(wiki, [str(source)], (source_root,))

    assert result["source_count"] == 1
    assert not list(temp_root.iterdir())


def test_extracted_sensitive_content_is_rejected_and_auto_workdir_is_cleaned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    wiki = tmp_path / "wiki"
    source_root = tmp_path / "sources"
    temp_root = tmp_path / "temporary"
    source_root.mkdir()
    temp_root.mkdir()
    make_wiki(wiki)
    source = source_root / "scan.pdf"
    source.write_bytes(b"%PDF synthetic")
    monkeypatch.setattr(skill_ingestion_adapter.tempfile, "tempdir", str(temp_root))

    def fake_extract(path: Path, mode: str, install_mode: str) -> dict:
        return {
            "text": "api_key = sk-abcdefghijklmnopqrstuvwxyz123456", "format": "pdf",
            "extraction_method": "fake", "pages": 1, "pages_label": "pages", "chars": 42,
            "words": 1, "estimated_tokens": 12, "images_dropped": 0, "chapters_detected": 0,
            "chapters_method": "none", "has_toc": False,
        }

    monkeypatch.setattr(skill_ingestion_adapter.utils, "extract_single_file", fake_extract)
    with pytest.raises(core.WikiError, match="api_token"):
        skill_catalog.extract_sources(wiki, [str(source)], (source_root,))
    assert not list(temp_root.iterdir())
