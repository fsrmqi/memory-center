"""项目空间统计的隔离、字节口径与文件异常验证。"""
import json
import os

import pytest

from memory_center.core.foundation.catalog import CatalogError
from memory_center.platform.storage_usage import workspace_storage
from tests.service.test_platform import service  # noqa: F401


def test_storage_files_vectors_and_scope(service):
    client, headers, platform, spaces = service
    a, b = [space['workspace_id'] for space in spaces]
    db = platform.store.db
    root = db.data_dir / 'workspaces' / a
    for name, content in {'generations/current/graph.json': b'graph', 'generations/old/index.db': b'old-index',
                          'parse-cache/parser.json': b'parsed', 'embedding-cache/vector.json': b'vector',
                          'generation.lock': b'lock'}.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    other = db.data_dir / 'workspaces' / b
    other.mkdir(parents=True, exist_ok=True)
    (other / 'private.txt').write_bytes(b'x' * 1000)
    (root / 'external').symlink_to(other, target_is_directory=True)
    platform.store.create('index', {'id': a, 'workspace_id': a, 'generation': 'current', 'config_version': 1})
    with db.connection(True) as connection:
        for wid in (a, b):
            connection.execute('INSERT INTO chunks(id,workspace_id,generation,source_id,content,metadata,profile,embedding) VALUES(?,?,?,?,?,?,?,?)',
                               (wid+'-chunk', wid, 'current', 'demo', '中文内容', '{}', 'test-profile', '[1,2]'))
            connection.execute('INSERT INTO chunk_terms VALUES(?,?,?,?,?)', (wid+'-chunk', wid, 'current', '中文', 1))
        if db.url:
            connection.execute("UPDATE chunks SET vector_value='[1,2]' WHERE workspace_id=?", (a,))
    response = client.get(f'/api/v1/workspaces/{a}/storage', headers=headers)
    assert response.status_code == 200, response.text
    usage = response.json()
    assert usage['workspace_id'] == a
    assert usage['partial'] and usage['files']['skipped_symlinks'] == 1
    assert usage['files']['total_bytes'] == 30
    assert usage['files']['current_generation_bytes'] == 5
    assert usage['files']['other_generations_bytes'] == 9
    assert usage['files']['embedding_cache_bytes'] == 6
    assert usage['database']['chunks']['count'] == 1
    assert usage['database']['chunks']['vector_count'] == 1
    assert usage['database']['chunks']['vector_json_bytes'] == 5
    expected = sum(len(value.encode()) for value in (a+'-chunk', a, 'current', 'demo', '中文内容', '{}', 'test-profile', '[1,2]'))
    assert usage['database']['chunks']['text_bytes'] == expected
    assert usage['database']['terms']['text_bytes'] == sum(len(value.encode()) for value in (a+'-chunk', a, 'current', '中文'))
    assert usage['accounted_bytes'] == 30 + usage['database']['payload_bytes']
    if not db.url:
        assert usage['database']['chunks']['native_vector_bytes'] == 0
        assert usage['shared_database']['physical_bytes'] > usage['accounted_bytes']
    else:
        assert usage['database']['chunks']['native_vector_bytes'] > 0
        assert usage['shared_database']['physical_bytes'] is None
    assert b not in json.dumps(usage)


def test_storage_empty_auth_and_validation(service):
    client, headers, platform, spaces = service
    a = spaces[0]['workspace_id']
    usage = client.get(f'/api/v1/workspaces/{a}/storage', headers=headers).json()
    assert usage['files']['total_bytes'] == 0
    assert usage['database']['chunks']['vector_count'] == 0
    assert not usage['partial']
    assert client.get(f'/api/v1/workspaces/{a}/storage').status_code == 401
    assert client.get('/api/v1/workspaces/invalid/storage', headers=headers).status_code == 422
    missing = client.get('/api/v1/workspaces/ws_'+'0'*32+'/storage', headers=headers)
    assert missing.status_code == 422
    assert missing.json()['error']['code'] == 'FORBIDDEN'
    with pytest.raises(CatalogError):
        workspace_storage(platform.store, '../other')


def test_storage_unreadable_is_partial(service, monkeypatch):
    _, _, platform, spaces = service
    a = spaces[0]['workspace_id']
    root = platform.store.db.data_dir / 'workspaces' / a
    root.mkdir(parents=True, exist_ok=True)
    blocked = root / 'parse-cache'
    blocked.mkdir()
    scan = os.scandir

    def denied(path):
        if path == blocked:
            raise PermissionError('fixture')
        return scan(path)

    monkeypatch.setattr(os, 'scandir', denied)
    usage = workspace_storage(platform.store, a)
    assert usage['partial'] and usage['files']['read_errors'] == 1
    assert usage['files']['total_bytes'] == 0


def test_storage_root_symlink_is_not_followed(service):
    _, _, platform, spaces = service
    a, b = [space['workspace_id'] for space in spaces]
    parent = platform.store.db.data_dir / 'workspaces'
    parent.mkdir(parents=True, exist_ok=True)
    (parent / b).mkdir()
    (parent / b / 'foreign').write_bytes(b'x' * 200)
    (parent / a).symlink_to(parent / b, target_is_directory=True)
    usage = workspace_storage(platform.store, a)
    assert usage['partial'] and usage['files']['total_bytes'] == 0
    assert usage['files']['skipped_symlinks'] == 1
