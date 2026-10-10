"""将内置 Skill 资料提取器接入 Wiki MCP 的受治理适配层。"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Any

from memory_center.platform.assistant import core
from memory_center.platform.assistant.skill_ingestion import ExtractionError, pdf_inspector_integration, utils
from memory_center.platform.assistant.skill_ingestion.parsers import calibre

_MARKDOWN_HEADING = re.compile(r"^\s*(?:#{1,6}|={1,6})\s+(.+?)\s*$")
_EXTRACTION_LOCK = threading.RLock()


def _chapter_outline(text: str, detected: list[str]) -> list[dict[str, str]]:
    """补足结构检测的标题样本：numeric 与 structural 两种结果均可供 Agent 分章。"""
    titles = list(detected)
    for line in text.splitlines():
        match = _MARKDOWN_HEADING.match(line)
        if match:
            title = match.group(1).strip().rstrip("#").strip()
            if title and title not in titles:
                titles.append(title)
    return [{"title": title[:180]} for title in titles[:120]]


def extract_collection(
    files: list[Path], mode: str, workdir: str = "", retain_workdir: bool = True,
) -> dict[str, Any]:
    """运行完整提取链，但禁止自动安装依赖、隐藏绝对路径并保留逐源失败。"""
    if mode not in {"text", "technical"}:
        raise core.WikiError("mode 仅支持 text 或 technical")
    if not files:
        raise core.WikiError("没有可提取的来源文件")
    managed_workdir = not workdir
    output = Path(workdir).expanduser().resolve() if workdir else Path(tempfile.mkdtemp(prefix="wiki-skill-work-"))
    if output.exists() and any(output.iterdir()):
        raise core.WikiError("workdir 已存在且非空，拒绝覆盖已有提取结果")
    try:
        utils.prepare_output_dir(output)
    except ExtractionError as exc:
        raise core.WikiError(str(exc)) from exc

    sources: list[dict[str, Any]] = []
    sections: list[str] = []
    failures: list[dict[str, str]] = []
    try:
        # PDF hook 与 Calibre 输出目录依赖模块级状态；加锁避免并发请求串写工作目录。
        with _EXTRACTION_LOCK:
            calibre.OUTPUT_DIR = output
            pdf_inspector_integration.install_pdf_inspector_hook(utils)
            for file_path in files:
                try:
                    # Wiki MCP 不允许工具调用隐式 pip install；缺少可选依赖时保留回退链和诊断。
                    result = utils.extract_single_file(file_path, mode, install_mode="no")
                except ExtractionError as exc:
                    failures.append({"name": file_path.name, "error": str(exc)[:1_000]})
                    continue
                text = result.pop("text")
                reason = core.sensitive_text_reason(text)
                if reason:
                    raise core.WikiError(f"提取正文命中敏感内容规则：{file_path.name} ({reason})")
                source_id = f"source-{hashlib.sha256(str(file_path).encode()).hexdigest()[:16]}"
                sections.append(f"\n\n{'=' * 80}\nSOURCE: {file_path.name} ({source_id})\n{'=' * 80}\n\n{text}")
                sources.append({
                    "source_id": source_id,
                    "name": file_path.name,
                    "sha256": hashlib.sha256(file_path.read_bytes()).hexdigest(),
                    "bytes": file_path.stat().st_size,
                    "format": result["format"],
                    "extraction_method": result["extraction_method"],
                    "pages": result["pages"],
                    "pages_label": result["pages_label"],
                    "chars": result["chars"],
                    "words": result["words"],
                    "estimated_tokens": result["estimated_tokens"],
                    "images_dropped": result["images_dropped"],
                    "chapters_detected": result["chapters_detected"],
                    "chapters_method": result["chapters_method"],
                    "has_toc": result["has_toc"],
                })
        if not sources:
            raise core.WikiError(f"所有 {len(failures)} 个来源均提取失败：{failures}")

        full_text = "".join(sections).strip()
        text_path = output / "full_text.txt"
        metadata_path = output / "metadata.json"
        text_path.write_text(full_text, encoding="utf-8")
        structure = utils.detect_structure("\n\n".join(section.split("\n\n", 2)[-1] for section in sections))
        metadata: dict[str, Any] = {
            "schema_version": 2,
            "mode": mode,
            "workdir": str(output),
            "text_file": str(text_path),
            "metadata_file": str(metadata_path),
            "source_count": len(sources),
            "failed_source_count": len(failures),
            "failures": failures,
            "estimated_tokens": utils.estimate_tokens(full_text),
            "sources": sources,
            "chapters": _chapter_outline(full_text, structure["chapter_headings_sample"]),
            **structure,
        }
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        pdf_inspector_integration.enrich_pdf_inspector_metadata(metadata_path)
        response = {**metadata, "preview": full_text[:1_200]}
        if not retain_workdir:
            response.update({"workdir": None, "text_file": None, "metadata_file": None})
            shutil.rmtree(output)
        return response
    except Exception:
        if (not retain_workdir or managed_workdir) and output.exists():
            shutil.rmtree(output)
        raise
