"""Ollama/OpenAI-compatible 批量嵌入；未配置时仅关键词，无伪向量。

一轮索引里向量化是唯一随**模型延迟**线性增长的阶段（实测 9,459 块 / 592 批），
因此这里做两件互相独立的事，收益来源也不同（见
`docs/benchmarks/V5_EMBEDDING_STAGE_BASELINE.md`）：

- **内容寻址缓存**（``embed_many(cache=...)``）：热跑命中即不发请求，省的是**请求数**；
- **保序并发**（``embed_many(concurrency=...)``）：冷跑把批摊开到多个连接，省的是**墙钟**。

两者都必须保住产物的逐值相等：``Executor.map`` 保序，命中与未命中返回同一形状的
向量，因此「并发 + 缓存」路径与「串行逐批」路径的结果可以直接深度比较。
"""
import hashlib
import json
import math
import os
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from typing import Any
from urllib.parse import urlparse

import httpx

from memory_center.core.foundation.catalog import CatalogError

# 单次请求的最大文本条数。批越大往返越少，但单个请求失败的影响面也越大；
# 取 16 与原实现一致，可用 MEMORY_CENTER_EMBEDDING_BATCH 覆盖。
DEFAULT_BATCH_SIZE = 16

# 并发请求数。嵌入是**远程 HTTP**：httpx 等待响应时释放 GIL，所以线程池有效——
# 与 tree-sitter 解析（Python 绑定不释放 GIL）不同，那边只能用进程池。
DEFAULT_CONCURRENCY = 8
MAX_CONCURRENCY = 32

BATCH_ENV = "MEMORY_CENTER_EMBEDDING_BATCH"
CONCURRENCY_ENV = "MEMORY_CENTER_EMBEDDING_CONCURRENCY"


def _configured_int(env: Mapping[str, str] | None, name: str, default: int, low: int, high: int) -> int:
    """读一个夹在 ``[low, high]`` 的整型环境变量；缺失或非法一律退回 ``default``。"""
    source = os.environ if env is None else env
    raw = str(source.get(name, "") or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(low, min(value, high))


def configured_batch_size(env: Mapping[str, str] | None = None) -> int:
    """单次请求的文本条数，夹在 1–256。"""
    return _configured_int(env, BATCH_ENV, DEFAULT_BATCH_SIZE, 1, 256)


def configured_concurrency(env: Mapping[str, str] | None = None) -> int:
    """并发请求数，1 表示就地串行，上限 32。

    并发只改变「同时有多少请求在途」，不改变产物——``Executor.map`` 保序，
    返回的向量与输入文本一一对应。
    """
    return _configured_int(env, CONCURRENCY_ENV, DEFAULT_CONCURRENCY, 1, MAX_CONCURRENCY)


class EmbeddingCancelled(Exception):
    """调用方要求中止嵌入（索引已被取消）。

    与模型故障区分开：取消是**预期**的控制流，索引层直接返回、不写 job 失败；
    模型故障仍以 ``CatalogError`` 上抛，由索引层保留上一代索引。
    """


class Embedder:
    def __init__(self, settings, client: Any = None):
        self.settings = settings
        self.enabled = bool(settings.get('url') and settings.get('model'))
        self.profile = hashlib.sha256(json.dumps({k: settings.get(k) for k in ['url', 'model', 'protocol', 'dimensions']}, sort_keys=True).encode()).hexdigest()[:24] if self.enabled else ''
        self.dimensions = int(settings.get('dimensions', 1024) or 1024)
        # 调用方注入的连接：索引路径传一个长生命周期 client 进来复用 keep-alive，
        # 验证与检索路径不传，走 :meth:`_connection` 的自建分支。
        self._client = client

    @staticmethod
    def validate(settings):
        if bool(settings.get('url')) != bool(settings.get('model')):
            raise CatalogError('MODEL_INVALID', '模型地址和名称需同时填写或同时留空')
        if settings.get('url'):
            try:
                parsed = urlparse(settings['url'])
                _ = parsed.port
            except ValueError as exc:
                raise CatalogError('MODEL_INVALID', '模型地址或端口无效') from exc
            if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password:
                raise CatalogError('MODEL_INVALID', '模型地址需为无内嵌凭据的 HTTP/HTTPS 地址')
        if settings.get('protocol', 'ollama') not in {'ollama', 'openai'}:
            raise CatalogError('MODEL_INVALID', '模型协议不受支持')
        if not 1 <= settings.get('dimensions', 1024) <= 4096:
            raise CatalogError('MODEL_INVALID', '向量维度需介于 1–4096')
        return settings

    @contextmanager
    def _connection(self):
        """请求连接：调用方注入时复用，否则就地建一个用完即关。

        索引路径必须注入：一遍索引有几百批，若每批新建 ``httpx.Client``，
        连接握手成本会乘上批数（基线实测冷跑因此慢 8%）。验证与检索都是单次
        请求，自建分支的开销可忽略，也避免把长连接生命周期带进这两个短路径。
        """
        if self._client is not None:
            yield self._client
        else:
            with httpx.Client(timeout=60, follow_redirects=False, trust_env=False) as client:
                yield client

    def _request(self, client, batch) -> list[list[float]]:
        """一次请求取回一批向量；数量或维度不合法即抛 ``EMBEDDING_INVALID``。"""
        settings = self.settings
        endpoint = '/api/embed' if settings.get('protocol', 'ollama') == 'ollama' else '/embeddings'
        headers = {}
        key = os.environ.get('MEMORY_CENTER_MODEL_API_KEY', '')
        if key:
            headers['Authorization'] = 'Bearer ' + key
        response = client.post(settings['url'].rstrip('/') + endpoint,
                               json={'model': settings['model'], 'input': list(batch)}, headers=headers)
        response.raise_for_status()
        payload = response.json()
        vectors = payload.get('embeddings') if endpoint == '/api/embed' else [
            item['embedding'] for item in sorted(payload['data'], key=lambda item: item['index'])]
        if not isinstance(vectors, list) or len(vectors) != len(batch):
            raise CatalogError('EMBEDDING_INVALID', '模型返回数量不匹配')
        for vector in vectors:
            if len(vector) != self.dimensions or any(not isinstance(v, (float, int)) or isinstance(v, bool) or not math.isfinite(v) for v in vector):
                raise CatalogError('EMBEDDING_INVALID', '模型维度或向量数值无效')
        return vectors

    @staticmethod
    def _translate(action):
        """把传输层异常统一成 ``MODEL_CONNECTION_FAILED``；``CatalogError`` 原样上抛。

        ``EmbeddingCancelled`` 不在捕获列表里，故取消语义不受影响。
        """
        try:
            return action()
        except CatalogError:
            raise
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise CatalogError('MODEL_CONNECTION_FAILED', '模型连接或响应无效，请检查服务、协议与模型配置') from exc

    def _embed(self, texts):
        if not self.enabled:
            return [[] for _ in texts]
        width = configured_batch_size()
        results = []
        with self._connection() as client:
            for offset in range(0, len(texts), width):
                results.extend(self._request(client, texts[offset:offset + width]))
        return results

    def embed(self, texts):
        """单次批量嵌入，无缓存、无并发；供模型连接验证与查询向量化使用。

        这两条路径**刻意不接缓存**：验证要反映「此刻服务是否可用」，检索要反映
        「此刻这条查询」，命中一个跨代际的条目都会掩盖真实状态。
        """
        return self._translate(lambda: self._embed(texts))

    def embed_many(self, texts, *, cache: Any = None, concurrency: int = 1,
                   batch_size: int | None = None,
                   should_stop: Callable[[], bool] | None = None,
                   on_batch: Callable[[int], None] | None = None) -> list[list[float]]:
        """批量向量化：内容寻址缓存 + 保序并发；返回与 ``texts`` 等长的向量列表。

        返回顺序与 ``texts`` 严格一致（``Executor.map`` 保序），调用方可以直接与输入
        ``zip``。四条语义：

        - **缓存只影响速度**：命中与未命中的向量逐值相等；``cache=None`` 时完全不读写。
        - **取消是「尽快停下」**：``should_stop`` 在每批开始前求值，为真即抛
          :class:`EmbeddingCancelled`。已被线程池接走的批次仍会跑完（Python 3.11 的
          ``map`` 一次性提交全部任务），但结果不会再写缓存、也不会进入返回值。
        - **模型故障照常上抛**：``CatalogError`` 不在此吞掉，由索引层保留上一代索引。
        - **缓存写入与进度回调都只在主线程发生**：既避免多线程写同一键，也让进度
          计数天然有序。
        """
        if not self.enabled:
            return [[] for _ in texts]
        total = len(texts)
        if total == 0:
            return []
        vectors: list[list[float] | None] = [None] * total
        digests = [hashlib.sha256(text.encode('utf-8')).hexdigest() for text in texts]
        pending: list[int] = []
        if cache is None:
            pending = list(range(total))
        else:
            for index, digest in enumerate(digests):
                hit = cache.get(self.profile, digest, self.dimensions)
                if hit is None:
                    pending.append(index)
                else:
                    vectors[index] = hit
        cached = total - len(pending)
        if on_batch is not None and cached:
            # 命中的部分也计入进度，否则进度会停在缓存省下的那一段上。
            on_batch(cached)
        if not pending:
            return [vector if vector is not None else [] for vector in vectors]

        width = configured_batch_size() if batch_size is None else max(1, int(batch_size))
        batches = [pending[offset:offset + width] for offset in range(0, len(pending), width)]

        def guard() -> None:
            if should_stop is not None and should_stop():
                raise EmbeddingCancelled()

        def consume(batch: list[int], obtained: list[list[float]]) -> None:
            for index, vector in zip(batch, obtained, strict=True):
                vectors[index] = vector
                if cache is not None:
                    cache.put(self.profile, digests[index], vector)
            if on_batch is not None:
                on_batch(len(batch))

        workers = max(1, min(int(concurrency), MAX_CONCURRENCY))

        def run() -> None:
            with self._connection() as client:
                if workers <= 1 or len(batches) <= 1:
                    for batch in batches:
                        guard()
                        consume(batch, self._request(client, [texts[index] for index in batch]))
                    return

                def fetch(batch: list[int]):
                    guard()
                    return batch, self._request(client, [texts[index] for index in batch])

                with ThreadPoolExecutor(max_workers=workers, thread_name_prefix='embed') as pool:
                    for batch, obtained in pool.map(fetch, batches):
                        consume(batch, obtained)

        self._translate(run)
        return [vector if vector is not None else [] for vector in vectors]


__all__: Sequence[str] = (
    "BATCH_ENV",
    "CONCURRENCY_ENV",
    "DEFAULT_BATCH_SIZE",
    "DEFAULT_CONCURRENCY",
    "MAX_CONCURRENCY",
    "Embedder",
    "EmbeddingCancelled",
    "configured_batch_size",
    "configured_concurrency",
)
