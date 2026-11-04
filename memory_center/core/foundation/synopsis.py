"""外部化工具结果的确定性摘要(synopsis)生成。

设计参考 OpenViking 的 tool_result_synopsis:纯函数、无模型依赖、每类
结构化格式使用显式常量上限做有界采样。当 session event payload 超过
内联上限被外置到 memory/refs/ 时,事件本体保留一份 synopsis,使
resume/handoff/recent-evidence 无需展开 payload 即可判断证据内容。
"""
from __future__ import annotations

import csv
import io
import json
import re
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

SynopsisKind = Literal["json", "csv", "tsv", "yaml", "xml", "code", "text", "unknown"]

# 分类规则:按行首模式识别代码文本。文档类提示优先于宽泛的代码骨架识别。
_CODE_PATTERNS = [
    re.compile(r"^\s*(from\s+\S+\s+import|import\s+\S+)", re.MULTILINE),
    re.compile(r"^\s*(class|def|async\s+def|function|export\s+function|const|let|var)\s+\w+", re.MULTILINE),
    re.compile(r"^\s*(package|use|pub\s+fn|fn|public\s+class)\s+\w+", re.MULTILINE),
]
_CODE_COMMENT_HINTS = ("def ", "class ", "import ", "return ", "self.", "fn ", "func ")

# 每类格式的有界采样上限(与 OV 同源的常量表风格,数值按 MC payload 形态调整)。
_TEXT_HEADER_LIMIT = 18
_TEXT_EXCERPT_CHARS = 500
_JSON_MAX_DEPTH = 2
_JSON_ARRAY_SAMPLE_LIMIT = 3
_JSON_OBJECT_KEY_LIMIT = 10
_YAML_KEY_LIMIT = 30
_XML_CHILD_TAG_LIMIT = 30
_TABLE_FIRST_ROW_SAMPLE_CHARS = 180
_CODE_IMPORT_LIMIT = 12
_CODE_SYMBOL_LIMIT = 24
_CODE_IMPORT_LINE_CHARS = 180
_CODE_SYMBOL_LINE_CHARS = 200
_SUMMARY_LINE_CHARS = 160
_STRUCTURE_LINE_CHARS = 120


@dataclass(frozen=True)
class ToolResultSynopsis:
    """一条外置 payload 的确定性摘要,全部字段有界。"""

    kind: SynopsisKind
    title: str
    summary: list[str] = field(default_factory=list)
    structure: list[str] = field(default_factory=list)
    notable_items: list[str] = field(default_factory=list)
    sample: str = ""


def _clip(value: str, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def detect_kind(text: str) -> SynopsisKind:
    """按内容探测 payload 文本类型;顺序与 OV 一致:结构化格式优先于代码/文本。"""
    stripped = text.strip()
    if not stripped:
        return "unknown"
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            json.loads(stripped)
            return "json"
        except (json.JSONDecodeError, ValueError):
            pass
    if stripped.startswith("<") and stripped.endswith(">"):
        try:
            ET.fromstring(stripped)
            return "xml"
        except ET.ParseError:
            pass
    lines = stripped.splitlines()
    if len(lines) >= 2:
        dialect = _sniff_dialect(lines[0])
        if dialect in {"csv", "tsv"}:
            return dialect
    if stripped.startswith(("-", "?")) or re.match(r"^\S+\s*:", stripped):
        try:
            loaded = json.loads(json.dumps(_mini_yaml_probe(stripped)))
            if isinstance(loaded, dict) and len(loaded) >= 1:
                return "yaml"
        except (ValueError, TypeError):
            pass
    code_hits = sum(1 for pattern in _CODE_PATTERNS if pattern.search(stripped))
    if code_hits >= 2 or (code_hits >= 1 and any(hint in stripped[:600] for hint in _CODE_COMMENT_HINTS)):
        return "code"
    return "text"


def _sniff_dialect(header: str) -> Literal["csv", "tsv", "none"]:
    if "\t" in header and "," not in header:
        return "tsv"
    if header.count(",") >= 1:
        return "csv"
    return "none"


def _mini_yaml_probe(text: str) -> dict[str, Any]:
    """极简 top-level key 探测,只用于区分 yaml 与普通文本。"""
    keys: dict[str, Any] = {}
    for line in text.splitlines():
        if not line or line.lstrip().startswith("#"):
            continue
        if line.startswith((" ", "\t", "-", "  ")):
            continue
        key, sep, _ = line.partition(":")
        if sep and key.strip() and re.match(r"^[\w.\-]+$", key.strip()):
            keys[key.strip()] = None
    return keys


def _json_summary(parsed: Any) -> ToolResultSynopsis:
    summary: list[str] = []
    structure: list[str] = []
    notable: list[str] = []

    def walk(node: Any, depth: int, path: str) -> None:
        if depth > _JSON_MAX_DEPTH:
            structure.append(_clip(f"{path} …", _STRUCTURE_LINE_CHARS))
            return
        if isinstance(node, dict):
            keys = list(node.keys())
            structure.append(_clip(f"{path} object({len(keys)} keys)", _STRUCTURE_LINE_CHARS))
            for key in keys[:_JSON_OBJECT_KEY_LIMIT]:
                value = node[key]
                if isinstance(value, (dict, list)):
                    notable.append(_clip(f"{path}.{key}: {type(value).__name__}({len(value)})", _SUMMARY_LINE_CHARS))
                elif value is not None and not isinstance(value, (bool, int, float)):
                    notable.append(_clip(f"{path}.{key}={value}", _SUMMARY_LINE_CHARS))
                elif isinstance(value, (bool, int, float)):
                    notable.append(_clip(f"{path}.{key}={value}", _SUMMARY_LINE_CHARS))
                walk(value, depth + 1, f"{path}.{key}")
        elif isinstance(node, list):
            structure.append(_clip(f"{path} array(len={len(node)})", _STRUCTURE_LINE_CHARS))
            for item in node[:_JSON_ARRAY_SAMPLE_LIMIT]:
                walk(item, depth + 1, f"{path}[]")

    walk(parsed, 0, "$")
    if isinstance(parsed, dict):
        summary.append(_clip(f"object with {len(parsed)} top-level keys", _SUMMARY_LINE_CHARS))
    elif isinstance(parsed, list):
        summary.append(_clip(f"array with {len(parsed)} items", _SUMMARY_LINE_CHARS))
    return ToolResultSynopsis(kind="json", title="json payload", summary=summary[:6], structure=structure[:10], notable_items=notable[:8])


def _table_summary(text: str, dialect: Literal["csv", "tsv"]) -> ToolResultSynopsis:
    delimiter = "\t" if dialect == "tsv" else ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = [row for row in reader if any(cell.strip() for cell in row)][:_TEXT_HEADER_LIMIT + 1]
    header = rows[0] if rows else []
    data_rows = rows[1:]
    counts = Counter(row[0].strip() for row in data_rows if row and row[0].strip())
    notable = [f"{value} x{count}" for value, count in counts.most_common(5)]
    sample = delimiter.join(cell.strip() for cell in header)[:_TABLE_FIRST_ROW_SAMPLE_CHARS]
    first = data_rows[0] if data_rows else []
    return ToolResultSynopsis(
        kind=dialect,
        title=f"{dialect.upper()} table: {len(data_rows)} data rows x {len(header)} columns",
        summary=[_clip(f"columns: {', '.join(str(cell) for cell in header)}", _SUMMARY_LINE_CHARS)],
        structure=[_clip(f"first row: {delimiter.join(str(cell) for cell in first)}", _STRUCTURE_LINE_CHARS)],
        notable_items=notable,
        sample=sample,
    )


def _yaml_summary(text: str) -> ToolResultSynopsis:
    keys = _mini_yaml_probe(text)
    top_keys = list(keys.keys())[:_YAML_KEY_LIMIT]
    structure = [_clip(f"top-level key: {key}", _STRUCTURE_LINE_CHARS) for key in top_keys]
    excerpt_lines = [line.rstrip() for line in text.splitlines() if line.strip()][:_TEXT_HEADER_LIMIT]
    return ToolResultSynopsis(
        kind="yaml",
        title=f"yaml document: {len(top_keys)} top-level keys",
        summary=[_clip(line, _SUMMARY_LINE_CHARS) for line in excerpt_lines[:5]],
        structure=structure[:12],
        sample="\n".join(excerpt_lines[:6])[:_TEXT_EXCERPT_CHARS],
    )


def _xml_summary(text: str) -> ToolResultSynopsis:
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return _text_summary(text)
    children = list(root)[:_XML_CHILD_TAG_LIMIT]
    tags = Counter(child.tag for child in list(root))
    structure = [_clip(f"<{root.tag}> with {len(list(root))} children", _STRUCTURE_LINE_CHARS)]
    structure.extend(_clip(f"<{child.tag}> {dict(list(child.attrib.items())[:3])}", _STRUCTURE_LINE_CHARS) for child in children[:6])
    return ToolResultSynopsis(
        kind="xml",
        title=f"xml document: <{root.tag}>",
        summary=[_clip(f"child tags: {dict(tags.most_common(5))}", _SUMMARY_LINE_CHARS)],
        structure=structure[:8],
        sample=text.strip()[:_TEXT_EXCERPT_CHARS],
    )


def _code_summary(text: str) -> ToolResultSynopsis:
    imports: list[str] = []
    symbols: list[str] = []
    symbol_pattern = re.compile(r"^\s*(?:class|def|async\s+def|function|fn|pub\s+fn|public\s+class|const|let|var)\s+\w+")
    import_pattern = re.compile(r"^\s*(?:from\s+\S+\s+import|import\s+\S+|use\s+\S+|package\s+\S+)")
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if import_pattern.match(line) and len(imports) < _CODE_IMPORT_LIMIT:
            imports.append(stripped[:_CODE_IMPORT_LINE_CHARS])
        elif symbol_pattern.match(line) and len(symbols) < _CODE_SYMBOL_LIMIT:
            symbols.append(stripped[:_CODE_SYMBOL_LINE_CHARS])
    title_bits = [str(len(symbols)), "symbols", str(len(imports)), "imports"]
    return ToolResultSynopsis(
        kind="code",
        title=" ".join(title_bits),
        summary=[_clip(f"symbols: {', '.join(_symbol_name(item) for item in symbols[:10])}", _SUMMARY_LINE_CHARS)] if symbols else [],
        structure=[_clip(item, _STRUCTURE_LINE_CHARS) for item in imports[:6]],
        sample=text.strip()[:_TEXT_EXCERPT_CHARS],
    )


def _symbol_name(line: str) -> str:
    match = re.search(r"(?:class|def|fn|function|const|let|var|pub\s+fn)\s+(\w+)", line)
    return match.group(1) if match else line[:40]


def _text_summary(text: str) -> ToolResultSynopsis:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    head = lines[:_TEXT_HEADER_LIMIT]
    return ToolResultSynopsis(
        kind="text",
        title=_clip(lines[0] if lines else "empty text", 80) or "empty text",
        summary=[_clip(line, _SUMMARY_LINE_CHARS) for line in head[:5]],
        sample="\n".join(head)[:_TEXT_EXCERPT_CHARS],
    )


def build_synopsis(text: str) -> ToolResultSynopsis:
    """对一段 payload 文本生成确定性摘要;任何异常都降级为 text 摘要。"""
    body = str(text or "")
    if not body.strip():
        return ToolResultSynopsis(kind="unknown", title="empty payload")
    try:
        kind = detect_kind(body)
    except Exception:  # pragma: no cover - 探测本身不应让记录链路失败
        return _text_summary(body)
    try:
        if kind == "json":
            return _json_summary(json.loads(body.strip()))
        if kind in {"csv", "tsv"}:
            return _table_summary(body, kind)
        if kind == "yaml":
            return _yaml_summary(body)
        if kind == "xml":
            return _xml_summary(body)
        if kind == "code":
            return _code_summary(body)
        return _text_summary(body)
    except Exception:  # pragma: no cover - 单类解析失败降级为 text
        try:
            return _text_summary(body)
        except Exception:
            return ToolResultSynopsis(kind="unknown", title="synopsis generation failed")


# 标识符/元数据类短字段:它们描述"这条事件是什么",不是需要摘要的结果正文。
_META_KEYS = frozenset(
    {
        "tool_name", "query", "target", "name", "project", "file_path", "path",
        "intent", "session_id", "task_id", "event_type", "type", "kind", "status",
        "workspace", "source", "ref_id", "receipt_ref", "payload_ref", "note",
    }
)


def synopsis_from_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    """从 session event payload 中选出最大文本字段生成 synopsis。

    跳过标识符/元数据类短字段,只摘要结果正文(output/result/content 等);
    无可用文本时返回 None。
    """
    candidates: list[tuple[int, str, str]] = []
    preferred_order = ("output", "stdout", "result", "response", "content", "body", "text", "diff")
    for key in preferred_order:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            candidates.append((len(value), key, value))
    for key, value in payload.items():
        if key in preferred_order or key in _META_KEYS:
            continue
        if not isinstance(value, str) or not value.strip():
            continue
        candidates.append((len(value), key, value))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    _, field_name, text = candidates[0]
    synopsis = build_synopsis(text)
    data = asdict(synopsis)
    data["title"] = _clip(f"{payload.get('tool_name', '') or field_name}: {synopsis.title}", 120).strip(": ")
    data["source_field"] = field_name
    return data


__all__ = ["ToolResultSynopsis", "build_synopsis", "detect_kind", "synopsis_from_payload"]
