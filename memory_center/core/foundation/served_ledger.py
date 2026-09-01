"""跨调用已服务文件账本(设计参考 OpenViking context_assembler/ledger.py)。

记录"本会话已经给模型看过的文件路径集合",供后续检索把重复结果降权,
避免长会话里 mc_lookup 反复返回同一批文件占用 token。与 OV 的语义一致:

- 账本是 bookkeeping,任何读写失败都降级为"无去重",绝不阻断查询;
- 按会话(session_id)隔离;无 session_id 的调用不记录也不降权;
- 有界:每个会话最多保留 MAX_SERVED_PATHS 条路径,超限丢弃最旧的。
"""
from __future__ import annotations

import json
import re
from collections import OrderedDict
from pathlib import Path
from typing import Any

LEDGER_FILENAME = "served-ledger.json"
LEDGER_VERSION = 1
MAX_SERVED_PATHS = 500
# 进程内缓存,避免每次 lookup 都读盘;键为 (workspace, session_id)。
_INPROC_LEDGERS: dict[tuple[str, str], OrderedDict[str, str]] = {}


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


def _session_key(workspace_file: str | Path, session_id: str) -> tuple[str, str]:
    return str(workspace_file), session_id.strip()


def _ledger_path(workspace_file: str | Path) -> Path:
    from memory_center.core.storage.workspace import WorkspaceStore

    return WorkspaceStore(workspace_file).memory_dir / LEDGER_FILENAME


def _load_all(workspace_file: str | Path) -> dict[str, Any]:
    try:
        path = _ledger_path(workspace_file)
        if not path.exists():
            return {"version": LEDGER_VERSION, "sessions": {}}
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or int(data.get("version", 0) or 0) != LEDGER_VERSION:
            return {"version": LEDGER_VERSION, "sessions": {}}
        if not isinstance(data.get("sessions"), dict):
            return {"version": LEDGER_VERSION, "sessions": {}}
        return data
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {"version": LEDGER_VERSION, "sessions": {}}


def _save_all(workspace_file: str | Path, data: dict[str, Any]) -> None:
    try:
        path = _ledger_path(workspace_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass  # 账本写失败绝不阻断查询


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
    normalized = [normalize_path(p) for p in (file_paths or [])]
    normalized = [p for p in normalized if p]
    if not normalized:
        # 空增量不是错误:返回当前账本大小(会话已存在时),便于调用方探测。
        try:
            existing = _INPROC_LEDGERS.get(_session_key(workspace_file, sid))
            if existing is not None:
                return len(existing)
            raw = _load_all(workspace_file).get("sessions", {}).get(sid)
            if isinstance(raw, dict) and isinstance(raw.get("paths"), dict):
                return len(raw["paths"])
        except Exception:
            pass
        return 0
    try:
        key = _session_key(workspace_file, sid)
        ledger = _INPROC_LEDGERS.get(key)
        if ledger is None:
            sessions = _load_all(workspace_file).get("sessions", {})
            raw = sessions.get(sid)
            if isinstance(raw, dict) and isinstance(raw.get("paths"), dict):
                ledger = OrderedDict(
                    sorted(raw["paths"].items(), key=lambda kv: str(kv[1]), reverse=False)
                )
                # 值是 tier,排序键用插入序号;这里简化为按 dict 原序保留。
                ledger = OrderedDict(raw["paths"].items())
            else:
                ledger = OrderedDict()
        for path in normalized:
            ledger.pop(path, None)
            ledger[path] = str(tier or "")
        while len(ledger) > MAX_SERVED_PATHS:
            ledger.popitem(last=False)
        _INPROC_LEDGERS[key] = ledger
        data = _load_all(workspace_file)
        data.setdefault("sessions", {})[sid] = {"paths": dict(ledger), "tier": str(tier or "")}
        # 有界:最多保留 50 个会话的账本。
        while len(data["sessions"]) > 50:
            data["sessions"].pop(next(iter(data["sessions"])))
        _save_all(workspace_file, data)
        return len(ledger)
    except Exception:
        return 0


def served_files(workspace_file: str | Path, session_id: str) -> set[str]:
    """读取某会话的已服务路径集合;读不到返回空集(不去重)。"""
    sid = str(session_id or "").strip()
    if not sid:
        return set()
    key = _session_key(workspace_file, sid)
    ledger = _INPROC_LEDGERS.get(key)
    if ledger is not None:
        return set(ledger.keys())
    try:
        raw = _load_all(workspace_file).get("sessions", {}).get(sid)
        if isinstance(raw, dict) and isinstance(raw.get("paths"), dict):
            ledger = OrderedDict(raw["paths"].items())
            _INPROC_LEDGERS[key] = ledger
            return set(ledger.keys())
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
