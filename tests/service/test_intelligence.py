"""普通模型整理：来源隔离、预览与原子确认保存。"""
import httpx
import pytest

from memory_center.core.foundation.catalog import CatalogError
from memory_center.platform.intelligence import ChatModel
from test_platform import service  # noqa: F401


@pytest.fixture
def model(monkeypatch):
    calls = []
    def generate(self, content):
        calls.append(content)
        return '# 整理结果\n\n已保留原始事实。'
    monkeypatch.setattr(ChatModel, 'generate', generate)
    return calls


def configure(client, headers):
    r = client.put('/api/v1/chat-model', headers=headers, json={
        'url': 'http://localhost:11434', 'model': 'test-model', 'protocol': 'ollama'})
    assert r.status_code == 200, r.text


def test_preview_edit_apply_and_idempotency(service, model):
    client, headers, platform, spaces = service
    configure(client, headers)
    workspace = spaces[0]['workspace_id']
    page = platform.knowledge.wiki('admin', workspace, '原标题', '原始事实')
    base = f'/api/v1/workspaces/{workspace}/organize'
    draft = client.post(base, headers=headers, json={'kind': 'wiki', 'record_ids': [page['id']]}).json()
    assert draft['requires_review'] and not draft['copy']
    assert platform.store.get('wiki', page['id'])['content'] == '原始事实'
    body = {'revision': draft['revision'], 'title': '人工修订标题', 'content': '经过审阅的结果'}
    saved = client.post(base + '/' + draft['id'] + '/apply', headers=headers, json=body)
    assert saved.status_code == 200, saved.text
    assert saved.json()['content'] == body['content']
    assert saved.json()['versions'][-1]['content'] == '原始事实'
    assert saved.json()['organized_sources'][0]['revision'] == 1
    again = client.post(base + '/' + draft['id'] + '/apply', headers=headers, json=body)
    assert again.json()['revision'] == saved.json()['revision']
    assert len(model) == 1


def test_conflict_scope_and_model_failure_preserve_original(service, model, monkeypatch):
    client, headers, platform, spaces = service
    configure(client, headers)
    a, b = [s['workspace_id'] for s in spaces]
    page = platform.knowledge.wiki('admin', a, '标题', '原文')
    base = f'/api/v1/workspaces/{a}/organize'
    assert client.post(f'/api/v1/workspaces/{b}/organize', headers=headers,
                       json={'kind': 'wiki', 'record_ids': [page['id']]}).json()['error']['code'] == 'FORBIDDEN'
    draft = client.post(base, headers=headers, json={'kind': 'wiki', 'record_ids': [page['id']]}).json()
    platform.knowledge.wiki('admin', a, '标题', '新版本', page['id'], 1)
    response = client.post(base + '/' + draft['id'] + '/apply', headers=headers,
                           json={'revision': 1, 'title': '整理', 'content': '不应覆盖'})
    assert response.status_code >= 400
    assert platform.store.get('wiki', page['id'])['content'] == '新版本'
    def fail(*args):
        raise CatalogError('CHAT_CONNECTION_FAILED', '连接失败')
    monkeypatch.setattr(ChatModel, 'generate', fail)
    assert client.post(base, headers=headers, json={'kind': 'wiki', 'record_ids': [page['id']]}).status_code >= 400
    assert len(platform.store.list('intelligence_preview')) == 1


def test_merge_keeps_sources_and_memory_needs_confirmation(service, model):
    client, headers, platform, spaces = service
    configure(client, headers)
    a = spaces[0]['workspace_id']
    base = f'/api/v1/workspaces/{a}/organize'
    pages = [platform.knowledge.wiki('admin', a, str(i), f'事实 {i}') for i in range(2)]
    draft = client.post(base, headers=headers, json={'kind': 'wiki', 'record_ids': [p['id'] for p in pages]}).json()
    assert draft['copy']
    result = client.post(base + '/' + draft['id'] + '/apply', headers=headers,
                        json={'revision': 1, 'title': '汇总', 'content': '汇总事实'}).json()
    assert result['id'] not in [p['id'] for p in pages]
    assert all(platform.store.get('wiki', p['id'])['revision'] == 1 for p in pages)
    memory = platform.knowledge.memory('admin', a, '确认过的记忆', confirmed=True)
    draft = client.post(base, headers=headers, json={'kind': 'memory', 'record_ids': [memory['id']]}).json()
    result = client.post(base + '/' + draft['id'] + '/apply', headers=headers,
                        json={'revision': 1, 'title': '记忆', 'content': '模型整理过的记忆'}).json()
    assert result['status'] == 'pending'
    assert result['versions'][0]['status'] == 'confirmed'


def test_readonly_directory_is_copied_and_freshness_checked(service, model, tmp_path):
    client, headers, platform, spaces = service
    configure(client, headers)
    a = spaces[0]['workspace_id']
    root = tmp_path / 'wiki'; root.mkdir()
    path = root / 'page.md'; path.write_text('# 来源\n原始资料')
    source = platform.wiki_sources.save('来源', str(root), [a])
    platform.wiki_sources.sync(source['id'])
    item = list(platform.wiki_sources.pages(a))[0]
    base = f'/api/v1/workspaces/{a}/organize'
    draft = client.post(base, headers=headers, json={'kind': 'wiki', 'record_ids': [item['id']]}).json()
    assert draft['copy']
    saved = client.post(base + '/' + draft['id'] + '/apply', headers=headers,
                        json={'revision': 1, 'title': '副本', 'content': '整理资料'})
    assert saved.status_code == 200, saved.text
    assert not saved.json().get('readonly') and path.read_text() == '# 来源\n原始资料'
    path.write_text('# 修改了')
    assert client.post(base, headers=headers, json={'kind': 'wiki', 'record_ids': [item['id']]}).status_code >= 400


@pytest.mark.parametrize('protocol', ['ollama', 'openai'])
def test_real_chat_transport_and_invalid_output(monkeypatch, protocol):
    real_client = httpx.Client
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={'message': {'content': '整理正文'}} if protocol == 'ollama' else
                               {'choices': [{'message': {'content': '整理正文'}, 'finish_reason': 'stop'}]})
    monkeypatch.setattr(httpx, 'Client', lambda **kw: real_client(**kw, transport=httpx.MockTransport(handler)))
    settings = {'url': 'http://localhost:1234/v1' if protocol == 'openai' else 'http://localhost:11434',
                'model': 'test', 'protocol': protocol}
    assert ChatModel(settings).generate('资料') == '整理正文'
    assert requests[0].url.path == ('/v1/chat/completions' if protocol == 'openai' else '/api/chat')
    monkeypatch.setattr(httpx, 'Client', lambda **kw: real_client(**kw, transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={'message': {'content': ''}, 'choices': []}))))
    with pytest.raises(CatalogError):
        ChatModel(settings).generate('资料')


def test_unconfigured_model_is_explicit():
    with pytest.raises(CatalogError, match='普通模型'):
        ChatModel({}).generate('资料')
