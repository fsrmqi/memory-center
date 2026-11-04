"""参考机制的行为回归：预算、坏缓存、取消、重排、别名与候选门禁。"""
import asyncio
import json
import sqlite3
from types import SimpleNamespace

import httpx
import pytest

from memory_center.platform.code_graph import build_code_graph
from memory_center.platform.diagnostics import failure_receipt
from memory_center.platform.embedding_cache import EmbeddingCache
from memory_center.platform.embeddings import Embedder, EmbeddingCancelled
from memory_center.platform.jobs import Jobs
from memory_center.platform.parse_cache import ParseCache
from memory_center.platform.reranking import Reranker
from tests.service.test_platform import service as service  # noqa: F401


@pytest.mark.parametrize('kind', ['parse', 'embedding'])
def test_invalid_utf8_cache_is_miss(tmp_path, kind):
    cache = ParseCache(tmp_path) if kind == 'parse' else EmbeddingCache(tmp_path)
    path = cache.path_for('model', 'hash')
    path.parent.mkdir(parents=True)
    path.write_bytes(b'\xff\xfe')
    assert (cache.get('model', 'hash') if kind == 'parse' else cache.get('model', 'hash', 1)) is None
    assert cache.corrupt == 1


def test_cancel_during_request_does_not_consume_or_cache():
    stopped = [False]
    class Client:
        def post(self, *args, **kwargs):
            stopped[0] = True
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {'embeddings': [[1.0]]})
    class Cache:
        def get(self, *args): return None
        def put(self, *args): pytest.fail('取消后写缓存')
    with pytest.raises(EmbeddingCancelled):
        Embedder({'url': 'http://test.invalid', 'model': 'demo', 'dimensions': 1}, Client()).embed_many(
            ['demo'], cache=Cache(), should_stop=lambda: stopped[0])


def test_global_budget_reserves_later_projects(monkeypatch):
    monkeypatch.setattr('memory_center.platform.jobs.cpu_budget', lambda: 16)
    stub = SimpleNamespace(settings=lambda: {'max_projects': 4, 'max_file_workers': 0})
    grants = [Jobs.file_workers_for(stub, n) + 1 for n in range(1, 5)]
    assert sum(grants) <= 16
    assert grants == [4, 4, 4, 4]


def test_failure_receipt_does_not_expose_exception_text():
    receipt = failure_receipt(sqlite3.OperationalError('Expression tree is too large private-value'), phase='services', subject='job_demo')
    assert receipt['error'] == 'SQLITE_EXPRESSION_LIMIT'
    assert 'private-value' not in json.dumps(receipt)
    assert receipt['diagnostics']['automatic_retry'] is False


def test_rerank_validation_sorting_and_fallback(monkeypatch):
    items = [{'content': 'first'}, {'content': 'second'}]
    response = httpx.Response(200, json={'results': [{'index': 0, 'relevance_score': .1}, {'index': 1, 'relevance_score': .8}]}, request=httpx.Request('POST', 'http://test.invalid'))
    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, *args, **kwargs): return response
    monkeypatch.setattr('memory_center.platform.reranking.httpx.Client', Client)
    ranker = Reranker({'enabled': True, 'url': 'http://test.invalid', 'model': 'demo'})
    ranked, state = ranker.rank('query', items)
    assert ranked[0]['content'] == 'second' and state['state'] == 'applied'
    response = httpx.Response(200, json={'results': [{'index': 0, 'relevance_score': 1}, {'index': 0, 'relevance_score': .5}]}, request=httpx.Request('POST', 'http://test.invalid'))
    ranked, state = ranker.rank('query', items)
    assert ranked == items and state['state'] == 'fallback'


def graph_from(tmp_path, sources):
    paths = []
    for name, text in sources.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        paths.append(path)
    return build_code_graph(tmp_path, paths)


def test_ts_alias_and_reexport_chain(tmp_path):
    graph = graph_from(tmp_path, {
        'tsconfig.json': '{"compilerOptions":{"baseUrl":".","paths":{"@/*":["src/*"]}}}',
        'src/impl.ts': 'export function assist() { return 1; }',
        'src/barrel.ts': 'export {assist as help} from "./impl";',
        'src/main.ts': 'import {help} from "@/barrel"; export function run() { return help(); }'})
    assert any(e['resolution'] == 'explicit_import' for e in graph['edges'])
    target = next(s for s in graph['symbols'] if s['name'] == 'assist')
    assert any(e['target'] == target['id'] for e in graph['edges'])


def test_inherited_calls_are_inferred(tmp_path):
    graph = graph_from(tmp_path, {
        'Example.java': 'package demo; class Base { void help() {} } class Child extends Base { void run() { help(); } }',
        'example.py': 'class Base:\n    def help(self):\n        return 1\nclass Child(Base):\n    def run(self):\n        return self.help()\n'})
    inherited = [e for e in graph['edges'] if e['resolution'] == 'inherited_method']
    assert len(inherited) == 2
    assert all(e['evidence_level'] == 'INFERRED' for e in inherited)


def test_reexport_cycle_is_unresolved(tmp_path):
    graph = graph_from(tmp_path, {'a.ts': 'export {help} from "./b";', 'b.ts': 'export {help} from "./a";',
        'main.ts': 'import {help} from "./a"; export function run(){help();}'})
    assert not graph['edges'] and graph['unresolved']


def test_background_organize_and_capture_are_review_only(service, monkeypatch):
    client, headers, platform, spaces = service
    workspace = spaces[0]['workspace_id']
    # Pause task selection while validating the persisted queue and manual execution.
    platform.knowledge_tasks.stopping = True
    monkeypatch.setattr('memory_center.platform.intelligence.ChatModel.generate', lambda self, text: '# 整理后的资料')
    platform.store.create('chat_model', {'model': 'mock'})
    for i in range(23):
        platform.knowledge.wiki('admin', workspace, f'page-{i}', 'duplicate' if i < 2 else f'content-{i}')
    response = client.post(f'/api/v1/workspaces/{workspace}/knowledge-tasks', headers=headers, json={'kind': 'wiki'})
    assert response.status_code == 200, response.text
    task = response.json()
    platform.knowledge_tasks.stopping = False
    platform.knowledge_tasks.run(task['id'])
    result = platform.store.get('knowledge_task', task['id'])
    assert result['status'] == 'succeeded' and result['completed'] == 23
    assert len(result['preview_ids']) == 2 and len(result['duplicate_groups']) == 1
    assert len(platform.store.list('wiki', workspace)) == 23  # 预览不写原文
    capture_url = f'/api/v1/workspaces/{workspace}/session-candidates'
    payload = {'source_id': 'session-demo', 'content': '待审会话资料'}
    assert client.post(capture_url, headers=headers, json=payload).status_code == 422
    assert client.put(f'/api/v1/workspaces/{workspace}/capture-settings', headers=headers, json={'enabled': True}).status_code == 200
    one = client.post(capture_url, headers=headers, json=payload).json()
    two = client.post(capture_url, headers=headers, json=payload).json()
    assert one['id'] == two['id'] and one['status'] == 'pending'
    assert not list(i for kind,i in platform.knowledge.active(workspace) if kind == 'memory')


def seed_index(platform, workspace):
    from memory_center.platform.jobs import split_text
    job = platform.store.create('job', {'workspace_id': workspace['workspace_id'], 'status': 'running'})
    code = split_text('preserved code', {'kind': 'code', 'source_id': 'code:demo.py', 'path': 'demo.py'})
    platform.store.publish(workspace['workspace_id'], job['id'], code, 'isolated.yaml', workspace['config_version'])
    return job['id'], code[0]['id']


def test_knowledge_refresh_replaces_only_knowledge_and_stops_after_failure(service):
    client, headers, platform, spaces = service
    workspace = spaces[0]['workspace_id']
    generation, code_id = seed_index(platform, spaces[0])
    page = platform.knowledge.wiki('admin', workspace, 'page', 'uniqueknowledge')
    manager = platform.knowledge_tasks
    first = manager.enqueue_refresh(workspace)
    manager.run(first['id'])
    assert platform.store.get('knowledge_task', first['id'])['status'] == 'succeeded'
    assert platform.lookup(platform.administrator(), workspace, 'uniqueknowledge', 'keyword')['items']
    platform.store.update('wiki', page['id'], {'status': 'deleted'})
    second = manager.enqueue_refresh(workspace)
    manager.run(second['id'])
    assert platform.store.get('knowledge_task', second['id'])['status'] == 'succeeded'
    index = platform.store.get('index', workspace)
    assert index['generation'] == generation and index['chunk_count'] == 1
    with platform.store.db.connection() as connection:
        assert connection.execute('SELECT id FROM chunks WHERE workspace_id=?', (workspace,)).fetchone()[0] == code_id
        assert connection.execute('SELECT count(*) FROM chunk_terms WHERE chunk_id!=?', (code_id,)).fetchone()[0] == 0
    stopped = manager.enqueue_refresh(workspace)
    manager.cancel(stopped['id'])
    assert manager.enqueue_refresh(workspace, automatic=True)['id'] == stopped['id']
    assert manager.enqueue_refresh(workspace)['id'] != stopped['id']


def test_organize_change_during_model_request_drops_preview(service, monkeypatch):
    client, headers, platform, spaces = service
    workspace = spaces[0]['workspace_id']
    platform.store.create('chat_model', {'model': 'mock'})
    page = platform.knowledge.wiki('admin', workspace, 'page', 'before')
    original = __import__('memory_center.platform.intelligence', fromlist=['Intelligence']).Intelligence.preview
    def changed(self, *args):
        platform.store.update('wiki', page['id'], {'content': 'after'})
        return original(self, *args)
    monkeypatch.setattr('memory_center.platform.intelligence.Intelligence.preview', changed)
    monkeypatch.setattr('memory_center.platform.intelligence.ChatModel.generate', lambda self, text: 'result')
    task = platform.knowledge_tasks.enqueue(workspace, 'wiki')
    platform.knowledge_tasks.run(task['id'])
    assert platform.store.get('knowledge_task', task['id'])['error'] == 'REVISION_CONFLICT'
    assert not platform.store.list('intelligence_preview', workspace)


def test_cancel_during_organize_drops_preview(service, monkeypatch):
    _, _, platform, spaces = service
    workspace = spaces[0]['workspace_id']
    platform.store.create('chat_model', {'model': 'mock'})
    platform.knowledge.wiki('admin', workspace, 'page', 'original')
    task = platform.knowledge_tasks.enqueue(workspace, 'wiki')
    def cancelled(self, text):
        platform.knowledge_tasks.cancel(task['id'])
        return 'result'
    monkeypatch.setattr('memory_center.platform.intelligence.ChatModel.generate', cancelled)
    platform.knowledge_tasks.run(task['id'])
    assert platform.store.get('knowledge_task', task['id'])['status'] == 'cancelled'
    assert not platform.store.list('intelligence_preview', workspace)


def test_java_inheritance_across_package_files(tmp_path):
    graph = graph_from(tmp_path, {'demo/Base.java': 'package demo; class Base { void help() {} }',
        'demo/Child.java': 'package demo; class Child extends Base { void run() { help(); } }'})
    assert len([e for e in graph['edges'] if e['resolution'] == 'inherited_method']) == 1


def test_retrieval_evaluation_uses_manual_source_keys(service):
    client, headers, platform, spaces = service
    workspace = spaces[0]['workspace_id']
    seed_index(platform, spaces[0])
    response = client.post(f'/api/v1/workspaces/{workspace}/retrieval-evaluation', headers=headers,
        json={'cases': [{'query': 'preserved', 'mode': 'keyword', 'expected_sources': ['code:demo.py']}]})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['mean_recall'] == result['mean_precision'] == 1
    assert result['automatic_tuning'] is False and 'preserved' not in json.dumps(result)


def test_embedding_request_window_is_bounded_on_cancel():
    stopped, calls = [False], []
    class Client:
        def post(self, *args, **kwargs):
            calls.append(kwargs['json']['input'])
            stopped[0] = True
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {'embeddings': [[1.0]]})
    with pytest.raises(EmbeddingCancelled):
        Embedder({'url': 'http://test.invalid', 'model': 'demo', 'dimensions': 1}, Client()).embed_many(
            [f'demo-{i}' for i in range(100)], concurrency=2, batch_size=1, should_stop=lambda: stopped[0])
    assert len(calls) <= 2


def test_unimported_python_base_does_not_create_inheritance_edge(tmp_path):
    graph = graph_from(tmp_path, {'base.py': 'class Base:\n    def help(self):\n        return 1\n',
        'main.py': 'class Child(Base):\n    def run(self):\n        return self.help()\n'})
    assert not graph['edges'] and graph['unresolved']


def test_jsonc_alias_with_trailing_comma_and_imported_reexport(tmp_path):
    graph = graph_from(tmp_path, {
        'tsconfig.json': '{// configuration\n"compilerOptions":{"paths":{"@/*":["src/*",],},},}',
        'src/impl.ts': 'export function assist(){return 1;}',
        'src/barrel.ts': 'import {assist} from "./impl"; export {assist as help};',
        'src/main.ts': 'import {help} from "@/barrel"; export function run(){return help();}'})
    target = next(s for s in graph['symbols'] if s['name'] == 'assist')
    assert any(e['target'] == target['id'] for e in graph['edges'])


@pytest.mark.parametrize('usage,expected', [({'prompt_tokens': 7},7), ({},None), ({'prompt_tokens': True},None)])
def test_embedding_metrics_use_only_real_integer_usage(usage, expected):
    class Client:
        def post(self, *args, **kwargs):
            return SimpleNamespace(raise_for_status=lambda: None,
                json=lambda: {'data': [{'index': 0, 'embedding': [1.0]}], 'usage': usage})
    embedder = Embedder({'url': 'http://test.invalid', 'model': 'demo', 'protocol':'openai', 'dimensions':1}, Client())
    assert embedder.embed(['fixture']) == [[1.0]]
    assert embedder.metrics['requests'] == 1
    assert embedder.metrics['request_seconds'] >= 0
    assert embedder.metrics['input_tokens'] == expected
