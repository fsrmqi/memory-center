"""SQLite 向量扫描的可选预算、完整范围与候选可见性。"""
import json

import pytest

from memory_center.core.foundation.catalog import CatalogError
from memory_center.platform.embeddings import Embedder
from memory_center.platform.retrieval import sqlite_vector_limit
from tests.service.test_platform import service  # noqa: F401


def test_streamed_vectors_beyond_default_budget(service, monkeypatch):
    _, _, platform, spaces = service
    if platform.store.db.url:
        pytest.skip('SQLite 流式扫描专属验收')
    a = spaces[0]['workspace_id']
    settings = {'url': 'http://127.0.0.1:11434', 'model': 'fixture', 'protocol': 'ollama', 'dimensions': 2}
    platform.store.create('model', settings)
    profile = Embedder(settings).profile
    platform.store.create('index', {'id': a, 'workspace_id': a, 'generation': 'fixture',
                                    'config_version': 1, 'embedding_profile': profile, 'chunk_count': 6002})
    with platform.store.db.connection(True) as connection:
        connection.executemany('INSERT INTO chunks VALUES(?,?,?,?,?,?,?,?)', [
            (f'chunk_{i:06}', a, 'fixture', 'fixture', 'fixture', json.dumps({'kind': 'code'}), profile,
             '[0,1]' if i == 6001 else '[1,0]') for i in range(6002)])
        connection.execute('INSERT INTO chunks VALUES(?,?,?,?,?,?,?,?)',
                           ('private', a, 'fixture', 'private', 'hidden memory', json.dumps({'kind': 'memory'}), profile, '[0,1]'))
    monkeypatch.setattr(Embedder, 'embed', lambda self, values: [[0.0, 1.0]])
    monkeypatch.delenv('MEMORY_CENTER_SQLITE_VECTOR_SCAN_LIMIT', raising=False)
    with pytest.raises(CatalogError) as exc:
        platform.retrieval.search(spaces[0], platform.administrator(), 'fixture', 'vector')
    assert exc.value.code == 'VECTOR_BUDGET'
    monkeypatch.setenv('MEMORY_CENTER_SQLITE_VECTOR_SCAN_LIMIT', '0')
    result = platform.retrieval.search(spaces[0], platform.administrator(), 'fixture', 'vector')
    assert result['items'][0]['chunk_id'] == 'chunk_006001'
    assert result['items'][1]['chunk_id'] == 'chunk_000000'  # 同分排序保持确定性。
    assert 'private' not in [item['chunk_id'] for item in result['items']]
    monkeypatch.setenv('MEMORY_CENTER_SQLITE_VECTOR_SCAN_LIMIT', '7000')
    assert platform.retrieval.search(spaces[0], platform.administrator(), 'fixture', 'vector')['state'] == 'FOUND'


@pytest.mark.parametrize('value', ['-1', 'wrong', '0.5'])
def test_invalid_scan_budget(value, monkeypatch):
    monkeypatch.setenv('MEMORY_CENTER_SQLITE_VECTOR_SCAN_LIMIT', value)
    with pytest.raises(CatalogError) as exc:
        sqlite_vector_limit()
    assert exc.value.code == 'VECTOR_CONFIG_INVALID'
