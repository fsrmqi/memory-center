"""5.0 服务隔离、事务发布、知识治理与真实 Worker 验证。"""
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from memory_center.core.foundation.catalog import CatalogError
from memory_center.service.app import create_service_app
from memory_center.service.config import ServiceConfig


@pytest.fixture(params=['sqlite', 'postgres'])
def service(request, tmp_path):
    url = os.environ.get('MEMORY_CENTER_TEST_DATABASE_URL', '') if request.param == 'postgres' else ''
    if request.param == 'postgres' and not url:
        pytest.skip('需要隔离 PostgreSQL 验证数据库')
    if url:
        from memory_center.platform.database import pg_connect
        with pg_connect(url) as connection:
            from urllib.parse import urlencode
            from uuid import uuid4
            schema = 'mc_verify_' + uuid4().hex
            connection.execute('CREATE SCHEMA ' + schema)
        base_url = url
        url += ('&' if '?' in url else '?') + urlencode({'options': '-csearch_path=' + schema + ',public'})
    data = tmp_path / 'data'
    app = create_service_app(ServiceConfig(data, database_url=url, auth_mode="token"))
    a, b = tmp_path / 'a', tmp_path / 'b'
    for root, text in [(a, 'alpha only'), (b, 'beta only')]:
        root.mkdir()
        (root / 'README.md').write_text(text)
        (root / 'pom.xml').write_text('<project/>')
        (root / 'Entry.java').write_text('package demo; public class Entry { public void hello() {} }')
    with TestClient(app, base_url='http://localhost') as client:
        headers = {'Authorization': 'Bearer ' + (data / 'admin-token').read_text()}
        spaces = [client.post('/api/v1/workspaces', headers=headers, json={'name': root.name, 'root': str(root)}).json()
                  for root in [a, b]]
        yield client, headers, app.state.platform, spaces
    if url:
        with pg_connect(base_url) as connection:
            connection.execute("DROP SCHEMA " + schema + " CASCADE")


def credential(client, headers, spaces, writable=True):
    result = client.post('/api/v1/credentials', headers=headers,
                         json={'name': 'test', 'workspace_ids': spaces, 'writable': writable})
    assert result.status_code == 201, result.text
    return result.json()


def mcp_connect(client, token=''):
    headers = {'Accept': 'application/json, text/event-stream', **({'Authorization': 'Bearer ' + token} if token else {})}
    response = client.post('/mcp', headers=headers, json={'jsonrpc': '2.0', 'id': 0, 'method': 'initialize', 'params': {
        'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 'test', 'version': '1'}}})
    assert response.status_code == 200, response.text
    headers['Mcp-Session-Id'] = response.headers['mcp-session-id']
    headers['MCP-Protocol-Version'] = response.json()['result']['protocolVersion']
    response = client.post('/mcp', headers=headers, json={'jsonrpc': '2.0', 'method': 'notifications/initialized'})
    assert response.status_code == 202
    return headers


def call(client, headers, tool, arguments):
    response = client.post('/mcp', headers=headers, json={'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
                                                          'params': {'name': tool, 'arguments': arguments}})
    assert response.status_code == 200, response.text
    return response.json()['result']


def test_mcp_initialize_reports_service_version(service):
    """握手 serverInfo.version 必须是本服务版本，而不是 MCP SDK 版本。"""
    from memory_center import __version__

    client, admin, _platform, spaces = service
    read = credential(client, admin, [spaces[0]['workspace_id']], False)
    response = client.post('/mcp', headers={'Accept': 'application/json, text/event-stream',
                                            'Authorization': 'Bearer ' + read['token']},
                           json={'jsonrpc': '2.0', 'id': 0, 'method': 'initialize', 'params': {
                               'protocolVersion': '2025-06-18', 'capabilities': {},
                               'clientInfo': {'name': 'test', 'version': '1'}}})
    assert response.status_code == 200, response.text
    info = response.json()['result']['serverInfo']
    assert info['version'] == __version__
    assert info['name'] == 'Memory Center 5.0'


def test_credential_scope_session_revoke(service):
    client, admin, platform, spaces = service
    a, b = [s['workspace_id'] for s in spaces]
    ca, cb = credential(client, admin, [a]), credential(client, admin, [b])
    ha, hb = mcp_connect(client, ca['token']), mcp_connect(client, cb['token'])
    readonly = credential(client, admin, [a], False)
    hr = mcp_connect(client, readonly['token'])
    listing = client.post('/mcp', headers=hr, json={'jsonrpc': '2.0', 'id': 3, 'method': 'tools/list'}).json()['result']
    assert 'mc_start' not in [tool['name'] for tool in listing['tools']]
    assert call(client, hr, 'mc_start', {'workspace_id': a, 'intent': 'illegal'})['isError']
    assert call(client, ha, 'mc_start', {'workspace_id': b, 'intent': 'illegal'})['isError']
    response = call(client, ha, 'mc_start', {'workspace_id': a, 'intent': 'alpha'})
    assert not response.get('isError'), response
    started = response['structuredContent']
    assert call(client, hb, 'mc_resume', {'session_id': started['id']})['isError']
    assert call(client, ha, 'mc_lookup', {'workspace_id': b, 'query': 'alpha'})['isError']
    assert 'digest' not in client.get('/api/v1/credentials', headers=admin).text
    assert ca['token'] not in client.get('/api/v1/credentials', headers=admin).text
    stolen = {**hb, 'Mcp-Session-Id': ha['Mcp-Session-Id']}
    assert client.post('/mcp', headers=stolen, json={'jsonrpc': '2.0', 'id': 8, 'method': 'tools/list'}).status_code == 403
    assert client.delete('/api/v1/credentials/' + ca['id'], headers=admin).status_code == 200
    assert client.post('/mcp', headers=ha, json={'jsonrpc': '2.0', 'id': 9, 'method': 'tools/list'}).status_code == 401
    assert call(client, hb, 'mc_resume', {'session_id': started['id']})['isError']


def test_mc_resume_returns_continuation_contract(service):
    client, admin, platform, spaces = service
    a = spaces[0]['workspace_id']
    credential_a = credential(client, admin, [a])
    headers = mcp_connect(client, credential_a['token'])
    started = call(client, headers, 'mc_start', {'workspace_id': a, 'intent': '接续契约'})['structuredContent']
    resumed = call(client, headers, 'mc_resume', {'session_id': started['id']})['structuredContent']
    assert resumed['id'] == started['id']
    continuation = resumed['continuation']
    assert continuation['strategy'] == 'continue_session'
    assert continuation['session_handle'] == {'provider': 'memory-center', 'session_id': started['id'], 'state': 'open'}
    assert continuation['next_action']['tool'] in {'mc_lookup', 'mc_index'}
    assert resumed['content_boundary']['instruction'] == ['continuation.next_action']

    call(client, headers, 'mc_close', {'session_id': started['id'], 'outcome': 'done'})
    closed = call(client, headers, 'mc_resume', {'session_id': started['id']})['structuredContent']
    assert closed['continuation']['strategy'] == 'rebuild_from_packet'
    assert closed['continuation']['reason'].startswith('session_closed')
    assert closed['continuation']['session_handle']['state'] == 'closed'


def test_mc_lookup_marks_instruction_and_data_boundary(service):
    client, admin, platform, spaces = service
    a = spaces[0]['workspace_id']
    result = platform.lookup(platform.administrator(), a, 'alpha', 'hybrid', 5)
    boundary = result['content_boundary']
    assert boundary['data'] == ['items', 'symbols', 'chain']
    assert boundary['instruction'] == []
    assert 'generation' in boundary['metadata']
    assert boundary['policy']


def test_knowledge_generation_and_cancellation(service):
    client, admin, platform, spaces = service
    a, b = [s['workspace_id'] for s in spaces]
    doc = client.post(f'/api/v1/workspaces/{a}/documents', headers=admin,
                      json={'filename': '启动.md', 'content': '# 启动方法\n容器启动使用 compose，项目记忆长期保存。'}).json()
    pending = client.post(f'/api/v1/workspaces/{a}/memories', headers=admin,
                          json={'content': 'secretpending 不应召回'}).json()
    platform.knowledge.memory('other-agent', a, 'secretowner 不应召回', True)
    actor = platform.administrator()
    response = client.post(f'/api/v1/workspaces/{a}/index', headers=admin, json={})
    assert response.status_code == 200, response.text
    job = response.json()
    for _ in range(160):
        status = platform.store.get('job', job['id'])
        if status['status'] in {'succeeded', 'failed'}:
            break
        time.sleep(.1)
    assert status['status'] == 'succeeded', status
    result = platform.lookup(actor, a, '项目记忆', 'keyword')
    assert result['items'] and all(item['workspace_id'] == a for item in result['items'])
    assert platform.lookup(actor, a, 'secretpending', 'keyword')['items'] == []
    assert platform.lookup(actor, a, 'secretowner', 'keyword')['items'] == []
    assert platform.lookup(actor, b, '项目记忆', 'keyword')['state'] == 'NOT_INDEXED'
    assert client.patch(f'/api/v1/workspaces/{a}/knowledge/document/{doc["id"]}', headers=admin,
                        json={'revision': doc['revision'], 'status': 'deleted'}).status_code == 200
    assert platform.lookup(actor, a, '项目记忆', 'keyword')['items'] == []
    assert client.patch(f'/api/v1/workspaces/{b}/knowledge/memory/{pending["id"]}', headers=admin,
                        json={'revision': pending['revision'], 'status': 'confirmed'}).status_code == 422
    old = platform.store.get('index', a)['generation']
    cancelled = platform.store.create('job', {'workspace_id': a, 'owner': 'admin', 'status': 'cancelled', 'progress': 0})
    with pytest.raises(CatalogError, match='取消'):
        platform.store.publish(a, cancelled['id'], [], '', spaces[0]['config_version'])
    assert platform.store.get('index', a)['generation'] == old
    source = Path(spaces[0]['root']) / 'README.md'
    source.write_text('changed alpha only')
    stale = platform.lookup(actor, a, 'alpha', 'keyword')
    assert stale['items'][0]['freshness'] == 'STALE'


def test_wiki_revision_and_memory_state(service):
    client, admin, platform, spaces = service
    a = spaces[0]['workspace_id']
    wiki = client.post(f'/api/v1/workspaces/{a}/wiki', headers=admin, json={'title': '启动', 'content': '版本一'}).json()
    edited = client.patch(f'/api/v1/workspaces/{a}/wiki/{wiki["id"]}', headers=admin,
                          json={'title': '启动', 'content': '版本二', 'revision': 1}).json()
    assert edited['revision'] == 2 and edited['versions'][0]['content'] == '版本一'
    assert client.patch(f'/api/v1/workspaces/{a}/wiki/{wiki["id"]}', headers=admin,
                        json={'title': '启动', 'content': '旧写入', 'revision': 1}).status_code == 409
    rollback = client.post(f'/api/v1/workspaces/{a}/wiki/{wiki["id"]}/rollback', headers=admin,
                           json={'revision': 2, 'target_revision': 1}).json()
    assert rollback['revision'] == 3 and rollback['content'] == '版本一'
    memory = client.post(f'/api/v1/workspaces/{a}/memories', headers=admin, json={'content': '中文记忆'}).json()
    assert memory['status'] == 'pending'
    confirmed = client.patch(f'/api/v1/workspaces/{a}/knowledge/memory/{memory["id"]}', headers=admin,
                             json={'revision': 1, 'status': 'confirmed'}).json()
    assert confirmed['status'] == 'confirmed'


def test_pg_catalog_transaction_contract(service):
    client, admin, platform, spaces = service
    assert client.post('/api/v1/workspaces', headers=admin,
                       json={'name': 'duplicate', 'root': spaces[0]['root']}).status_code == 409
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda n: client.patch('/api/v1/workspaces/' + spaces[0]['workspace_id'], headers=admin,
                                                       json={'revision': 1, 'name': f'new-{n}'}).status_code, range(4)))
    assert results.count(200) == 1 and results.count(409) == 3


def test_vector_profile_pg_and_sqlite(service):
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Endpoint(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            vectors = [[1., 0., 0.] if 'alpha' in text else [0., 1., 0.] for text in body['input']]
            payload = json.dumps({'embeddings': vectors} if self.path == '/api/embed' else
                                 {'data': [{'index': i, 'embedding': v} for i, v in enumerate(vectors)]}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    endpoint = ThreadingHTTPServer(('127.0.0.1', 0), Endpoint)
    thread = threading.Thread(target=endpoint.serve_forever, daemon=True)
    thread.start()
    client, admin, platform, spaces = service
    workspace_id = spaces[0]['workspace_id']
    settings = {'url': f'http://127.0.0.1:{endpoint.server_port}', 'model': 'contract-fixture', 'dimensions': 3,
                'protocol': 'ollama'}
    try:
        assert client.post('/api/v1/models/test', headers=admin, json=settings).json()['ready']
        assert client.put('/api/v1/models', headers=admin, json=settings).status_code == 200
        job = platform.jobs.enqueue(workspace_id, 'admin')
        for _ in range(150):
            status = platform.store.get('job', job['id'])
            if status['status'] in {'succeeded', 'failed'}:
                break
            time.sleep(.1)
        assert status['status'] == 'succeeded', status
        actor = platform.administrator()
        result = platform.lookup(actor, workspace_id, 'alpha', 'vector')
        assert result['vector_enabled'] and 'alpha' in result['items'][0]['content']
        assert platform.resolve_reference(actor, result['ref_id'])['owner'] == 'admin'
        if platform.store.db.url:
            with platform.store.db.connection() as connection:
                assert connection.execute("SELECT count(*) FROM pg_indexes WHERE indexname LIKE 'mc_vec_%'").fetchone()[0] >= 1
        # 模型档案改变后不能混用同维度旧模型向量。
        settings['model'] = 'different-model'
        assert client.put('/api/v1/models', headers=admin, json=settings).status_code == 200
        assert platform.lookup(actor, workspace_id, 'alpha', 'vector')['items'] == []
        # 协议与错误维度通过真实 HTTP 夹具验证，不作为真实语义质量验证。
        settings['protocol'], settings['dimensions'] = 'openai', 3
        assert client.post('/api/v1/models/test', headers=admin, json=settings).json()['ready']
        settings['dimensions'] = 4
        assert client.post('/api/v1/models/test', headers=admin, json=settings).status_code == 422
    finally:
        endpoint.shutdown()
        endpoint.server_close()
        thread.join(timeout=3)


def test_ref_source_revocation_and_rate(service):
    client, admin, platform, spaces = service
    a = spaces[0]['workspace_id']
    actor = platform.administrator()
    doc = platform.knowledge.document(a, '来源', 'refprivate evidence only')
    response = client.post(f'/api/v1/workspaces/{a}/index', headers=admin, json={})
    assert response.status_code == 200, response.text
    job = response.json()
    for _ in range(150):
        status = platform.store.get('job', job['id'])
        if status['status'] in {'succeeded', 'failed'}:
            break
        time.sleep(.1)
    assert status['status'] == 'succeeded', status
    result = platform.lookup(actor, a, 'refprivate', 'keyword')
    assert platform.resolve_reference(actor, result['ref_id'])
    platform.store.update('document', doc['id'], {'status': 'deleted'}, doc['revision'])
    with pytest.raises(CatalogError, match='删除'):
        platform.resolve_reference(actor, result['ref_id'])
    limited = client.post('/api/v1/credentials', headers=admin,
                          json={'name': 'limited', 'workspace_ids': [a], 'rate': 1}).json()
    headers = {'Accept': 'application/json, text/event-stream', 'Authorization': 'Bearer ' + limited['token']}
    body = {'jsonrpc': '2.0', 'id': 0, 'method': 'initialize', 'params': {
        'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 'limited', 'version': '1'}}}
    assert client.post('/mcp', json=body, headers=headers).status_code == 200
    assert client.post('/mcp', json=body, headers=headers).status_code == 429


def test_backup_restore_and_traversal(tmp_path):
    import io
    import tarfile

    from memory_center.service.maintenance import backup, restore
    data = tmp_path / 'data'
    with TestClient(create_service_app(ServiceConfig(data, auth_mode="token")), base_url='http://localhost'):
        from filelock import Timeout
        with pytest.raises(Timeout):
            backup(data, tmp_path / 'active.tar.gz')
    archive = tmp_path / 'backup.tar.gz'
    backup(data, archive)
    restored = tmp_path / 'restored'
    restore(archive, restored)
    assert (restored / 'admin-token').read_text() == (data / 'admin-token').read_text()
    assert archive.stat().st_mode & 0o077 == 0
    with TestClient(create_service_app(ServiceConfig(restored, auth_mode="token")), base_url='http://localhost') as client:
        assert client.get('/health/ready').status_code == 200
    with pytest.raises(ValueError):
        restore(archive, restored)
    bad = tmp_path / 'bad.tar.gz'
    with tarfile.open(bad, 'w:gz') as file:
        entry = tarfile.TarInfo('../escape')
        entry.size = 1
        file.addfile(entry, io.BytesIO(b'x'))
    with pytest.raises(ValueError, match='越界'):
        restore(bad, tmp_path / 'invalid')
    assert not (tmp_path / 'escape').exists()
