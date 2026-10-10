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
3. **坏条目只退化为未命中**：截断、JSON 损坏、契约版本不符、向量长度或数值类型与
   当前配置不符，都按未命中处理并允许覆写；磁盘不可写时跳过写入。缓存故障绝不
   中止索引。

**为什么是分片而不是一条一个文件。** 实测本机「新建一个文件」是 4–15 ms 的**固定**
开销，与文件大小几乎无关（1 KiB 与 1.5 MiB 都是约 14.5 ms/文件）。9,459 条向量若
一条一个文件，单轮写缓存就要约 250 s；按 2 位哈希前缀聚成 256 个分片文件、整片
批量重写后降到约 1 s。分片数再小会让单片过大（整片解析变慢），再大则文件数回升，
故取 256。同一分片的写入合并到 :meth:`EmbeddingCache.flush` 一次落盘，一轮索引的
9,459 次 ``put`` 因此只产生 256 次文件写。
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

# 分片键前缀长度（十六进制字符），即 16 ** 2 = 256 个分片。
SHARD_CHARS = 2

# 向量缓存的默认字节上限。一个 768 维向量编码成 JSON 约 10 KiB，
# 1 GiB 约可容纳 10 万条；更大的工作区用 MEMORY_CENTER_EMBEDDING_CACHE_MB 放大。
DEFAULT_MAX_BYTES = 1024 * 1024 * 1024

# 预算上限，防止异常配置把预算推到不受控的量级。
MAX_BUDGET_BYTES = 8 * 1024 ** 3

# 预算开关：MEMORY_CENTER_EMBEDDING_CACHE_MB=0 关闭向量缓存，未设置时用默认值。
BUDGET_ENV = "MEMORY_CENTER_EMBEDDING_CACHE_MB"


def configured_budget_bytes(env: Mapping[str, str] | None = None) -> int:
    """向量缓存字节预算；0 表示关闭向量缓存。

    与解析缓存不同，这里**不做规模自适应**：向量体积由「块数 × 维度」决定，而块数
    只有在切块之后才知道，缓存对象却要在索引开始时就建好。默认值取 1 GiB，足以覆盖
    十万级块的工作区；确需更大时显式调 ``MEMORY_CENTER_EMBEDDING_CACHE_MB``。
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
    """分片的内容寻址向量缓存；一个分片一个文件，整片原子重写。

    读写线程安全，且**同一缓存目录只应有一个写者**——服务侧同一工作区的索引是串行
    的，故不需要跨进程锁。落盘采用「写临时文件 + ``os.replace``」，读者看不到半个
    分片；同一分片重复写入的条目必然相同（值只由键决定），因此并发读也安全。

    ``put`` 只改内存并标记分片为脏，真正落盘发生在 :meth:`flush`。这样一轮索引的
    上万次写入被合并成几百次文件写——见模块 docstring 里关于文件创建固定开销的说明。
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
        self._shards: dict[str, dict[str, list[float]]] = {}
        self._loaded: set[str] = set()
        self._dirty: set[str] = set()
        self._touched: set[str] = set()

    def key_for(self, profile: str, text_hash: str) -> tuple[str, str]:
        """返回 ``(内容寻址键, 分片名)``；分片名是键的前缀，便于人工核对。"""
        key = cache_key(self.namespace, str(profile), str(text_hash))
        return key, key[:SHARD_CHARS]

    def path_for(self, profile: str, text_hash: str) -> Path:
        """条目所在的分片路径；多个键可能落在同一个分片里。"""
        _key, bucket = self.key_for(profile, text_hash)
        return self.root / bucket / f"{bucket}.json"

    def _load(self, bucket: str) -> dict[str, list[float]]:
        """取分片内容；缺失、损坏或契约不符时返回空表（等价于整片未命中）。"""
        if bucket in self._loaded:
            return self._shards.get(bucket, {})
        self._loaded.add(bucket)
        entries: dict[str, list[float]] = {}
        self._shards[bucket] = entries
        try:
            raw = (self.root / bucket / f"{bucket}.json").read_text(encoding="utf-8")
        except UnicodeError:
            with self._lock:
                self.corrupt += 1
            return entries
        except OSError:
            return entries
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            with self._lock:
                self.corrupt += 1
            return entries
        if not isinstance(payload, dict) or payload.get("schema") != PAYLOAD_SCHEMA:
            with self._lock:
                self.corrupt += 1
            return entries
        values = payload.get("entries")
        if isinstance(values, dict):
            # 逐条过滤：单片里混进个别坏条目时，只丢那几条，不牵连同片的其余向量。
            for key, vector in values.items():
                if isinstance(vector, list) and self._numeric(vector):
                    entries[key] = vector
        return entries

    @staticmethod
    def _numeric(vector: list[Any]) -> bool:
        """向量元素必须是非布尔的有限实数——``bool`` 是 ``int`` 的子类，需显式排除。"""
        for item in vector:
            if isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item):
                return False
        return True

    def get(self, profile: str, text_hash: str, dimensions: int) -> list[float] | None:
        """按键取向量；未命中返回 ``None``。``None`` 只表示未命中——不缓存 ``None``。

        长度与 ``dimensions`` 不符的一律按未命中处理：这类条目多来自旧模型配置，
        放行会让维度不对的向量进入索引，检索时必然失败。
        """
        key, bucket = self.key_for(profile, text_hash)
        vector = self._load(bucket).get(key)
        if vector is None or len(vector) != int(dimensions):
            with self._lock:
                self.misses += 1
            return None
        # 命中只记账，时间戳留到 flush 统一刷新，避免上万次 utime 系统调用。
        self._touched.add(bucket)
        with self._lock:
            self.hits += 1
        return vector

    def put(self, profile: str, text_hash: str, vector: Sequence[float]) -> bool:
        """写入内存中的分片并标记为脏；落盘由 :meth:`flush` 完成。

        返回 ``False`` 只表示该向量无法编码（例如含非数值元素），此时不会污染缓存。
        """
        try:
            materialized = [float(item) for item in vector]
        except (TypeError, ValueError):
            with self._lock:
                self.skipped += 1
            return False
        key, bucket = self.key_for(profile, text_hash)
        self._load(bucket)[key] = materialized
        self._dirty.add(bucket)
        return True

    def flush(self) -> int:
        """把所有脏分片原子落盘，刷新命中过的时间戳，并释放分片内存。

        返回写出的分片数（不是条目数）。写完即释放内存：调用方（一轮索引）用完即弃，
        下次读取会重新从盘上装载，因此不会把整个工作区的向量常驻在进程里。
        """
        written = 0
        for bucket in sorted(self._dirty):
            entries = self._shards.get(bucket, {})
            try:
                payload = json.dumps({"schema": PAYLOAD_SCHEMA, "entries": entries}, ensure_ascii=False)
            except (TypeError, ValueError):
                with self._lock:
                    self.skipped += 1
                continue
            path = self.root / bucket / f"{bucket}.json"
            temp = ""
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(
                    "w", encoding="utf-8", dir=str(path.parent), prefix=".tmp-", suffix=".json", delete=False
                ) as handle:
                    handle.write(payload)
                    temp = handle.name
                os.replace(temp, path)
            except OSError:
                if temp:
                    try:
                        os.unlink(temp)
                    except OSError:
                        pass
                with self._lock:
                    self.skipped += 1
                continue
            written += 1
            with self._lock:
                self.writes += 1
        self._dirty.clear()
        # 命中过的分片刷新一次时间戳，使 enforce_budget 的淘汰顺序反映「最近使用」
        # 而非「最近写入」——长期未变的分片恰恰是最该保留的。
        for bucket in self._touched:
            try:
                os.utime(self.root / bucket / f"{bucket}.json", None)
            except OSError:
                pass
        self._touched.clear()
        self._shards.clear()
        self._loaded.clear()
        return written

    def shard_count(self) -> int:
        """已装载的分片数，供诊断与测试使用。"""
        return len(self._loaded)

    def snapshot(self) -> dict[str, Any]:
        """本进程内的命中/未命中/落盘计数，供任务详情与诊断复用。"""
        with self._lock:
            return {"namespace": self.namespace, "directory": str(self.root), "schema": PAYLOAD_SCHEMA,
                    "shard_chars": SHARD_CHARS, "hits": self.hits, "misses": self.misses,
                    "writes": self.writes, "corrupt": self.corrupt, "skipped": self.skipped,
                    "pending_shards": len(self._dirty)}


__all__: Sequence[str] = (
    "BUDGET_ENV",
    "DEFAULT_MAX_BYTES",
    "EMBEDDING_NAMESPACE",
    "MAX_BUDGET_BYTES",
    "PAYLOAD_SCHEMA",
    "SHARD_CHARS",
    "EmbeddingCache",
    "configured_budget_bytes",
    "enforce_budget",
)
