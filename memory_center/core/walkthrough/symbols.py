"""Pure helpers for resolving Java symbols, paths and method bodies for walkthroughs.

These functions intentionally do not touch the GraphStore or workspace cache.
They take indexed dicts (from ``java-symbol-index.json`` / ``file-index.json``)
and the workspace config, and return plain dictionaries.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List

from ..orchestrator.common import _project_matches

__all__ = [
    "parse_method_walkthrough_symbol",
    "find_method_symbol_entry",
    "find_receiver_impl_method",
    "build_file_abs_path_map",
    "resolve_indexed_abs_path",
    "extract_java_method_body",
    "extract_java_method_body_from_path",
    "matching_brace_end_runtime",
    "find_method_span_lines",
    "line_number_at_offset",
    "detect_unqualified_same_class_calls",
    "extract_java_case_labels",
]


def parse_method_walkthrough_symbol(symbol: str) -> Dict[str, str]:
    raw = (symbol or "").strip()
    if "#" in raw:
        owner, method = raw.rsplit("#", 1)
    else:
        owner, method = raw, ""
    owner = owner.strip()
    method = method.strip()
    class_name = owner.split(".")[-1] if owner else ""
    package = owner[: -(len(class_name) + 1)] if "." in owner and class_name else ""
    return {"raw": raw, "owner": owner, "package": package, "class": class_name, "method": method}


def find_method_symbol_entry(
    symbols: List[Dict[str, Any]],
    parsed: Dict[str, str],
    project: str = "",
) -> Dict[str, Any]:
    class_name = parsed.get("class", "")
    package = parsed.get("package", "")
    method = parsed.get("method", "")
    if not class_name or not method:
        return {}
    candidates: List[tuple[int, Dict[str, Any], str]] = []
    for item in symbols:
        owner_names = list(item.get("classes", []) or []) + list(item.get("interfaces", []) or [])
        if class_name not in owner_names or method not in (item.get("methods", []) or []):
            continue
        if project and not _project_matches(project, item.get("project", "")):
            continue
        score = 0
        if package and item.get("package") == package:
            score += 100
        if package and package in str(item.get("file", "")).replace("/", "."):
            score += 40
        if class_name in (item.get("classes", []) or []):
            score += 20
        if class_name in (item.get("interfaces", []) or []):
            score += 10
        candidates.append((score, item, class_name))
    if not candidates and project:
        return find_method_symbol_entry(symbols, parsed, project="")
    if not candidates:
        return {}
    candidates.sort(key=lambda row: (-row[0], row[1].get("project", ""), row[1].get("file", "")))
    _, item, owner = candidates[0]
    return {"symbol": item, "class_name": owner, "project": item.get("project", ""), "file": item.get("file", "")}


def find_receiver_impl_method(
    symbols: List[Dict[str, Any]],
    receiver_type: str,
    method_name: str,
    project: str,
) -> Dict[str, Any]:
    preferred_names = [f"{receiver_type}Impl"]
    if receiver_type.endswith("Service"):
        preferred_names.append(receiver_type.removesuffix("Service") + "ServiceImpl")
    candidates: List[tuple[int, Dict[str, Any], str]] = []
    for item in symbols:
        if method_name not in (item.get("methods", []) or []):
            continue
        if project and not _project_matches(project, item.get("project", "")):
            continue
        class_names = list(item.get("classes", []) or [])
        interface_names = list(item.get("interfaces", []) or [])
        for class_name in class_names:
            score = 0
            if class_name in preferred_names:
                score += 100
            if class_name.endswith("Impl") and receiver_type in class_name:
                score += 70
            if receiver_type in interface_names:
                score += 60
            if receiver_type in str(item.get("file", "")):
                score += 30
            if score:
                candidates.append((score, item, class_name))
    if not candidates:
        return {}
    candidates.sort(key=lambda row: (-row[0], row[1].get("project", ""), row[1].get("file", "")))
    _, item, class_name = candidates[0]
    return {"symbol": item, "class_name": class_name, "project": item.get("project", ""), "file": item.get("file", "")}


def build_file_abs_path_map(config: Any, store: Any) -> Dict[tuple[str, str], str]:
    file_index = store.read_json_prefer_backend("file-index.json", [])
    mapping: Dict[tuple[str, str], str] = {}
    for row in file_index:
        project = str(row.get("project", "") or "")
        path = str(row.get("path", "") or "")
        abs_path = str(row.get("abs_path", "") or "")
        if project and path and abs_path:
            mapping[(project, path)] = abs_path
            mapping[("", path)] = abs_path
    for service in getattr(config, "services", []) or []:
        try:
            service_root = config.resolve_service_path(service)
            prefix = config.service_logical_prefix(service)
        except Exception:
            continue
        if not prefix:
            continue
        mapping.setdefault((service.name, prefix), str(service_root))
    mapping.setdefault(("", ""), str(getattr(config, "root_path", Path.cwd())))
    return mapping


def resolve_indexed_abs_path(
    file_abs_map: Dict[tuple[str, str], str],
    project: str,
    file_path: str,
) -> str:
    if not file_path:
        return ""
    direct = file_abs_map.get((project, file_path)) or file_abs_map.get(("", file_path))
    if direct:
        return direct
    root = file_abs_map.get(("", ""), "")
    if root:
        return str((Path(root) / file_path).resolve())
    return file_path


_METHOD_HEADER_PATTERN = (
    r"(?:@\w+(?:\([^)]*\))?\s*)*"
    r"(?:public|private|protected)\s+"
    r"(?:static\s+)?[\w<>, ?\.\[\]]+\s+"
)


def _method_header_regex(method_name: str) -> re.Pattern[str]:
    return re.compile(
        _METHOD_HEADER_PATTERN
        + re.escape(method_name)
        + r"\s*\([^;{}]*\)\s*(?:throws\s+[\w, ]+\s*)?\{",
        re.M,
    )


def matching_brace_end_runtime(text: str, open_pos: int) -> int:
    depth = 0
    pos = open_pos
    while pos < len(text):
        ch = text[pos]
        if ch == '"':
            pos += 1
            while pos < len(text):
                if text[pos] == "\\":
                    pos += 2
                elif text[pos] == '"':
                    pos += 1
                    break
                else:
                    pos += 1
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return pos
        pos += 1
    return len(text)


def extract_java_method_body(text: str, method_name: str) -> str:
    match = _method_header_regex(method_name).search(text)
    if not match:
        return ""
    open_pos = match.end() - 1
    close_pos = matching_brace_end_runtime(text, open_pos)
    if close_pos <= open_pos:
        return ""
    return text[open_pos + 1:close_pos]


def extract_java_method_body_from_path(abs_path: str, method_name: str) -> str:
    if not abs_path or not method_name:
        return ""
    try:
        text = Path(abs_path).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    return extract_java_method_body(text, method_name)


def line_number_at_offset(text: str, offset: int) -> int:
    return text.count("\n", 0, max(offset, 0)) + 1


def find_method_span_lines(abs_path: str, method_name: str) -> Dict[str, int]:
    if not abs_path:
        return {}
    try:
        text = Path(abs_path).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return {}
    match = _method_header_regex(method_name).search(text)
    if not match:
        return {}
    open_pos = match.end() - 1
    close_pos = matching_brace_end_runtime(text, open_pos)
    return {
        "start_line": line_number_at_offset(text, match.start()),
        "end_line": line_number_at_offset(text, close_pos),
    }


_SAME_CLASS_IGNORED = {
    "if", "for", "while", "switch", "catch", "return", "new", "throw", "super", "this",
    "try", "else", "do", "synchronized",
}


def detect_unqualified_same_class_calls(
    abs_path: str,
    owner_method: str,
    class_methods: set[str],
) -> List[str]:
    if not abs_path:
        return []
    try:
        text = Path(abs_path).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    body = extract_java_method_body(text, owner_method)
    if not body:
        return []
    calls: List[str] = []
    seen: set[str] = set()
    for match in re.finditer(r"(?<![.\w])([A-Za-z_]\w*)\s*\(", body):
        name = match.group(1)
        if name in _SAME_CLASS_IGNORED or name not in class_methods or name in seen:
            continue
        seen.add(name)
        calls.append(name)
    return calls


def extract_java_case_labels(abs_path: str, method_name: str) -> List[str]:
    body = extract_java_method_body_from_path(abs_path, method_name)
    labels: List[str] = []
    for match in re.finditer(r"\bcase\s+([^:]+)\s*:", body):
        label = match.group(1).strip().strip('"')
        if label and label not in labels:
            labels.append(label)
    return labels
