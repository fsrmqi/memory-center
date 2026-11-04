"""受治理的文档到 Agent Skill 候选目录。

确定性地抽取/清点资料，语义结构由调用 Agent 显式生成，并让大文件只在需要时加载。
这里不复制来源正文，也不把生成内容当作 Wiki 事实；它只创建带来源哈希的私有候选
Skill，供人工审阅和后续验证。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from memory_center.platform.assistant import core, skill_ingestion_adapter
from memory_center.platform.assistant.skill_ingestion.config import SUPPORTED_EXTENSIONS

MAX_SOURCES = 64
MAX_SOURCE_BYTES = 100 * 1024 * 1024
MAX_EXCERPT_CHARS = 1_200
MAX_SKILL_BODY_CHARS = 80_000
_NAME_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")


def _safe_name(name: str) -> str:
    value = (name or "").strip()
    if not _NAME_RE.fullmatch(value):
        raise core.WikiError("Skill 名称需为 1-64 位小写字母、数字或连字符，且不能以连字符开头")
    return value


def _allowed_sources(root: Path, paths: list[str], allowed_roots: tuple[Path, ...]) -> list[Path]:
    if not paths:
        raise core.WikiError("source_paths 至少需要一个受授权的资料路径")
    roots = (root.resolve(), *(item.expanduser().resolve() for item in allowed_roots))
    files: list[Path] = []
    for raw in paths:
        candidate = Path(raw).expanduser()
        if candidate.is_symlink():
            raise core.WikiError("Skill 来源不能是符号链接")
        path = candidate.resolve()
        if not path.exists() or not core._is_within(path, roots):
            raise core.WikiError("Skill 来源不存在或未处于已授权资料范围")
        if core._find_sensitive_path(path):
            raise core.WikiError("Skill 来源包含疑似凭据文件，拒绝处理")
        if path.is_file():
            files.append(path)
        else:
            files.extend(item for item in path.rglob("*") if item.is_file() and not item.is_symlink())
    unique = sorted(set(files))
    if not unique:
        raise core.WikiError("Skill 来源中没有可处理的文件")
    if len(unique) > MAX_SOURCES:
        raise core.WikiError(f"Skill 来源文件超过上限 {MAX_SOURCES}")
    unsupported = [item for item in unique if item.suffix.lower() not in SUPPORTED_EXTENSIONS]
    if unsupported:
        raise core.WikiError(f"Skill 来源包含不支持的格式：{unsupported[0].name}")
    total_bytes = sum(item.stat().st_size for item in unique)
    if total_bytes > MAX_SOURCE_BYTES:
        raise core.WikiError(f"Skill 来源总大小超过上限 {MAX_SOURCE_BYTES} bytes")
    sensitive = core._find_sensitive_content(unique)
    if sensitive:
        raise core.WikiError(f"Skill 来源含疑似凭据内容，拒绝处理：{sensitive.name}")
    return unique


def _manifest(files: list[Path]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    records: list[dict[str, Any]] = []
    excerpts: list[dict[str, str]] = []
    for path in files:
        try:
            preview = skill_ingestion_adapter.extract_collection([path], mode="text", retain_workdir=False)
            text = preview["preview"]
            extractor = preview["sources"][0]["extraction_method"]
            title = path.stem
        except Exception as exc:
            title, text, extractor = path.stem, "", f"failed:{type(exc).__name__}"
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        records.append({
            "source_id": f"source-{hashlib.sha256(str(path).encode()).hexdigest()[:16]}",
            "name": path.name,
            "sha256": digest,
            "bytes": path.stat().st_size,
            "extractor": extractor,
            "title": title[:160],
            "extracted_chars": len(text),
        })
        excerpts.append({"name": path.name, "content": text[:MAX_EXCERPT_CHARS]})
    return records, excerpts


def analyze_sources(root: Path, source_paths: list[str], allowed_source_roots: tuple[Path, ...] = ()) -> dict[str, Any]:
    """确定性地返回来源清单和有界预览，供 Agent 生成结构而非逐次重读原文。"""
    root = root.expanduser().resolve()
    files = _allowed_sources(root, source_paths, allowed_source_roots)
    sources, excerpts = _manifest(files)
    return {
        "schema_version": 1,
        "source_count": len(sources),
        "total_bytes": sum(item["bytes"] for item in sources),
        "sources": sources,
        "excerpts": excerpts,
        "next_action": "根据来源生成 frameworks、decision_rules、anti_patterns 和按主题加载的 references；不要复制原文段落",
    }


def extract_sources(
    root: Path,
    source_paths: list[str],
    allowed_source_roots: tuple[Path, ...] = (),
    mode: str = "text",
    workdir: str = "",
) -> dict[str, Any]:
    """运行可复现的多格式提取，并返回独立工作目录和章节边界。"""
    root = root.expanduser().resolve()
    files = _allowed_sources(root, source_paths, allowed_source_roots)
    return skill_ingestion_adapter.extract_collection(files, mode=mode, workdir=workdir)


def _skill_document(name: str, description: str, body: str, chapters: list[dict[str, str]]) -> str:
    description = (description or "").strip()
    body = (body or "").strip()
    if not description or len(description) > 1024:
        raise core.WikiError("description 不能为空且不能超过 1024 字符")
    if not body or len(body) > MAX_SKILL_BODY_CHARS:
        raise core.WikiError(f"body 不能为空且不能超过 {MAX_SKILL_BODY_CHARS} 字符")
    references = ""
    if chapters:
        links = "\n".join(f"- [{item['title']}](references/{item['file']})" for item in chapters)
        references = f"\n\n## 按需参考\n\n{links}\n"
    return f'---\nname: {name}\ndescription: "{description.replace(chr(34), chr(39))}"\n---\n\n# {name}\n\n{body}{references}'


def _chapter_artifacts(chapters: list[dict[str, str]] | None) -> list[dict[str, str]]:
    artifacts: list[dict[str, str]] = []
    for index, item in enumerate(chapters or [], start=1):
        title = (item.get("title") or "").strip() if isinstance(item, dict) else ""
        content = (item.get("content") or "").strip() if isinstance(item, dict) else ""
        if not title or not content:
            raise core.WikiError("chapters 的每项都需要 title 和 content")
        if len(content) > 20_000:
            raise core.WikiError("单个章节参考不能超过 20000 字符")
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:48] or f"chapter-{index:02d}"
        artifacts.append({"title": title[:120], "file": f"ch{index:02d}-{slug}.md", "content": f"# {title}\n\n{content}\n"})
    return artifacts


def create_candidate(
    root: Path,
    skill_root: Path,
    source_paths: list[str],
    name: str,
    description: str,
    body: str,
    allowed_source_roots: tuple[Path, ...] = (),
    confirm: bool = False,
    chapters: list[dict[str, str]] | None = None,
    glossary: str = "",
    patterns: str = "",
    cheatsheet: str = "",
) -> dict[str, Any]:
    """创建不可覆盖的候选 Skill；confirm=False 时只返回完整预览。"""
    root = root.expanduser().resolve()
    name = _safe_name(name)
    sources = analyze_sources(root, source_paths, allowed_source_roots)
    chapter_artifacts = _chapter_artifacts(chapters)
    document = _skill_document(name, description, body, chapter_artifacts)
    skill_root = skill_root.expanduser().resolve()
    target = skill_root / name
    if target.exists() or target.is_symlink():
        raise core.WikiError(f"候选 Skill 已存在，禁止覆盖：{target}")
    auxiliary = {
        "glossary.md": glossary.strip(),
        "patterns.md": patterns.strip(),
        "cheatsheet.md": cheatsheet.strip(),
    }
    for filename, content in auxiliary.items():
        if len(content) > 20_000:
            raise core.WikiError(f"{filename} 不能超过 20000 字符")
    artifacts = {"SKILL.md": document, **{f"references/{item['file']}": item["content"] for item in chapter_artifacts}}
    artifacts.update({filename: content + "\n" for filename, content in auxiliary.items() if content})
    manifest = {
        "schema_version": 1,
        "name": name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_count": sources["source_count"],
        "sources": sources["sources"],
        "skill_sha256": hashlib.sha256(document.encode("utf-8")).hexdigest(),
        "artifacts": {path: hashlib.sha256(content.encode("utf-8")).hexdigest() for path, content in artifacts.items()},
        "status": "candidate",
        "sharing": "private",
    }
    preview = {
        "schema_version": 1,
        "status": "需要确认" if not confirm else "候选已创建",
        "name": name,
        "target": str(target),
        "source_count": manifest["source_count"],
        "chapter_count": len(chapter_artifacts),
        "artifacts": sorted(manifest["artifacts"]),
        "skill_sha256": manifest["skill_sha256"],
        "document": document,
        "estimated_tokens": max(1, len(document) // 4),
        "sharing": "private",
        "confirmed": confirm,
        "next_action": "审阅 SKILL.md 与 sources.json；在真实任务验证后，再将稳定结论通过 assistant_memory(promote) 晋升到 Wiki",
    }
    if not confirm:
        return preview
    skill_root.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{name}-", dir=skill_root))
    try:
        for relative, content in artifacts.items():
            destination = stage / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content, encoding="utf-8")
        (stage / "sources.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (stage / "README.md").write_text(
            f"# {name}\n\n私有候选 Skill。来源清单及哈希见 `sources.json`；章节放在 `references/`，只在相关问题出现时读取。不得将来源原文或本 Skill 对外分发。\n",
            encoding="utf-8",
        )
        os.replace(stage, target)
    except OSError as exc:
        if stage.exists():
            for child in sorted(stage.rglob("*"), reverse=True):
                child.unlink() if child.is_file() else child.rmdir()
            stage.rmdir()
        raise core.WikiError(f"候选 Skill 创建失败：{exc}") from exc
    return preview


def _candidate_path(skill_root: Path, name: str) -> Path:
    return skill_root.expanduser().resolve() / _safe_name(name)


def inspect_candidate(skill_root: Path, name: str) -> dict[str, Any]:
    target = _candidate_path(skill_root, name)
    manifest = target / "sources.json"
    skill = target / "SKILL.md"
    if not target.is_dir() or target.is_symlink() or not manifest.is_file() or not skill.is_file():
        raise core.WikiError("候选 Skill 不存在或结构不完整")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    return {"target": str(target), "manifest": data, "body": skill.read_text(encoding="utf-8"), "validation": validate_candidate(skill_root, name)}


def list_candidates(skill_root: Path) -> dict[str, Any]:
    root = skill_root.expanduser().resolve()
    if not root.is_dir():
        return {"skill_root": str(root), "candidates": []}
    candidates = []
    for item in sorted(root.iterdir()):
        if item.is_symlink() or not item.is_dir() or not (item / "sources.json").is_file():
            continue
        try:
            manifest = json.loads((item / "sources.json").read_text(encoding="utf-8"))
            candidates.append({"name": item.name, "status": manifest.get("status"), "source_count": manifest.get("source_count")})
        except (OSError, json.JSONDecodeError):
            candidates.append({"name": item.name, "status": "invalid"})
    return {"skill_root": str(root), "candidates": candidates}


def validate_candidate(skill_root: Path, name: str) -> dict[str, Any]:
    target = _candidate_path(skill_root, name)
    errors: list[str] = []
    warnings: list[str] = []
    skill = target / "SKILL.md"
    manifest = target / "sources.json"
    if not skill.is_file() or not manifest.is_file():
        return {"valid": False, "errors": ["缺少 SKILL.md 或 sources.json"], "warnings": []}
    text = skill.read_text(encoding="utf-8-sig")
    if not text.startswith("---\n") or "\n---\n" not in text:
        errors.append("SKILL.md 缺少 YAML frontmatter")
    if not re.search(r"^name:\s*" + re.escape(name) + r"\s*$", text, re.MULTILINE):
        errors.append("frontmatter name 与目录名不一致")
    if not re.search(r"^description:\s*\S+", text, re.MULTILINE):
        errors.append("frontmatter 缺少 description")
    if len(text.splitlines()) > 500:
        warnings.append("SKILL.md 超过 500 行；建议将章节内容拆到按需读取的 references/ 目录")
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        if data.get("name") != name or not data.get("sources"):
            errors.append("sources.json 缺少名称或来源清单")
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if data.get("skill_sha256") != digest:
            errors.append("SKILL.md 已变更，sources.json 中的 skill_sha256 不匹配")
        for relative, expected in data.get("artifacts", {}).items():
            artifact = target / relative
            if not artifact.is_file():
                errors.append(f"缺少已登记工件：{relative}")
                continue
            actual = hashlib.sha256(artifact.read_bytes()).hexdigest()
            if actual != expected:
                errors.append(f"已登记工件哈希不匹配：{relative}")
    except (OSError, json.JSONDecodeError):
        errors.append("sources.json 不是有效 JSON")
    return {"valid": not errors, "errors": errors, "warnings": warnings}


def _classify_evidence_refs(evidence_refs: list[str]) -> dict[str, list[str]]:
    """Separate supporting run snapshots from task-validation evidence.

    Research Kit passports are useful provenance, but an exported snapshot alone
    cannot demonstrate that a candidate Skill worked on a real task.
    """
    snapshot_prefix = "dsh-research-kit:run:"
    snapshots = [ref for ref in evidence_refs if ref.startswith(snapshot_prefix) and ":passport:" in ref]
    return {
        "validation_refs": [ref for ref in evidence_refs if ref not in snapshots],
        "snapshot_refs": snapshots,
    }


def _publication_manifest(candidate: Path, name: str, evidence: dict[str, list[str]]) -> dict[str, Any]:
    """Build a portable, privacy-safe release record for a published Skill.

    A publication is not proof that the Skill is universally correct.  It records
    the exact immutable candidate content and the evidence references supplied for
    this release, so another host can decide whether the asset is eligible for its
    own retrieval or release policy without reading the candidate's source files.
    """
    source_manifest = json.loads((candidate / "sources.json").read_text(encoding="utf-8"))
    source_digest = hashlib.sha256(
        json.dumps(source_manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "schema_version": 2,
        "asset": {
            "kind": "agent_skill",
            "name": name,
            "version": f"sha256:{source_manifest['skill_sha256']}",
            "content_sha256": source_manifest["skill_sha256"],
            "source_manifest_sha256": source_digest,
        },
        "release": {
            "status": "published",
            "published_at": datetime.now(timezone.utc).isoformat(),
            "verification_status": "validation_referenced",
            "evidence_refs": [*evidence["validation_refs"], *evidence["snapshot_refs"]],
            "validation_refs": evidence["validation_refs"],
            "snapshot_refs": evidence["snapshot_refs"],
        },
        "provenance": {
            "source_count": source_manifest["source_count"],
            "artifact_hashes": source_manifest["artifacts"],
            "sharing": source_manifest.get("sharing", "private"),
        },
    }


def publish_candidate(
    candidate_root: Path,
    published_root: Path,
    name: str,
    evidence_refs: list[str] | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """将通过完整性校验且具备任务证据的候选发布到 Agent 发现目录。"""
    name = _safe_name(name)
    candidate = _candidate_path(candidate_root, name)
    validation = validate_candidate(candidate_root, name)
    if not validation["valid"]:
        raise core.WikiError(f"候选 Skill 未通过校验：{validation['errors']}")
    refs = []
    for value in evidence_refs or []:
        cleaned = value.strip()[:300] if isinstance(value, str) else ""
        if cleaned and cleaned not in refs:
            refs.append(cleaned)
    if not refs:
        raise core.WikiError("发布需要至少一条任务验证证据引用，例如 Memory Center receipt 或 task 引用")
    evidence = _classify_evidence_refs(refs)
    if not evidence["validation_refs"]:
        raise core.WikiError("研究运行护照快照只能关联发布记录；发布还需要至少一条真实任务验证证据引用")
    published_root = published_root.expanduser().resolve()
    target = published_root / name
    if target.exists() or target.is_symlink():
        raise core.WikiError(f"全局 Skill 已存在，禁止覆盖：{target}")
    preview = {
        "status": "需要确认" if not confirm else "已发布",
        "name": name,
        "candidate": str(candidate),
        "target": str(target),
        "evidence_refs": refs,
        "validation": validation,
        "confirmed": confirm,
        "next_action": "确认候选内容与真实任务效果无误后，以 confirm=true 再次调用 publish",
    }
    if not confirm:
        return preview
    published_root.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{name}-", dir=published_root))
    try:
        shutil.copytree(candidate, stage / name, symlinks=False)
        publication = _publication_manifest(candidate, name, evidence)
        (stage / name / "publication.json").write_text(
            json.dumps(publication, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
        os.replace(stage / name, target)
        stage.rmdir()
    except OSError as exc:
        if stage.exists():
            shutil.rmtree(stage)
        raise core.WikiError(f"全局 Skill 发布失败：{exc}") from exc
    return preview
