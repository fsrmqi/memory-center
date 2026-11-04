"""向量缓存：内容寻址、分片合并落盘、坏载荷降级、预算淘汰与往返逐值相等。

对应改动：``platform/embedding_cache.py``（新增，分片存储）、``platform/embeddings.py``
（``Embedder.embed_many`` 接入）、``platform/jobs.py``（工作区级缓存目录装配 + flush）。

核心不变量与解析缓存一致：**缓存只影响速度，不影响产物**。因此最关键的断言是
「命中返回的向量与重新写入的向量逐值相等」，而不是命中率。

另一条只有本模块有的不变量：**写入次数必须是分片数量级，而不是条目数量级**——
本机「新建一个文件」是毫秒级固定开销，一条一个文件会让热缓存反而比冷跑更慢。
"""
import json
import os

import pytest

from memory_center.platform.embedding_cache import (
    BUDGET_ENV,
    DEFAULT_MAX_BYTES,
    MAX_BUDGET_BYTES,
    PAYLOAD_SCHEMA,
    SHARD_CHARS,
    EmbeddingCache,
    configured_budget_bytes,
    enforce_budget,
)
from memory_center.platform.parse_cache import cache_key

SHARD_TOTAL = 16 ** SHARD_CHARS


def sibling_hash(cache, profile, shard, base='h'):
    """找一个与 ``shard`` 同分片的另一个键，用来验证「同片互不牵连」。"""
    for index in range(20000):
        candidate = f'{base}-{index}'
        if cache.key_for(profile, candidate)[1] == shard:
            return candidate
    raise AssertionError('找不到同分片的兄弟键')


def test_key_for_isolates_profile_and_text():
    cache = EmbeddingCache('/tmp/never-written')
    key_a, shard_a = cache.key_for('profile-a', 'hash-1')
    key_b, _ = cache.key_for('profile-b', 'hash-1')
    key_c, _ = cache.key_for('profile-a', 'hash-2')
    assert len({key_a, key_b, key_c}) == 3
    assert len(shard_a) == SHARD_CHARS and key_a.startswith(shard_a)


def test_key_reuses_the_shared_content_addressed_construction():
    """键材料与解析缓存同源，命名空间把两类载荷隔开。"""
    cache = EmbeddingCache('/tmp/never-written')
    key, shard = cache.key_for('profile-a', 'hash-1')
    assert key == cache_key('embedding', 'profile-a', 'hash-1')
    assert cache.path_for('profile-a', 'hash-1') == cache.root / shard / f'{shard}.json'


def test_roundtrip_is_exactly_equal(tmp_path):
    cache = EmbeddingCache(tmp_path)
    vector = [0.1, -2.5, 3.0, 1e-17, 12345.678, 0.0, -0.0]
    assert cache.put('p', 'h', vector) is True
    # JSON 经由 repr 往返精确；若换成 float32 二进制，这里会因丢精度而失败。
    assert cache.get('p', 'h', len(vector)) == vector


def test_flushed_entry_is_readable_by_a_fresh_instance(tmp_path):
    """内存只是写缓冲：跨进程/跨代际复用必须靠落盘。"""
    cache = EmbeddingCache(tmp_path)
    cache.put('p', 'h', [1.0, 2.0])
    assert cache.flush() == 1
    assert EmbeddingCache(tmp_path).get('p', 'h', 2) == [1.0, 2.0]


def test_flush_merges_many_puts_into_shard_sized_writes(tmp_path):
    """一轮上万次 put 必须合并成「分片数」次写，而不是「条目数」次写。"""
    cache = EmbeddingCache(tmp_path)
    for index in range(500):
        cache.put('p', f'h{index}', [float(index)])
    written = cache.flush()
    expected_shards = len({cache.key_for('p', f'h{index}')[1] for index in range(500)})
    assert written == expected_shards
    assert written <= SHARD_TOTAL
    assert written < 500


def test_flush_releases_shard_memory(tmp_path):
    cache = EmbeddingCache(tmp_path)
    for index in range(200):
        cache.put('p', f'h{index}', [float(index)])
    assert cache.shard_count() > 0
    cache.flush()
    assert cache.shard_count() == 0


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
    # 坏分片不能被钉死：覆写后必须恢复正常。
    assert cache.put('p', 'h', [1.0, 2.0, 3.0, 4.0]) is True
    assert cache.get('p', 'h', 4) == [1.0, 2.0, 3.0, 4.0]


def test_contract_version_mismatch_is_corrupt(tmp_path):
    """契约版本不符意味着编码方式变了，旧分片必须整体作废。"""
    cache = EmbeddingCache(tmp_path)
    target = cache.path_for('p', 'h')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({'schema': PAYLOAD_SCHEMA + 1, 'entries': {}}), encoding='utf-8')
    assert cache.get('p', 'h', 1) is None
    assert cache.snapshot()['corrupt'] == 1


@pytest.mark.parametrize('bad', [
    [1.0, 2.0],                          # 长度与当前维度不符
    [1.0, 'x', 3.0, 4.0],                # 非数值
    [1.0, True, 3.0, 4.0],               # bool 是 int 子类，必须被拒
    [1.0, float('inf'), 3.0, 4.0],       # 非有限
    [1.0, float('nan'), 3.0, 4.0],
    'not-a-list',
])
def test_bad_entry_is_dropped_without_poisoning_its_shard(tmp_path, bad):
    """单片里混进坏条目时只丢那几条；同片的其余向量必须照常命中。"""
    cache = EmbeddingCache(tmp_path)
    bad_hash = 'h'
    _key, shard = cache.key_for('p', bad_hash)
    good_hash = sibling_hash(cache, 'p', shard)
    good_key, _ = cache.key_for('p', good_hash)
    bad_key, _ = cache.key_for('p', bad_hash)
    target = cache.path_for('p', bad_hash)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({'schema': PAYLOAD_SCHEMA,
                                  'entries': {bad_key: bad, good_key: [1.0, 2.0, 3.0, 4.0]}}),
                      encoding='utf-8')
    assert cache.get('p', bad_hash, 4) is None
    assert cache.get('p', good_hash, 4) == [1.0, 2.0, 3.0, 4.0]


def test_hit_refreshes_shard_mtime_only_on_flush(tmp_path):
    """命中记账在内存，时间戳统一在 flush 时刷新——避免上万次 utime 系统调用。"""
    cache = EmbeddingCache(tmp_path)
    cache.put('p', 'h', [1.0])
    assert cache.flush() == 1
    target = cache.path_for('p', 'h')
    os.utime(target, (1000, 1000))
    assert cache.get('p', 'h', 1) == [1.0]
    assert target.stat().st_mtime == 1000        # flush 之前不碰盘
    assert cache.flush() == 0                     # 没有脏分片
    assert target.stat().st_mtime > 1000


def test_budget_eviction_drops_least_recently_used_shards(tmp_path):
    cache = EmbeddingCache(tmp_path)
    for index in range(6):
        cache.put('p', f'h{index}', [float(index)])
    cache.flush()
    shards = sorted({cache.path_for('p', f'h{index}') for index in range(6)})
    assert len(shards) >= 3
    for index, path in enumerate(shards):
        os.utime(path, (1000 + index, 1000 + index))
    budget = shards[0].stat().st_size
    outcome = enforce_budget(cache.root, budget)
    assert outcome['evicted'] >= 1
    assert outcome['remaining_bytes'] <= budget
    assert not shards[0].exists()                 # 最旧的分片先被淘汰


def test_budget_within_limit_evicts_nothing(tmp_path):
    cache = EmbeddingCache(tmp_path)
    cache.put('p', 'h', [1.0])
    cache.flush()
    outcome = enforce_budget(cache.root, DEFAULT_MAX_BYTES)
    assert outcome['evicted'] == 0 and outcome['kept'] == 1


def test_configured_budget_defaults_and_overrides():
    assert configured_budget_bytes({}) == DEFAULT_MAX_BYTES
    assert configured_budget_bytes({BUDGET_ENV: '256'}) == 256 * 1024 ** 2
    assert configured_budget_bytes({BUDGET_ENV: '0'}) == 0            # 0 表示关闭
    assert configured_budget_bytes({BUDGET_ENV: 'nonsense'}) == DEFAULT_MAX_BYTES
    assert configured_budget_bytes({BUDGET_ENV: '999999'}) == MAX_BUDGET_BYTES


def test_put_rejects_non_numeric_vector(tmp_path):
    cache = EmbeddingCache(tmp_path)
    assert cache.put('p', 'h', [object()]) is False
    assert cache.snapshot()['skipped'] == 1


def test_snapshot_counts_are_per_instance(tmp_path):
    cache = EmbeddingCache(tmp_path)
    cache.put('p', 'h', [1.0])
    cache.get('p', 'h', 1)
    cache.get('p', 'absent', 1)
    cache.flush()
    snapshot = cache.snapshot()
    assert snapshot['hits'] == 1 and snapshot['misses'] == 1 and snapshot['writes'] == 1
    assert snapshot['schema'] == PAYLOAD_SCHEMA and snapshot['shard_chars'] == SHARD_CHARS
