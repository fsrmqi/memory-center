"""解析缓存：内容寻址、键隔离、坏缓存降级、预算淘汰与冷热产物等价。

对应改动：``platform/parse_cache.py``（新增）、``platform/code_graph.py``（通用结构
解析接入）、``core/indexing/reindex.py``（Java 专用解析接入）、``platform/jobs.py``
（工作区级缓存目录装配）。

核心不变量：**缓存只影响速度，不影响产物**。因此最重要的断言是
「冷跑产物 == 热跑产物」，而不是缓存命中率。
"""
import os

import pytest

from memory_center.core.foundation.models import JavaSymbol, to_dict
from memory_center.core.indexing.language_registry import get_language_spec_for_extension
from memory_center.core.indexing.parse_result import CallSite, StructuralParseResult, SymbolSpan
from memory_center.platform import code_graph as code_graph_module
from memory_center.platform.code_graph import build_code_graph
from memory_center.platform.parse_cache import (
    CACHE_SCHEMA,
    JAVA_NAMESPACE,
    STRUCTURAL_NAMESPACE,
    ParseCache,
    cache_key,
    configured_budget_bytes,
    decode_structural,
    encode_structural,
    enforce_budget,
)
from memory_center.platform.work_pool import WorkPool
from memory_center.core.indexing.reindex import _decode_java_result, _parse_java_file

SOURCES = {
    'pkg/helpers.py': 'def assist():\n    return 1\n',
    'pkg/main.py': 'from .helpers import assist as aid\ndef python_entry():\n    return aid()\n',
    'web/helpers.ts': 'export const assist = () => 1;',
    'web/main.ts': 'import {assist as aid} from "./helpers"; export const ts_entry = () => aid();',
    'Entry.java': 'package demo; class Entry { void java_entry() { helper(); } void helper() {} }',
}

JAVA_SOURCE = """package demo.order;

@FeignClient(name = "user-service")
public interface UserClient {
    String find(Long id);
}
"""


@pytest.fixture(autouse=True)
def _fresh_child_parsers():
    """``_CHILD_PARSERS`` 是跨用例的模块级缓存，用例改动解析器后必须清掉。"""
    code_graph_module._CHILD_PARSERS.clear()
    yield
    code_graph_module._CHILD_PARSERS.clear()


def write_tree(root, sources=SOURCES):
    paths = []
    for relative, text in sources.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        paths.append(path)
    return paths


def parseable(paths):
    return [path for path in paths if get_language_spec_for_extension(path.suffix) is not None]


def cache_files(root):
    return sorted(path for path in root.rglob('*.json') if not path.name.startswith('.tmp-'))


# ── 缓存本体 ────────────────────────────────────────────────────────────────


def test_round_trip_and_miss(tmp_path):
    cache = ParseCache(tmp_path)
    assert cache.get('python', 'nope') is None
    assert cache.snapshot()['misses'] == 1
    assert cache.put('python', 'digest', value={'k': [1, 2]}) is True
    assert cache.get('python', 'digest') == {'k': [1, 2]}
    assert cache.snapshot()['hits'] == 1
    assert len(cache_files(tmp_path)) == 1


def test_key_isolates_namespace_language_and_identity():
    assert cache_key(STRUCTURAL_NAMESPACE, 'java', 'h') != cache_key(JAVA_NAMESPACE, 'java', 'h')
    assert cache_key(STRUCTURAL_NAMESPACE, 'java', 'h') != cache_key(STRUCTURAL_NAMESPACE, 'go', 'h')
    assert cache_key(STRUCTURAL_NAMESPACE, 'java', 'h') != cache_key(STRUCTURAL_NAMESPACE, 'java', 'h2')
    # Java 产物带 project/file，故文件身份必须进键。
    assert cache_key(JAVA_NAMESPACE, 'p1', 'a.java', 'h') != cache_key(JAVA_NAMESPACE, 'p2', 'a.java', 'h')


def test_namespaces_do_not_collide_on_disk(tmp_path):
    structural, java = ParseCache(tmp_path, STRUCTURAL_NAMESPACE), ParseCache(tmp_path, JAVA_NAMESPACE)
    structural.put('java', 'same', value={'kind': 'structural'})
    java.put('java', 'same', value={'kind': 'java'})
    assert structural.get('java', 'same') == {'kind': 'structural'}
    assert java.get('java', 'same') == {'kind': 'java'}


def test_corrupt_entry_degrades_to_miss_and_is_refilled(tmp_path):
    cache = ParseCache(tmp_path)
    cache.put('python', 'digest', value={'ok': True})
    target = cache_files(tmp_path)[0]
    target.write_text('{"schema": 1, "value": ', encoding='utf-8')
    assert cache.get('python', 'digest') is None
    assert cache.snapshot()['corrupt'] == 1
    assert cache.put('python', 'digest', value={'ok': True}) is True
    assert cache.get('python', 'digest') == {'ok': True}


def test_schema_mismatch_degrades_to_miss(tmp_path):
    cache = ParseCache(tmp_path)
    cache.put('python', 'digest', value={'ok': True})
    target = cache_files(tmp_path)[0]
    target.write_text(f'{{"schema": {CACHE_SCHEMA + 1}, "value": {{"ok": true}}}}', encoding='utf-8')
    assert cache.get('python', 'digest') is None
    assert cache.snapshot()['corrupt'] == 1


def test_unserializable_payload_is_skipped_not_raised(tmp_path):
    cache = ParseCache(tmp_path)
    assert cache.put('python', 'digest', value={'bad': {1, 2}}) is False
    assert cache.snapshot()['skipped'] == 1
    assert cache.snapshot()['writes'] == 0
    assert cache_files(tmp_path) == []


def test_read_only_directory_is_skipped_not_raised(tmp_path):
    cache = ParseCache(tmp_path / 'missing-but-unwritable')
    cache.root.mkdir(parents=True)
    cache.root.chmod(0o500)
    try:
        assert cache.put('python', 'digest', value={'ok': True}) is False
        assert cache.snapshot()['skipped'] == 1
    finally:
        cache.root.chmod(0o700)


def test_configured_budget_defaults_and_switch():
    assert configured_budget_bytes({}) == 512 * 1024 * 1024
    assert configured_budget_bytes({'MEMORY_CENTER_PARSE_CACHE_MB': '0'}) == 0
    assert configured_budget_bytes({'MEMORY_CENTER_PARSE_CACHE_MB': '8'}) == 8 * 1024 * 1024
    assert configured_budget_bytes({'MEMORY_CENTER_PARSE_CACHE_MB': 'junk'}) == 512 * 1024 * 1024


def test_enforce_budget_evicts_oldest_first(tmp_path):
    cache = ParseCache(tmp_path)
    for index in range(4):
        cache.put('python', f'digest-{index}', value={'blob': 'x' * 512})
    files = cache_files(tmp_path)
    assert len(files) == 4
    for index, path in enumerate(files):
        os.utime(path, (1_000 + index, 1_000 + index))
    size = sum(path.stat().st_size for path in files)
    outcome = enforce_budget(tmp_path, size - 1)
    assert outcome['evicted'] == 1
    assert outcome['kept'] == 3
    assert outcome['remaining_bytes'] <= size - 1
    assert not files[0].exists()
    assert all(path.exists() for path in files[1:])


def test_enforce_budget_is_noop_within_budget(tmp_path):
    cache = ParseCache(tmp_path)
    cache.put('python', 'digest', value={'ok': True})
    outcome = enforce_budget(tmp_path, 10 * 1024 * 1024)
    assert outcome['evicted'] == 0
    assert outcome['kept'] == 1
    assert outcome['freed_bytes'] == 0
    # 预算为 0 表示关闭缓存，不做任何清理。
    assert enforce_budget(tmp_path, 0)['evicted'] == 0


# ── 结构结果编解码 ──────────────────────────────────────────────────────────


def test_structural_codec_round_trips_every_field():
    original = StructuralParseResult(
        language='python', module='pkg',
        imports=['a', 'b'],
        classes=[SymbolSpan(name='C', qualified_name='pkg.C', line=1, end_line=9,
                            parent_qualified_name='', kind='class')],
        functions=[SymbolSpan(name='f', qualified_name='pkg.C.f', line=3, end_line=5,
                              parent_qualified_name='pkg.C', kind='method')],
        calls=[CallSite(caller_qualified_name='pkg.C.f', callee_text='self.g()', line=4, receiver_text='self')],
        constants={'K': 'v'},
        raw={'parse_status': 'parsed', 'syntax_errors': False, 'local_bindings': {'pkg.C.f': ['x']}},
    )
    assert decode_structural(encode_structural(original)) == original


# ── 通用结构解析：冷热等价与失效 ─────────────────────────────────────────────


def test_build_code_graph_warm_cache_equals_cold(tmp_path):
    paths = write_tree(tmp_path)
    cache = ParseCache(tmp_path / 'cache')
    cold = build_code_graph(tmp_path, paths, None, None, cache)
    assert cold['symbols']
    assert cache.snapshot()['hits'] == 0
    assert cache.snapshot()['writes'] == len(parseable(paths))

    warm = build_code_graph(tmp_path, paths, None, None, cache)
    assert warm == cold
    assert cache.snapshot()['hits'] == len(parseable(paths))


def test_build_code_graph_cache_matches_uncached_reference(tmp_path):
    paths = write_tree(tmp_path)
    reference = build_code_graph(tmp_path, paths, None)
    cache = ParseCache(tmp_path / 'cache')
    warm = build_code_graph(tmp_path, paths, None, None, cache)
    build_code_graph(tmp_path, paths, None, None, cache)
    assert warm == reference
    assert build_code_graph(tmp_path, paths, None, None, cache) == reference


def test_build_code_graph_pooled_with_cache_equals_serial(tmp_path):
    paths = write_tree(tmp_path)
    cache = ParseCache(tmp_path / 'cache')
    reference = build_code_graph(tmp_path, paths, None)
    with WorkPool(2, min_items=1) as pool:
        cold = build_code_graph(tmp_path, paths, None, pool, cache)
    assert cold == reference
    with WorkPool(2, min_items=1) as pool:
        warm = build_code_graph(tmp_path, paths, None, pool, cache)
    assert warm == reference


def test_content_change_invalidates_only_that_file(tmp_path):
    paths = write_tree(tmp_path)
    cache = ParseCache(tmp_path / 'cache')
    cold = build_code_graph(tmp_path, paths, None, None, cache)
    before_hits = cache.snapshot()['hits']

    (tmp_path / 'pkg' / 'helpers.py').write_text('def assist():\n    return 2\n', encoding='utf-8')
    changed = build_code_graph(tmp_path, paths, None, None, cache)
    assert changed != cold
    symbol = next(item for item in changed['symbols'] if item['path'] == 'pkg/helpers.py')
    reference = next(item for item in cold['symbols'] if item['path'] == 'pkg/helpers.py')
    assert symbol['hash'] != reference['hash']
    # 只有一个文件变了：其余文件仍然命中，只有它重新解析。
    assert cache.snapshot()['hits'] - before_hits == len(parseable(paths)) - 1


def test_unchanged_file_keeps_stable_hash_across_runs(tmp_path):
    """缓存命中时覆盖台账的 hash 仍取自当前文件内容，不会变成缓存摘要。"""
    paths = write_tree(tmp_path)
    cache = ParseCache(tmp_path / 'cache')
    cold = build_code_graph(tmp_path, paths, None, None, cache)
    warm = build_code_graph(tmp_path, paths, None, None, cache)
    assert warm['coverage'] == cold['coverage']


def test_unavailable_parser_is_not_cached(tmp_path, monkeypatch):
    """解析器不可用时不得落缓存，否则「缺绑定」会被固化成持久结果。"""

    class _Unavailable:
        def __init__(self, language_name):
            self.language_name = language_name

        @property
        def available(self):
            return False

        def parse(self, source, file_path=''):
            return StructuralParseResult(language=self.language_name)

    monkeypatch.setattr(code_graph_module, 'TreeSitterStructuralParser', _Unavailable)
    paths = write_tree(tmp_path)
    cache = ParseCache(tmp_path / 'cache')
    graph = build_code_graph(tmp_path, paths, None, None, cache)
    assert all(value['status'] == 'unavailable' for value in graph['coverage'].values())
    assert cache.snapshot()['writes'] == 0
    assert cache_files(tmp_path / 'cache') == []


# ── Java 专用解析：冷热等价与身份隔离 ───────────────────────────────────────


def test_java_parse_warm_cache_equals_cold(tmp_path):
    path = tmp_path / 'UserClient.java'
    path.write_text(JAVA_SOURCE, encoding='utf-8')
    cache = ParseCache(tmp_path / 'cache', JAVA_NAMESPACE)

    cold = _parse_java_file('order-service', 'UserClient.java', path, cache)
    assert cold['symbol']
    warm = _parse_java_file('order-service', 'UserClient.java', path, cache)
    assert warm == cold
    assert cache.snapshot()['hits'] == 1


def test_java_parse_without_cache_equals_with_cache(tmp_path):
    path = tmp_path / 'Entry.java'
    path.write_text('package demo; class Entry { void helper() {} }\n', encoding='utf-8')
    reference = _parse_java_file('svc', 'Entry.java', path, None)
    cache = ParseCache(tmp_path / 'cache', JAVA_NAMESPACE)
    assert _parse_java_file('svc', 'Entry.java', path, cache) == reference
    assert _parse_java_file('svc', 'Entry.java', path, cache) == reference


def test_java_pending_feign_is_rebuilt_from_cached_symbol():
    symbol = JavaSymbol(project='order', file='UserClient.java', package='demo.order',
                        interfaces=['UserClient'], annotations=['FeignClient'])
    payload = {'symbol': to_dict(symbol), 'apis': [], 'mq': [], 'feign': True}
    result = _decode_java_result(payload, 'order', 'UserClient.java', 'SOURCE')
    assert result['symbol'] == to_dict(symbol)
    # 延迟 Feign 解析需要的四元组必须与未命中路径逐值一致。
    assert result['pending_feign'] == ('order', 'UserClient.java', 'SOURCE', symbol)


def test_java_payload_without_symbol_returns_empty_shape():
    result = _decode_java_result({'symbol': None, 'apis': [], 'mq': [], 'feign': False}, 'p', 'f.java', '')
    assert result == {'symbol': None, 'apis': [], 'pending_feign': None, 'mq': []}


def test_java_cache_identity_separates_projects(tmp_path):
    """同一份源码分属两个项目时不得互相顶掉——产物里的 project/file 必须正确。"""
    path = tmp_path / 'Shared.java'
    path.write_text('package demo; class Shared { void run() {} }\n', encoding='utf-8')
    cache = ParseCache(tmp_path / 'cache', JAVA_NAMESPACE)
    first = _parse_java_file('alpha', 'alpha/Shared.java', path, cache)
    second = _parse_java_file('beta', 'beta/Shared.java', path, cache)
    assert first['symbol']['project'] == 'alpha'
    assert second['symbol']['project'] == 'beta'
    assert second['symbol']['file'] == 'beta/Shared.java'
    assert cache.snapshot()['hits'] == 0
