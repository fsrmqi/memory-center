"""哈希增量、删除清理和发布失败时上一代保护。"""
import json
from pathlib import Path

from memory_center.platform.jobs import run_index
from memory_center.core.storage.workspace import WorkspaceStore
from memory_center.platform.incremental_index import plan_incremental, seed_facts
from tests.service.test_platform import service  # noqa: F401
from tests.service.test_project_embedding import settings


def build(platform, space):
    job = platform.store.create('job', {'workspace_id': space['workspace_id'], 'status': 'running',
                                      'config_version': space['config_version']})
    run_index(platform.store.db.data_dir, platform.store.db.url, space, job['id'], file_workers=0)
    result = platform.store.get('job', job['id'])
    assert result['status'] == 'succeeded', result
    return result, Path(platform.store.get('index', space['workspace_id'])['workspace_file']).parent


def test_cold_warm_delta_and_delete(service, monkeypatch):
    _, _, platform, spaces = service
    space = spaces[0]
    settings(platform, space['workspace_id'], 'off')
    import importlib
    jobs = importlib.import_module("memory_center.core.indexing.reindex")
    real = jobs.reindex_workspace
    calls = []
    def track(*args, **kwargs):
        calls.append(kwargs)
        return real(*args, **kwargs)
    monkeypatch.setattr(jobs, 'reindex_workspace', track)
    cold, first = build(platform, space)
    assert cold['incremental']['mode'] == 'full' and len(calls) == 1
    snapshot = (first/'graph/graph.db').read_bytes()
    warm, second = build(platform, space)
    assert warm['incremental']['mode'] == 'unchanged' and len(calls) == 1
    assert (first/'graph/graph.db').stat().st_ino != (second/'graph/graph.db').stat().st_ino
    root = Path(space['root'])
    source = root/'Entry.java'
    source.write_text('package demo; public class Entry { public void changed() {} }')
    delta, third = build(platform, space)
    assert delta['incremental']['mode'] == 'incremental' and delta['incremental']['modified_files'] == 1
    assert calls[-1]['resolve_all_relations'] is True
    symbols = WorkspaceStore(third/'workspace.yaml').read_json_prefer_backend('java-symbol-index.json', [])
    assert any(m == 'changed' for row in symbols for m in row.get('methods',[]))
    assert not any(m == 'hello' for row in symbols for m in row.get('methods',[]))
    source.unlink()
    deleted, fourth = build(platform, space)
    assert deleted['incremental']['deleted_files'] == 1
    assert WorkspaceStore(fourth/'workspace.yaml').read_json_prefer_backend('java-symbol-index.json', []) == []
    assert not any(row['path'].endswith('Entry.java') for row in WorkspaceStore(fourth/'workspace.yaml').read_json_prefer_backend('index-coverage.json', {})['files'])
    assert (first/'graph/graph.db').read_bytes() == snapshot


def test_manifest_scope_and_config_invalidation():
    old = {'schema': 1, 'config': 'same', 'files': {'a/X.java': {'hash': 'x', 'service': 'a'}, 'b/Y.java': {'hash': 'y', 'service': 'b'}}}
    new = json.loads(json.dumps(old));new['files']['a/X.java']['hash'] = 'changed'
    plan = plan_incremental(old, new, ['a','b'])
    assert plan['changed_services'] == ['a'] and plan['reused_services'] == ['b']
    new['files']['pom.xml'] = {'hash': 'shared', 'service': ''}
    assert plan_incremental(old, new, ['a','b'])['changed_services'] == ['a','b']
    new['config'] = 'different'
    assert plan_incremental(old, new, ['a','b'])['mode'] == 'full'


def test_source_change_during_build_does_not_publish(service, monkeypatch):
    _, _, platform, spaces = service
    space = spaces[0];settings(platform, space['workspace_id'], 'off')
    _, original = build(platform, space)
    from memory_center.platform.embeddings import Embedder
    # 模型设置读取发生在解析以后，隔离地模拟解析期间源码变化。
    real = Embedder.__init__
    def mutate(self, *args, **kwargs):
        real(self, *args, **kwargs)
        (Path(space['root'])/'Entry.java').write_text('class Changed {}')
    monkeypatch.setattr(Embedder, '__init__', mutate)
    job = platform.store.create('job', {'workspace_id': space['workspace_id'], 'status': 'running', 'config_version': space['config_version']})
    run_index(platform.store.db.data_dir, platform.store.db.url, space, job['id'], file_workers=0)
    failed = platform.store.get('job', job['id'])
    assert failed['status'] == 'failed' and failed['error'] == 'SOURCE_CHANGED'
    assert Path(platform.store.get('index', space['workspace_id'])['workspace_file']).parent == original


def test_corrupt_manifest_falls_back_full(service):
    _, _, platform, spaces = service
    space = spaces[0];settings(platform, space['workspace_id'], 'off')
    _, directory = build(platform, space)
    manifest = json.loads((directory/'source-manifest.json').read_text())
    manifest['files']['../outside'] = {'hash':'x','service':''}
    (directory/'source-manifest.json').write_text(json.dumps(manifest))
    job, _ = build(platform, space)
    assert job['incremental']['mode'] == 'full'


def test_only_changed_service_parsed_and_global_graph_matches_cold(service, monkeypatch):
    _, _, platform, spaces = service
    space = spaces[0];root = Path(space['root'])
    for name in ('left','right'):
        folder=root/name;folder.mkdir()
        (folder/'Entry.java').write_text(f'package {name}; public class Entry {{ public void unchanged() {{}} }}')
    services=[{'service_id':name,'name':name,'path':name,'type':'java','exclude_paths':[]} for name in ('left','right')]
    space=platform.catalog.update(space['workspace_id'],space['revision'],services=services)
    settings(platform,space['workspace_id'],'off')
    build(platform,space)
    import importlib
    engine=importlib.import_module('memory_center.core.indexing.reindex');real=engine.reindex_workspace;seen=[]
    def track(*args, **kwargs):
        seen.append(kwargs['projects']);return real(*args,**kwargs)
    monkeypatch.setattr(engine,'reindex_workspace',track)
    (root/'left/Entry.java').write_text('package left; public class Entry { public void updated() {} }')
    task,delta=build(platform,space)
    assert len(seen)==1 and len(seen[0])==1 and len(task['incremental']['reused_services'])==1
    merged=WorkspaceStore(delta/'workspace.yaml').read_json_prefer_backend('java-symbol-index.json',[])
    assert any(r['file'].startswith('right/') and any(m=='unchanged' for m in r.get('methods',[])) for r in merged)
    # 删除清单强制冷构建，事实集合应与增量结果一致。
    (delta/'source-manifest.json').unlink()
    _,cold=build(platform,space)
    rebuilt=WorkspaceStore(cold/'workspace.yaml').read_json_prefer_backend('java-symbol-index.json',[])
    assert sorted(json.dumps(row,sort_keys=True) for row in merged)==sorted(json.dumps(row,sort_keys=True) for row in rebuilt)
    import sqlite3
    def edges(directory):
        with sqlite3.connect(directory/'graph/graph.db') as db:
            return db.execute('SELECT source_id,target_id,type FROM edges ORDER BY source_id,target_id,type').fetchall()
    assert edges(delta)==edges(cold)
