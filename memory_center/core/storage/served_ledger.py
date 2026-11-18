"""跨调用已服务文件账本(设计参考 OpenViking context_assembler/ledger.py)。

记录"本会话已经给模型看过的文件路径集合",供后续检索把重复结果降权,
避免长会话里 mc_lookup 反复返回同一批文件占用 token。与 OV 的语义一致:

- 账本由 storage.SessionStateRepository 写入 SQLite；任何读写失败都降级为"无去重",绝不阻断查询;
- 按会话(session_id)隔离;无 session_id 的调用不记录也不降权;
- 有界:每个会话最多保留 MAX_SERVED_PATHS 条路径,超限丢弃最旧的。

归属：本模块是会话状态账本，属于 storage（基础事实与访问能力）。此前位于
``core.foundation``，导致基础层反向依赖 storage；按 foundation/README.md
「不得承载工作区 I/O」的边界迁至此处。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .session_state import MAX_SERVED_PATHS, SessionStateRepository

# 兼容旧导入；状态已迁移为 SQLite 的 session_state，不再直接写 JSON 文件。
LEDGER_FILENAME = "served-ledger.json"
LEDGER_VERSION = 1


def normalize_path(path: str) -> str:
    """统一路径分隔符并去尾空白;空串返回空串。"""
    return str(path or "").replace("\\", "/").strip()


def paths_refer_to_same_file(left: str, right: str) -> bool:
    """保守匹配绝对/相对路径，拒绝只按 basename 的歧义匹配。"""
    left_normalized = normalize_path(left)
    right_normalized = normalize_path(right)
    if not left_normalized or not right_normalized:
        return False
    if left_normalized == right_normalized:
        return True
    left_absolute = left_normalized.startswith("/")
    right_absolute = right_normalized.startswith("/")
    if left_absolute == right_absolute:
        return False
    absolute, relative = (left_normalized, right_normalized) if left_absolute else (right_normalized, left_normalized)
    return absolute.endswith("/" + relative.lstrip("/"))


def record_served_files(
    workspace_file: str | Path,
    session_id: str,
    file_paths: list[str],
    *,
    tier: str = "",
) -> int:
    """把本次响应里已提供给模型的文件路径记入会话账本,返回账本大小。

    无 session_id 或路径为空时是 no-op;任何异常静默降级。
    """
    sid = str(session_id or "").strip()
    if not sid:
        return 0
    try:
        repo = SessionStateRepository(workspace_file)
        normalized = [normalize_path(path) for path in file_paths]
        if not any(normalized):
            return len(repo.served_files(sid))
        return repo.record_served_files(sid, normalized, tier=tier)
    except Exception:
        return 0


def served_files(workspace_file: str | Path, session_id: str) -> set[str]:
    """读取某会话的已服务路径集合;读不到返回空集(不去重)。"""
    sid = str(session_id or "").strip()
    if not sid:
        return set()
    try:
        return SessionStateRepository(workspace_file).served_files(sid)
    except Exception:
        pass
    return set()


def extract_file_paths_from_payload(payload: dict[str, Any]) -> list[str]:
    """从 lookup 响应里提取已服务的文件路径集合(有界,最多 50 条)。

    来源字段均为既有响应结构:read_targets[].path、matches[].node.file_path、
    best_match.file_path、primary_chain.steps[].file_path。缺失时返回空表,
    不做任何猜测性提取。
    """
    paths: list[str] = []

    def _add(value: Any) -> None:
        if isinstance(value, str) and value.strip():
            paths.append(normalize_path(value))

    read_targets = payload.get("read_targets")
    if isinstance(read_targets, list):
        for item in read_targets[:50]:
            if isinstance(item, dict):
                _add(item.get("path") or item.get("file_path"))
    result = payload.get("result")
    result = result if isinstance(result, dict) else payload
    best_match = result.get("best_match")
    if isinstance(best_match, dict):
        _add(best_match.get("file_path") or best_match.get("path"))
    matches = result.get("matches")
    if isinstance(matches, list):
        for item in matches[:50]:
            node = item.get("node") if isinstance(item, dict) else None
            if isinstance(node, dict):
                _add(node.get("file_path") or node.get("path"))
    results = result.get("results")
    if isinstance(results, list):
        for item in results[:50]:
            node = item.get("node") if isinstance(item, dict) else None
            if isinstance(node, dict):
                _add(node.get("file_path") or node.get("path"))
    chain = payload.get("primary_chain")
    if isinstance(chain, dict):
        for step in chain.get("steps", [])[:20]:
            if isinstance(step, dict):
                _add(step.get("file_path") or step.get("path"))
    seen: set[str] = set()
    unique = [p for p in paths if not (p in seen or seen.add(p))]
    return unique[:50]


__all__ = [
    "LEDGER_FILENAME",
    "LEDGER_VERSION",
    "MAX_SERVED_PATHS",
    "normalize_path",
    "paths_refer_to_same_file",
    "record_served_files",
    "served_files",
    "extract_file_paths_from_payload",
]
