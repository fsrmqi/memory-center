"""项目向量范围：隔离、无模型运行、知识子集及发布修订门禁。"""
import json

import pytest

from memory_center.core.foundation.catalog import CatalogError
from memory_center.platform.embeddings import Embedder
from memory_center.platform.jobs import run_index
from memory_center.platform.project_embedding import ProjectEmbedding
from tests.service.test_platform import service  # noqa: F401


MODEL = {'url': 'http://127.0.0.1:1', 'model': 'fixture', 'protocol': 'ollama', 'dimensions': 2}


def settings(platform, workspace_id, mode):
    controller = ProjectEmbedding(platform)
    return controller.configure(workspace_id, mode, controller.settings(workspace_id)['revision'])


def index(platform, space, monkeypatch, mode, knowledge=False):
    wid = space['workspace_id']
    settings(platform, wid, mode)
    platform.store.create('model', MODEL)
    if knowledge:
        platform.store.create('wiki', {'workspace_id': wid, 'title': 'fixture note',
            'content': 'knowledge only marker', 'status': 'active', 'owner': 'admin'})
    job = platform.store.create('job', {'workspace_id': wid, 'owner': 'admin', 'status': 'running',
                                      'config_version': space['config_version']})
    seen = []
    def embed(self, values, **kwargs):
        seen.extend(values)
        return [[1.0, 0.0] for _ in values]
    monkeypatch.setattr(Embedder, 'embed_many', embed)
    run_index(platform.store.db.data_dir, platform.store.db.url, space, job['id'], file_workers=0)
    current = platform.store.get('job', job['id'])
    assert current['status'] == 'succeeded', current
    return platform.store.get('index', wid), seen


def test_project_settings_scope_revision_and_validation(service):
    client, headers, platform, spaces = service
    a, b = [w['workspace_id'] for w in spaces]
    path = f'/api/v1/workspaces/{a}/embedding-settings'
    assert client.get(path, headers=headers).json()['mode'] == 'inherit'
    value = client.put(path, headers=headers, json={'mode': 'off', 'revision': 0})
    assert value.status_code == 200
    assert ProjectEmbedding(platform).settings(b)['mode'] == 'inherit'
    assert client.put(path, headers=headers, json={'mode': 'all', 'revision': 0}).json()['error']['code'] == 'REVISION_CONFLICT'
    assert client.put(path, headers=headers, json={'mode': 'invalid', 'revision': 1}).status_code == 422
    assert client.get(path).status_code == 401


def test_disabled_index_keeps_graph_keyword_and_never_calls_model(service, monkeypatch):
    _, _, platform, spaces = service
    space = spaces[0]
    result, seen = index(platform, space, monkeypatch, 'off')
    assert not seen and result['embedding_mode'] == 'off' and result['embedding_profile'] == ''
    assert result['chunk_count'] > 0
    from pathlib import Path
    graph = json.loads((Path(result['workspace_file']).parent/'code-graph.json').read_text())
    symbol = next(s for s in graph['symbols'] if s['name'] == 'hello')
    assert platform.lookup(platform.administrator(), space['workspace_id'], symbol['id'], 'symbol')['state'] == 'FOUND'
    monkeypatch.setattr(Embedder, 'embed', lambda *args: pytest.fail('disabled query called embedding model'))
    hit = platform.lookup(platform.administrator(), space['workspace_id'], 'alpha', 'hybrid')
    assert hit['state'] == 'FOUND' and not hit['vector_enabled'] and not hit['vector_reindex_required']
    with pytest.raises(CatalogError) as exc:
        platform.lookup(platform.administrator(), space['workspace_id'], 'alpha', 'vector')
    assert exc.value.code == 'VECTOR_DISABLED'
    settings(platform, space['workspace_id'], 'all')
    assert platform.lookup(platform.administrator(), space['workspace_id'], 'alpha', 'hybrid')['vector_reindex_required']


def test_knowledge_only_vectors_and_expansion_requires_reindex(service, monkeypatch):
    _, _, platform, spaces = service
    space = spaces[0]
    result, seen = index(platform, space, monkeypatch, 'knowledge', True)
    assert seen == ['knowledge only marker'] and result['embedding_mode'] == 'knowledge'
    assert result['embedding_profile'] == Embedder(MODEL).profile
    with platform.store.db.connection() as db:
        rows = db.execute('SELECT metadata,profile,embedding FROM chunks WHERE workspace_id=?', (space['workspace_id'],)).fetchall()
    assert all(not r['profile'] and json.loads(r['embedding']) == [] for r in rows if json.loads(r['metadata'])['kind'] == 'code')
    monkeypatch.setattr(Embedder, 'embed', lambda *args: [[1.0, 0.0]])
    found = platform.lookup(platform.administrator(), space['workspace_id'], 'marker', 'vector')
    assert found['vector_enabled'] and all(i['source']['kind'] != 'code' for i in found['items'])
    settings(platform, space['workspace_id'], 'all')
    assert platform.lookup(platform.administrator(), space['workspace_id'], 'alpha', 'hybrid')['vector_reindex_required']


def test_change_during_embedding_preserves_previous_index(service, monkeypatch):
    _, _, platform, spaces = service
    space = spaces[0]
    previous, _ = index(platform, space, monkeypatch, 'off')
    settings(platform, space['workspace_id'], 'all')
    job = platform.store.create('job', {'workspace_id': space['workspace_id'], 'owner': 'admin', 'status': 'running',
                                      'config_version': space['config_version']})
    def change(self, values, **kwargs):
        settings(platform, space['workspace_id'], 'off')
        return [[1.0, 0.0] for _ in values]
    monkeypatch.setattr(Embedder, 'embed_many', change)
    run_index(platform.store.db.data_dir, platform.store.db.url, space, job['id'], file_workers=0)
    failed = platform.store.get('job', job['id'])
    assert failed['status'] == 'failed' and failed['error'] == 'EMBEDDING_SETTINGS_CHANGED'
    assert platform.store.get('index', space['workspace_id'])['generation'] == previous['generation']


def test_disabled_knowledge_refresh_skips_embedding(service, monkeypatch):
    _, _, platform, spaces = service
    space = spaces[0]
    index(platform, space, monkeypatch, 'off', True)
    monkeypatch.setattr(Embedder, 'embed_many', lambda *args, **kwargs: pytest.fail('refresh called disabled model'))
    task = platform.knowledge_tasks.enqueue_refresh(space['workspace_id'])
    platform.knowledge_tasks.run_refresh(task['id'])
    value = platform.store.get('knowledge_task', task['id'])
    assert value['status'] == 'succeeded', value
    assert platform.store.get('index', space['workspace_id'])['embedding_profile'] == ''


def test_knowledge_scope_filters_before_vector_budget_and_topk(service, monkeypatch):
    _, _, platform, spaces = service
    space = spaces[0]
    wid = space['workspace_id']
    platform.store.create('model', MODEL)
    note = platform.store.create('wiki', {'workspace_id': wid, 'title': 'note', 'content': 'note', 'status': 'active', 'owner': 'admin'})
    job = platform.store.create('job', {'workspace_id': wid, 'status': 'running'})
    profile = Embedder(MODEL).profile
    chunks = [{'id': f'code_{i}_{wid}', 'source_id': 'code', 'content': 'code', 'metadata': {'kind': 'code'},
               'profile': profile, 'embedding': [0.0, 1.0]} for i in range(202)]
    chunks.append({'id': 'note_'+wid, 'source_id': note['id'], 'content': 'note',
                   'metadata': {'kind': 'wiki', 'source_revision': note['revision']}, 'profile': profile, 'embedding': [1.0, 0.0]})
    platform.store.publish(wid, job['id'], chunks, 'fixture.yaml', space['config_version'])
    settings(platform, wid, 'knowledge')
    monkeypatch.setenv('MEMORY_CENTER_SQLITE_VECTOR_SCAN_LIMIT', '2')
    monkeypatch.setattr(Embedder, 'embed', lambda *args: [[0.0, 1.0]])
    result = platform.lookup(platform.administrator(), wid, 'note', 'vector')
    assert result['vector_enabled'] and not result['vector_reindex_required']
    assert [item['source']['kind'] for item in result['items']] == ['wiki']
