"""内容寻址的文件级解析缓存。

依据 `docs/benchmarks/V5_SERVICE_INDEX_STAGE_BASELINE.md`：服务侧一遍索引里同一份
源码被读三次、Java 被 tree-sitter 解析两次，解析占单遍墙钟的绝大部分。本模块把
**文件级 IR** 按内容缓存下来，让「只改了几个文件的再次索引」不再重解析其余文件。

三条不变量：

1. **内容寻址**：键 = sha256(缓存契约版本 ‖ 命名空间 ‖ 文件身份 ‖ 语言 ‖ 内容 sha256)。
   文件改名而内容不变仍然命中；内容一变必然未命中——不会把改过的文件读回旧结果。
   文件身份（项目名 + 相对路径）进键，是因为 Java 专用解析的产物里带着这两项；
   若只按内容寻址，两个内容相同但分属不同项目的文件会互相顶掉。
2. **缓存不改变产物**：命中与未命中返回**逐值相等**的对象。缓存只影响速度，不影响
   索引结果，因此可以直接用「冷跑产物 == 热跑产物」验证（见 test_parse_cache.py）。
3. **坏缓存只退化为未命中**：文件缺失、截断、JSON 损坏、契约版本不符，一律按未命中
   处理并允许覆写；目录只读或载荷不可序列化时跳过写入。缓存故障绝不中止索引。

跨文件关系（导入绑定落到哪个文件、调用边、Feign 目标服务）**不缓存**，留在归并
阶段重算：任何一个文件变了，依赖它的关系都会重新求值，不会读到过期边。
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from memory_center.core.indexing.parse_result import CallSite, StructuralParseResult, SymbolSpan

# 载荷结构与解析语义的契约版本。改动结构性结果的编码方式、或任何会改变解析输出的
# 实现时**必须**递增，否则旧载荷会被当成新结果复用。
CACHE_SCHEMA = 1

STRUCTURAL_NAMESPACE = "structural"
JAVA_NAMESPACE = "java"

# 缓存目录的默认字节上限；超出后按最近解析时间淘汰到预算内。
DEFAULT_MAX_BYTES = 512 * 1024 * 1024

# 预算开关：``MEMORY_CENTER_PARSE_CACHE_MB=0`` 关闭解析缓存，未设置或无法解析时用默认值。
BUDGET_ENV = "MEMORY_CENTER_PARSE_CACHE_MB"


def cache_key(namespace: str, *parts: str) -> str:
    """内容寻址键：任何一项不同都得到不同的键。"""
    material = "\x00".join((str(CACHE_SCHEMA), namespace, *(str(part) for part in parts)))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def configured_budget_bytes(env: Mapping[str, str] | None = None) -> int:
    """解析缓存字节预算；0 表示关闭解析缓存。"""
    source = os.environ if env is None else env
    raw = str(source.get(BUDGET_ENV, "") or "").strip()
    if not raw:
        return DEFAULT_MAX_BYTES
    try:
        megabytes = int(raw)
    except ValueError:
        return DEFAULT_MAX_BYTES
    return max(0, megabytes) * 1024 ** 2


def enforce_budget(directory: str | Path, max_bytes: int = DEFAULT_MAX_BYTES) -> dict[str, int]:
    """按最近使用时间淘汰，把缓存目录压回字节预算内。

    命中会刷新时间戳（见 :meth:`ParseCache.get`），所以一轮索引结束后，
    **仍在用的**条目时间都是新的、**已不再被任何文件引用的**条目（源码改过或
    删掉的旧内容）时间停在最后一次被读到的时刻，先于在用条目被淘汰。预算足够时
    不做任何删除。
    """
    root = Path(directory)
    outcome = {"evicted": 0, "freed_bytes": 0, "remaining_bytes": 0, "kept": 0}
    if max_bytes <= 0 or not root.is_dir():
        return outcome
    entries: list[tuple[float, int, Path]] = []
    total = 0
    for parent, _dirs, files in os.walk(root, followlinks=False):
        for name in files:
            if not name.endswith(".json") or name.startswith(".tmp-"):
                continue
            path = Path(parent) / name
            if path.is_symlink():
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            entries.append((stat.st_mtime, stat.st_size, path))
            total += stat.st_size
    outcome["kept"] = len(entries)
    outcome["remaining_bytes"] = total
    if total <= max_bytes:
        return outcome
    entries.sort(key=lambda item: item[0])
    for _mtime, size, path in entries:
        if total <= max_bytes:
            break
        try:
            path.unlink()
        except OSError:
            continue
        total -= size
        outcome["evicted"] += 1
        outcome["freed_bytes"] += size
        outcome["kept"] -= 1
    outcome["remaining_bytes"] = total
    return outcome


class ParseCache:
    """命名空间隔离的解析缓存；一个键一个文件，两级前缀分片避免单目录过大。

    ``namespace`` 让同类载荷彼此隔离（通用结构解析 / Java 专用解析），
    它同时进键与目录，前者防碰撞、后者便于人工检查与整体清理。
    """

    def __init__(self, directory: str | Path, namespace: str = STRUCTURAL_NAMESPACE):
        self.directory = Path(directory)
        self.namespace = namespace
        self.root = self.directory / namespace
        self.hits = 0
        self.misses = 0
        self.writes = 0
        self.corrupt = 0
        self.skipped = 0

    def path_for(self, *parts: str) -> Path:
        """载荷的落盘路径；同时用于诊断与淘汰相关测试。"""
        key = cache_key(self.namespace, *parts)
        return self.root / key[:2] / f"{key}.json"

    def get(self, *parts: str) -> Any | None:
        """按键取载荷；未命中返回 ``None``。``None`` 只表示未命中——不缓存 ``None``。

        命中时刷新文件时间戳，使 :func:`enforce_budget` 的淘汰顺序反映**最近使用**
        而非**最近解析**：长期未变的文件恰恰是最应该保留的条目，若按解析时间淘汰
        会被最先删掉。刷新只是 ``utime``，不重写载荷。
        """
        target = self.path_for(*parts)
        try:
            raw = target.read_text(encoding="utf-8")
        except OSError:
            self.misses += 1
            return None
        try:
            entry = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            self.corrupt += 1
            self.misses += 1
            return None
        if not isinstance(entry, dict) or entry.get("schema") != CACHE_SCHEMA or "value" not in entry:
            self.corrupt += 1
            self.misses += 1
            return None
        try:
            os.utime(target, None)
        except OSError:
            pass
        self.hits += 1
        return entry["value"]

    def put(self, *parts: str, value: Any) -> bool:
        """写载荷。先落临时文件再 ``os.replace`` 原子替换——读者看不到半个文件。

        同一键的并发写内容必然相同（值只由键决定），因此无需加锁。
        载荷不可 JSON 序列化或磁盘不可写时返回 ``False`` 并跳过，不影响本次索引。
        """
        try:
            payload = json.dumps({"schema": CACHE_SCHEMA, "value": value}, ensure_ascii=False)
        except (TypeError, ValueError):
            self.skipped += 1
            return False
        target = self.path_for(*parts)
        temp = ""
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=str(target.parent), prefix=".tmp-", suffix=".json", delete=False
            ) as handle:
                handle.write(payload)
                temp = handle.name
            os.replace(temp, target)
        except OSError:
            if temp:
                try:
                    os.unlink(temp)
                except OSError:
                    pass
            self.skipped += 1
            return False
        self.writes += 1
        return True

    def snapshot(self) -> dict[str, Any]:
        """本进程内的命中/未命中计数，供任务详情与诊断复用。

        池化调用时计数留在各 worker 进程内，因此该快照只保证「本进程所见」。
        """
        return {"namespace": self.namespace, "directory": str(self.root), "schema": CACHE_SCHEMA,
                "hits": self.hits, "misses": self.misses, "writes": self.writes,
                "corrupt": self.corrupt, "skipped": self.skipped}


def encode_structural(result: StructuralParseResult) -> dict[str, Any]:
    """把结构性解析结果编成 JSON 载荷。字段与 dataclass 一一对应，不丢也不改名。"""

    def span(item: SymbolSpan) -> dict[str, Any]:
        return {"name": item.name, "qualified_name": item.qualified_name, "line": item.line,
                "end_line": item.end_line, "parent_qualified_name": item.parent_qualified_name,
                "kind": item.kind}

    def call(item: CallSite) -> dict[str, Any]:
        return {"caller_qualified_name": item.caller_qualified_name, "callee_text": item.callee_text,
                "line": item.line, "receiver_text": item.receiver_text}

    return {"language": result.language, "module": result.module, "imports": list(result.imports),
            "classes": [span(item) for item in result.classes],
            "functions": [span(item) for item in result.functions],
            "calls": [call(item) for item in result.calls], "constants": dict(result.constants),
            "raw": result.raw}


def decode_structural(payload: dict[str, Any]) -> StructuralParseResult:
    """``encode_structural`` 的逆操作；解码结果与原始 dataclass 逐值相等。"""
    return StructuralParseResult(
        language=str(payload.get("language", "")),
        module=payload.get("module"),
        imports=list(payload.get("imports") or []),
        classes=[SymbolSpan(**item) for item in payload.get("classes") or []],
        functions=[SymbolSpan(**item) for item in payload.get("functions") or []],
        calls=[CallSite(**item) for item in payload.get("calls") or []],
        constants=dict(payload.get("constants") or {}),
        raw=dict(payload.get("raw") or {}),
    )


__all__: Sequence[str] = (
    "BUDGET_ENV",
    "CACHE_SCHEMA",
    "DEFAULT_MAX_BYTES",
    "JAVA_NAMESPACE",
    "STRUCTURAL_NAMESPACE",
    "ParseCache",
    "cache_key",
    "configured_budget_bytes",
    "decode_structural",
    "encode_structural",
    "enforce_budget",
)
