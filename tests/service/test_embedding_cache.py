"""向量缓存：内容寻址、键隔离、坏载荷降级、预算淘汰与往返逐值相等。

对应改动：``platform/embedding_cache.py``（新增）、``platform/embeddings.py``
（``Embedder.embed_many`` 接入）、``platform/jobs.py``（工作区级缓存目录装配）。

核心不变量与解析缓存一致：**缓存只影响速度，不影响产物**。因此最关键的断言是
「命中返回的向量与重新写入的向量逐值相等」，而不是命中率。
"""
import json
import os

import pytest

from memory_center.platform.embedding_cache import (
    BUDGET_ENV,
    DEFAULT_MAX_BYTES,
    MAX_BUDGET_BYTES,
    PAYLOAD_SCHEMA,
    EmbeddingCache,
    configured_budget_bytes,
    enforce_budget,
)
from memory_center.platform.parse_cache import cache_key


def test_key_isolates_profile_and_text():
    cache = EmbeddingCache('/tmp/never-written')
    assert cache.path_for('profile-a', 'hash-1') != cache.path_for('profile-b', 'hash-1')
    assert cache.path_for('profile-a', 'hash-1') != cache.path_for('profile-a', 'hash-2')


def test_path_uses_the_shared_content_addressed_key():
    """键材料与解析缓存同源，命名空间把两类载荷隔开，便于人工核对与整体清理。"""
    cache = EmbeddingCache('/tmp/never-written')
    expected = cache_key('embedding', 'profile-a', 'hash-1')
    assert cache.path_for('profile-a', 'hash-1').name == f"{expected}.json"


def test_roundtrip_is_exactly_equal(tmp_path):
    cache = EmbeddingCache(tmp_path)
    vector = [0.1, -2.5, 3.0, 1e-17, 12345.678, 0.0, -0.0]
    assert cache.put('p', 'h', vector) is True
    # JSON 经由 repr 往返精确；若换成 float32 二进制，这里会因丢精度而失败。
    assert cache.get('p', 'h', len(vector)) == vector


def test_missing_entry_is_a_miss(tmp_path):
    cache = EmbeddingCache(tmp_path)
    assert cache.get('p', 'absent', 4) is None
    assert cache.snapshot()['misses'] == 1


def test_corrupt_payload_falls_back_to_miss_and_can_be_overwritten(tmp_path):
    cache = EmbeddingCache(tmp_path)
    target = cache.path_for('p', 'h')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('{not json', encoding='utf-8')
    assert cache.get('p', 'h', 4) is None
    assert cache.snapshot()['corrupt'] == 1
    # 坏条目不能把键永久钉死：覆写后必须恢复正常。
    assert cache.put('p', 'h', [1.0, 2.0, 3.0, 4.0]) is True
    assert cache.get('p', 'h', 4) == [1.0, 2.0, 3.0, 4.0]


def test_contract_version_mismatch_is_corrupt(tmp_path):
    """契约版本不符意味着编码方式变了，旧载荷必须整体作废。"""
    cache = EmbeddingCache(tmp_path)
    target = cache.path_for('p', 'h')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({'schema': PAYLOAD_SCHEMA + 1, 'value': [1.0]}), encoding='utf-8')
    assert cache.get('p', 'h', 1) is None
    assert cache.snapshot()['corrupt'] == 1


@pytest.mark.parametrize('value', [
    [1.0, 2.0],                          # 长度与当前维度不符
    [1.0, 'x', 3.0, 4.0],                # 非数值
    [1.0, True, 3.0, 4.0],               # bool 是 int 子类，必须被拒
    [1.0, float('inf'), 3.0, 4.0],       # 非有限
    [1.0, float('nan'), 3.0, 4.0],
    'not-a-list',
])
def test_invalid_vector_shape_is_corrupt(tmp_path, value):
    """无效向量若放行，会在检索时变成维度校验失败——必须在读缓存时就拦下。"""
    cache = EmbeddingCache(tmp_path)
    target = cache.path_for('p', 'h')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({'schema': PAYLOAD_SCHEMA, 'value': value}), encoding='utf-8')
    assert cache.get('p', 'h', 4) is None
    assert cache.snapshot()['corrupt'] == 1


def test_hit_refreshes_mtime_so_eviction_tracks_recent_use(tmp_path):
    cache = EmbeddingCache(tmp_path)
    cache.put('p', 'old', [1.0])
    cache.put('p', 'recent', [2.0])
    old = cache.path_for('p', 'old')
    recent = cache.path_for('p', 'recent')
    os.utime(old, (1000, 1000))
    os.utime(recent, (2000, 2000))
    assert cache.get('p', 'old', 1) == [1.0]
    assert old.stat().st_mtime > 2000
    assert recent.stat().st_mtime == 2000


def test_budget_eviction_drops_least_recently_used(tmp_path):
    cache = EmbeddingCache(tmp_path)
    paths = []
    for index in range(4):
        cache.put('p', f'h{index}', [float(index)])
        paths.append(cache.path_for('p', f'h{index}'))
    for index, path in enumerate(paths):
        os.utime(path, (1000 + index, 1000 + index))
    outcome = enforce_budget(tmp_path, paths[0].stat().st_size)
    assert outcome['evicted'] == 3
    assert paths[3].exists()          # 最近使用过的那条保留
    assert not paths[0].exists()      # 最旧的先被淘汰


def test_budget_within_limit_evicts_nothing(tmp_path):
    cache = EmbeddingCache(tmp_path)
    cache.put('p', 'h', [1.0])
    outcome = enforce_budget(tmp_path, DEFAULT_MAX_BYTES)
    assert outcome['evicted'] == 0 and outcome['kept'] == 1


def test_configured_budget_defaults_and_overrides():
    assert configured_budget_bytes({}) == DEFAULT_MAX_BYTES
    assert configured_budget_bytes({BUDGET_ENV: '256'}) == 256 * 1024 ** 2
    assert configured_budget_bytes({BUDGET_ENV: '0'}) == 0            # 0 表示关闭
    assert configured_budget_bytes({BUDGET_ENV: 'nonsense'}) == DEFAULT_MAX_BYTES
    assert configured_budget_bytes({BUDGET_ENV: '999999'}) == MAX_BUDGET_BYTES


def test_put_skips_unserializable_value(tmp_path):
    cache = EmbeddingCache(tmp_path)
    assert cache.put('p', 'h', [object()]) is False
    assert cache.snapshot()['skipped'] == 1


def test_snapshot_counts_are_per_instance(tmp_path):
    cache = EmbeddingCache(tmp_path)
    cache.put('p', 'h', [1.0])
    cache.get('p', 'h', 1)
    cache.get('p', 'absent', 1)
    snapshot = cache.snapshot()
    assert snapshot['hits'] == 1 and snapshot['misses'] == 1 and snapshot['writes'] == 1
    assert snapshot['schema'] == PAYLOAD_SCHEMA
