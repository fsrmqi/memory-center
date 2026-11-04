"""嵌入批量路径：保序并发、连接复用、内容寻址缓存与取消语义。

用一个可控的本地 mock 端点量产物，不依赖真实模型服务。核心不变量：
**并发 + 缓存与串行逐批返回逐值相等的结果**——缓存与并发只该改变速度。
另有一条现状缺陷的对照：``Embedder.embed()`` 每次调用自建 ``httpx.Client``，
所以「一批一次调用」会开一条新连接；索引路径注入 client 后整轮只开一条。
"""
import hashlib
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from memory_center.core.foundation.catalog import CatalogError
from memory_center.platform.embedding_cache import EmbeddingCache
from memory_center.platform.embeddings import (
    BATCH_ENV,
    CONCURRENCY_ENV,
    MAX_CONCURRENCY,
    Embedder,
    EmbeddingCancelled,
    configured_batch_size,
    configured_concurrency,
)

DIMENSIONS = 8


def vector_for(text):
    """纯函数：同一文本在串行与并发两次运行里必须得到同一向量。"""
    seed = int(hashlib.sha256(text.encode()).hexdigest()[:8], 16)
    return [float((seed >> (index % 32)) & 0xFF) for index in range(DIMENSIONS)]


class _Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def setup(self):
        super().setup()
        with self.server.state['lock']:
            self.server.state['connections'] += 1

    def do_POST(self):
        state = self.server.state
        length = int(self.headers.get('Content-Length', 0) or 0)
        raw = self.rfile.read(length) if length else b''
        with state['lock']:
            state['in_flight'] += 1
            state['peak'] = max(state['peak'], state['in_flight'])
        try:
            try:
                body = json.loads(raw or b'{}')
            except json.JSONDecodeError:
                body = {}
            texts = list(body.get('input') or [])
            with state['lock']:
                state['requests'] += 1
                state['texts'] += len(texts)
            if state['delay']:
                time.sleep(state['delay'])
            mode = state['mode']
            if mode == 'http_error':
                self._reply(500, {'error': 'boom'})
                return
            if mode == 'count_mismatch':
                self._reply(200, {'embeddings': []})
                return
            if mode == 'dimension_mismatch':
                self._reply(200, {'embeddings': [[0.0]] * len(texts)})
                return
            if mode == 'integer_components':
                # 真实模型会把恰好为整数的分量序列化成 JSON 整数（`0` 而非 `0.0`），
                # json.loads 于是给出 int——这正是「缓存改变产物」那个缺陷的触发条件。
                self._reply(200, {'embeddings': [[0, 1, 2, 3, 4, 5, 6, 7] for _ in texts]})
                return
            self._reply(200, {'embeddings': [vector_for(text) for text in texts]})
        finally:
            with state['lock']:
                state['in_flight'] -= 1

    def _reply(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class _Server(ThreadingHTTPServer):
    # 默认 backlog 只有 5：并发请求建立连接时会被拒，表现为 ConnectionReset。
    daemon_threads = True
    request_queue_size = 128


@pytest.fixture
def embedding_server():
    state = {'requests': 0, 'texts': 0, 'connections': 0, 'in_flight': 0, 'peak': 0,
             'mode': 'ok', 'delay': 0.0, 'lock': threading.Lock()}
    server = _Server(('127.0.0.1', 0), _Handler)
    server.state = state
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state['settings'] = {'url': f'http://127.0.0.1:{server.server_address[1]}',
                         'model': 'test-embed', 'protocol': 'ollama', 'dimensions': DIMENSIONS}
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_parallel_result_equals_serial(embedding_server):
    texts = [f'text-{index}' for index in range(53)]
    settings = embedding_server['settings']
    serial = Embedder(settings).embed_many(texts, concurrency=1, batch_size=8)
    parallel = Embedder(settings).embed_many(texts, concurrency=6, batch_size=8)
    assert parallel == serial
    assert serial == [vector_for(text) for text in texts]


def test_order_follows_input_not_completion(embedding_server):
    """并发下先返回的批次可能后完成；保序是发布正确性的前提。"""
    texts = [f'chunk-{index}' for index in range(40)]
    embedding_server['delay'] = 0.01
    vectors = Embedder(embedding_server['settings']).embed_many(texts, concurrency=5, batch_size=4)
    assert vectors == [vector_for(text) for text in texts]


def test_cache_hit_avoids_requests(embedding_server, tmp_path):
    texts = [f'chunk-{index}' for index in range(20)]
    settings = embedding_server['settings']
    cache = EmbeddingCache(tmp_path)
    first = Embedder(settings).embed_many(texts, cache=cache, concurrency=4, batch_size=8)
    cold_requests = embedding_server['requests']
    assert cold_requests >= 1
    second = Embedder(settings).embed_many(texts, cache=cache, concurrency=4, batch_size=8)
    assert second == first
    assert embedding_server['requests'] == cold_requests     # 热跑零请求
    assert cache.snapshot()['hits'] == len(texts)


def test_partial_hit_matches_full_recompute(embedding_server, tmp_path):
    """命中与未命中混合时，结果必须与全部重算一致——否则缓存会悄悄改变产物。"""
    texts = [f'chunk-{index}' for index in range(20)]
    settings = embedding_server['settings']
    cache = EmbeddingCache(tmp_path)
    full = Embedder(settings).embed_many(texts, concurrency=2, batch_size=8)
    Embedder(settings).embed_many(texts[:10], cache=cache, concurrency=2, batch_size=8)
    mixed = Embedder(settings).embed_many(texts, cache=cache, concurrency=4, batch_size=8)
    assert mixed == full


def test_model_change_invalidates_every_entry(embedding_server, tmp_path):
    texts = [f'chunk-{index}' for index in range(8)]
    cache = EmbeddingCache(tmp_path)
    settings = embedding_server['settings']
    Embedder(settings).embed_many(texts, cache=cache, concurrency=1, batch_size=8)
    Embedder(dict(settings, model='another-model')).embed_many(
        texts, cache=cache, concurrency=1, batch_size=8)
    # 换模型必须重新请求，绝不能把旧模型算出的向量喂回索引。
    assert embedding_server['requests'] == 2
    assert cache.snapshot()['hits'] == 0


def test_injected_client_reuses_one_connection(embedding_server):
    texts = [f'chunk-{index}' for index in range(32)]
    settings = embedding_server['settings']
    with httpx.Client(timeout=30, follow_redirects=False, trust_env=False) as client:
        Embedder(settings, client=client).embed_many(texts, concurrency=1, batch_size=8)
    assert embedding_server['requests'] == 4
    assert embedding_server['connections'] == 1     # 4 批共用一个 keep-alive 连接


def test_embed_without_injected_client_opens_a_connection_per_call(embedding_server):
    """对照：验证/检索走 self-built client，每批一次调用就是一条新连接。

    这正是索引路径必须注入 client 的原因——几百批会把握手成本乘上批数。
    """
    texts = [f'chunk-{index}' for index in range(24)]
    embedder = Embedder(embedding_server['settings'])
    for offset in range(0, len(texts), 8):
        embedder.embed(texts[offset:offset + 8])
    assert embedding_server['requests'] == 3
    assert embedding_server['connections'] == 3


def test_should_stop_raises_cancellation(embedding_server):
    texts = [f'chunk-{index}' for index in range(64)]
    calls = []

    def stop():
        calls.append(1)
        return len(calls) > 1        # 第二批开始前取消

    with pytest.raises(EmbeddingCancelled):
        Embedder(embedding_server['settings']).embed_many(
            texts, concurrency=1, batch_size=8, should_stop=stop)


def test_cancellation_before_first_batch_sends_no_request_and_writes_no_cache(embedding_server, tmp_path):
    texts = [f'chunk-{index}' for index in range(32)]
    cache = EmbeddingCache(tmp_path)
    with pytest.raises(EmbeddingCancelled):
        Embedder(embedding_server['settings']).embed_many(
            texts, cache=cache, concurrency=1, batch_size=8, should_stop=lambda: True)
    assert embedding_server['requests'] == 0
    assert cache.snapshot()['writes'] == 0


def test_http_error_becomes_model_connection_failed(embedding_server):
    embedding_server['mode'] = 'http_error'
    with pytest.raises(CatalogError) as info:
        Embedder(embedding_server['settings']).embed_many(['x'], concurrency=1)
    assert info.value.code == 'MODEL_HTTP_ERROR'


def test_count_mismatch_is_invalid(embedding_server):
    embedding_server['mode'] = 'count_mismatch'
    with pytest.raises(CatalogError) as info:
        Embedder(embedding_server['settings']).embed_many(['x'], concurrency=1)
    assert info.value.code == 'EMBEDDING_INVALID'


def test_dimension_mismatch_is_invalid(embedding_server):
    embedding_server['mode'] = 'dimension_mismatch'
    with pytest.raises(CatalogError) as info:
        Embedder(embedding_server['settings']).embed_many(['x'], concurrency=1)
    assert info.value.code == 'EMBEDDING_INVALID'


def test_disabled_embedder_returns_empty_vectors_without_requests(embedding_server):
    embedder = Embedder({})
    assert embedder.enabled is False
    assert embedder.embed_many(['a', 'b']) == [[], []]
    assert embedding_server['requests'] == 0


def test_on_batch_reports_every_chunk_once(embedding_server, tmp_path):
    texts = [f'chunk-{index}' for index in range(24)]
    settings = embedding_server['settings']
    cache = EmbeddingCache(tmp_path)
    Embedder(settings).embed_many(texts[:12], cache=cache, concurrency=2, batch_size=8)
    seen = []
    Embedder(settings).embed_many(texts, cache=cache, concurrency=2, batch_size=8, on_batch=seen.append)
    # 命中 12 条 + 新算 12 条：每块都只报一次，总数不重不漏。
    assert sum(seen) == len(texts)


def test_concurrency_actually_overlaps_requests(embedding_server):
    texts = [f'chunk-{index}' for index in range(32)]
    embedding_server['delay'] = 0.05
    Embedder(embedding_server['settings']).embed_many(texts, concurrency=4, batch_size=4)
    assert embedding_server['peak'] >= 2


def test_configured_batch_size_and_concurrency_are_clamped():
    assert configured_batch_size({}) == 16
    assert configured_batch_size({BATCH_ENV: '1'}) == 1
    assert configured_batch_size({BATCH_ENV: '0'}) == 1
    assert configured_batch_size({BATCH_ENV: 'nonsense'}) == 16
    assert configured_concurrency({}) == 8
    assert configured_concurrency({CONCURRENCY_ENV: '0'}) == 1
    assert configured_concurrency({CONCURRENCY_ENV: '999'}) == MAX_CONCURRENCY
    assert configured_concurrency({CONCURRENCY_ENV: 'nonsense'}) == 8


def test_integer_components_are_normalized_to_float(embedding_server):
    """整数型分量必须归一化成 float，否则两条路径产出不同类型。"""
    embedding_server['mode'] = 'integer_components'
    vectors = Embedder(embedding_server['settings']).embed_many(['x', 'y'], concurrency=1)
    assert all(isinstance(value, float) for vector in vectors for value in vector)
    assert vectors == [[0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]] * 2


def test_cache_hit_matches_miss_down_to_repr(embedding_server, tmp_path):
    """等价性门槛必须细到 ``repr``：``int`` 与 ``float`` 虽然 ``==`` 相等，却是不同的产出。

    回归用例：缓存把元素归一化成 ``float``，而请求路径曾原样保留 ``int``，
    于是「命中」与「未命中」返回形状不同——缓存在悄悄改变产物。
    """
    embedding_server['mode'] = 'integer_components'
    settings = embedding_server['settings']
    cache = EmbeddingCache(tmp_path)
    miss = Embedder(settings).embed_many(['x'], cache=cache, concurrency=1)
    cache.flush()
    requests_before = embedding_server['requests']
    hit = Embedder(settings).embed_many(['x'], cache=EmbeddingCache(tmp_path), concurrency=1)
    assert embedding_server['requests'] == requests_before     # 第二次确实是命中
    assert repr(hit) == repr(miss)
