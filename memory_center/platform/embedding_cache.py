"""内容寻址的向量（embedding）缓存。

依据 `docs/benchmarks/V5_EMBEDDING_STAGE_BASELINE.md`：向量化是**远程 HTTP**，
一遍索引里每条文本都要与模型往返一次，是索引墙钟里唯一随模型延迟线性增长的
阶段（实测 9,459 块 / 592 批）。本模块把「文本 → 向量」按内容缓存下来，让
「只改了几个文件的再次索引」不再重发其余文本——热跑请求数直接归零。

三条不变量，与 `parse_cache` 同构：

1. **内容寻址**：键 = sha256(契约版本 ‖ 命名空间 ‖ 模型指纹 ‖ 文本 sha256)。
   模型指纹（``url``/``model``/``protocol``/``dimensions`` 的哈希）进键，换模型或
   改维度必然整体未命中，不会把别的模型算出来的向量喂回索引。
2. **缓存不改变产物**：命中返回的向量与重新请求得到的结果**逐值相等**。载荷因此
   用 JSON 编码——Python 的 float 经由 ``repr`` 往返精确，二进制 float32 会丢精度，
   不能用来做等价性门槛（索引里同一个 chunk 的向量会随命中与否而变化）。
3. **坏缓存只退化为未命中**：截断、JSON 损坏、契约版本不符、向量长度或数值类型与
   当前配置不符，一律按未命中处理并允许覆写；目录不可写时跳过写入。缓存故障绝不
   中止索引。

与 `parse_cache` 共用 :func:`~memory_center.platform.parse_cache.cache_key` 与
:func:`~memory_center.platform.parse_cache.enforce_budget`：前者保证键的构造方式
一致，后者按「最近使用」淘汰。向量载荷同样以 ``.json`` 落盘，淘汰逻辑因此无需分支。
"""
from __future__ import annotations

import json
import math
import os
import tempfile
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from memory_center.platform.parse_cache import cache_key, enforce_budget

# 载荷结构与向量语义的契约版本。改动编码方式（例如换掉 JSON）、或任何会改变
# 「同一文本返回的向量」的实现时**必须**递增，否则旧载荷会被当成新结果复用。
PAYLOAD_SCHEMA = 1

EMBEDDING_NAMESPACE = "embedding"

# 向量缓存的默认字节上限。一个 1024 维向量编码成 JSON 约 20 KiB，
# 1 GiB 约可容纳 5 万条；更大的工作区用 MEMORY_CENTER_EMBEDDING_CACHE_MB 放大。
DEFAULT_MAX_BYTES = 1024 * 1024 * 1024

# 预算上限，防止异常配置把预算推到不受控的量级。
MAX_BUDGET_BYTES = 8 * 1024 ** 3

# 预算开关：MEMORY_CENTER_EMBEDDING_CACHE_MB=0 关闭向量缓存，未设置时用默认值。
BUDGET_ENV = "MEMORY_CENTER_EMBEDDING_CACHE_MB"


def configured_budget_bytes(env: Mapping[str, str] | None = None) -> int:
    """向量缓存字节预算；0 表示关闭向量缓存。

    与解析缓存不同，这里**不做规模自适应**：向量体积由「块数 × 维度」决定，而块数
    只有在切块之后才知道，缓存对象却要在索引开始时就建好。默认值取 1 GiB，足以覆盖
    万级块的工作区；确需更大时显式调 ``MEMORY_CENTER_EMBEDDING_CACHE_MB``。
    """
    source = os.environ if env is None else env
    raw = str(source.get(BUDGET_ENV, "") or "").strip()
    if not raw:
        return DEFAULT_MAX_BYTES
    try:
        megabytes = int(raw)
    except ValueError:
        return DEFAULT_MAX_BYTES
    return min(max(0, megabytes) * 1024 ** 2, MAX_BUDGET_BYTES)


class EmbeddingCache:
    """命名空间隔离的向量缓存；一个键一个文件，两级前缀分片避免单目录过大。

    读写线程安全：计数用锁保护，写入先落临时文件再 ``os.replace`` 原子替换，读者
    看不到半个文件。同一键的并发写内容必然相同（值只由键决定），因此无需互斥。
    """

    def __init__(self, directory: str | Path, namespace: str = EMBEDDING_NAMESPACE):
        self.directory = Path(directory)
        self.namespace = namespace
        self.root = self.directory / namespace
        self.hits = 0
        self.misses = 0
        self.writes = 0
        self.corrupt = 0
        self.skipped = 0
        self._lock = threading.Lock()

    def path_for(self, profile: str, text_hash: str) -> Path:
        """载荷的落盘路径；同时用于诊断与淘汰相关测试。"""
        key = cache_key(self.namespace, str(profile), str(text_hash))
        return self.root / key[:2] / f"{key}.json"

    def get(self, profile: str, text_hash: str, dimensions: int) -> list[float] | None:
        """按键取向量；未命中返回 ``None``。``None`` 只表示未命中——不缓存 ``None``。

        长度与 ``dimensions`` 不符、或元素不是有限数值，都按**坏载荷**处理：这类条目
        多来自旧模型或半写文件，若放行会让无效向量进入索引（检索时维度校验失败）。
        命中时刷新文件时间戳，使 :func:`~memory_center.platform.parse_cache.enforce_budget`
        的淘汰顺序反映**最近使用**而非**最近写入**。
        """
        target = self.path_for(profile, text_hash)
        try:
            raw = target.read_text(encoding="utf-8")
        except OSError:
            with self._lock:
                self.misses += 1
            return None
        try:
            entry = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            with self._lock:
                self.corrupt += 1
                self.misses += 1
            return None
        if not isinstance(entry, dict) or entry.get("schema") != PAYLOAD_SCHEMA:
            with self._lock:
                self.corrupt += 1
                self.misses += 1
            return None
        value = entry.get("value")
        if not isinstance(value, list) or len(value) != int(dimensions) or not self._numeric(value):
            with self._lock:
                self.corrupt += 1
                self.misses += 1
            return None
        try:
            os.utime(target, None)
        except OSError:
            pass
        with self._lock:
            self.hits += 1
        return value

    @staticmethod
    def _numeric(vector: list[Any]) -> bool:
        """向量元素必须是非布尔的有限实数——``bool`` 是 ``int`` 的子类，需显式排除。"""
        for item in vector:
            if isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item):
                return False
        return True

    def put(self, profile: str, text_hash: str, vector: Sequence[float]) -> bool:
        """写向量。载荷不可序列化或磁盘不可写时返回 ``False`` 并跳过，不影响本次索引。"""
        try:
            payload = json.dumps({"schema": PAYLOAD_SCHEMA, "value": list(vector)}, ensure_ascii=False)
        except (TypeError, ValueError):
            with self._lock:
                self.skipped += 1
            return False
        target = self.path_for(profile, text_hash)
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
            with self._lock:
                self.skipped += 1
            return False
        with self._lock:
            self.writes += 1
        return True

    def snapshot(self) -> dict[str, Any]:
        """本进程内的命中/未命中计数，供任务详情与诊断复用。"""
        with self._lock:
            return {"namespace": self.namespace, "directory": str(self.root), "schema": PAYLOAD_SCHEMA,
                    "hits": self.hits, "misses": self.misses, "writes": self.writes,
                    "corrupt": self.corrupt, "skipped": self.skipped}


__all__: Sequence[str] = (
    "BUDGET_ENV",
    "DEFAULT_MAX_BYTES",
    "EMBEDDING_NAMESPACE",
    "MAX_BUDGET_BYTES",
    "PAYLOAD_SCHEMA",
    "EmbeddingCache",
    "configured_budget_bytes",
    "enforce_budget",
)
