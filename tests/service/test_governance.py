"""受管 Wiki、Skill 管理与统一 MCP 的真实闭环。"""
import hashlib

import pytest
from fastapi.testclient import TestClient

from memory_center.platform.governance import ASSISTANT_TOOLS
from memory_center.service.app import create_service_app
from memory_center.service.config import ServiceConfig
from tests.service.test_platform import call, mcp_connect


@pytest.fixture
def governance(tmp_path):
    root = tmp_path / 'source'
    root.mkdir()
    (root / 'guide.md').write_text('# 指南\n迁入标记 integrationevidence\n')
    (root / '模块注册表.md').write_text('| module | 位置 |\n| `personal` | `个人档案/` |\n')
    original = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir()}
    data = tmp_path / 'data'
    with TestClient(create_service_app(ServiceConfig(data)), base_url='http://localhost') as client:
        source = client.post('/api/v1/wiki-sources', json={'name': '原 Wiki', 'root': str(root), 'auto_sync': False}).json()
        yield client, source, root, data
    assert original == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir()}


def execute(client, tool, parameters):
    response = client.post('/api/v1/governance/' + tool, json={'parameters': parameters})
    assert response.status_code == 200, response.text
    return response.json()


def test_import_promote_archive_search_mcp(governance):
    client, source, root, data = governance
    payload = {'source_id': source['id']}
    assert client.post('/api/v1/governance/import', json=payload).json()['confirmed'] is False
    assert not (data / 'governance/wiki/guide.md').exists()
    payload['confirm'] = True
    response = client.post('/api/v1/governance/import', json=payload)
    assert response.status_code == 200, response.text
    assert client.post('/api/v1/governance/import', json=payload).status_code == 422
    assert execute(client, 'assistant_knowledge', {'action': 'search', 'query': 'integrationevidence'})['hits']
    p = {'action': 'promote', 'title': '长期知识', 'content': 'verifiedintegration 长期稳定结论', 'source': 'task:integration', 'module': 'personal'}
    preview = execute(client, 'assistant_memory', p)
    assert not preview['confirmed']
    assert not (data / 'governance/wiki' / preview['path']).exists()
    p['confirm'] = True
    assert execute(client, 'assistant_memory', p)['confirmed']
    assert execute(client, 'assistant_knowledge', {'action': 'search', 'query': 'verifiedintegration'})['hits']
    archive = {'action': 'archive', 'source_path': str(root / 'guide.md'), 'destination': '技术/归档', 'confirm': True}
    assert execute(client, 'assistant_memory', archive)['confirmed']
    headers = mcp_connect(client)
    listing = client.post('/mcp', headers=headers, json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}).json()
    assert ASSISTANT_TOOLS <= {t['name'] for t in listing['result']['tools']}
    result = call(client, headers, 'assistant_knowledge', {'action': 'brief', 'query': 'verifiedintegration'})
    assert not result.get('isError'), result
    assert execute(client, 'assistant_knowledge', {'action': 'read', 'path': preview['path']})['content']


def test_skill_full_lifecycle(governance):
    client, source, root, data = governance
    parameters = {'action': 'create', 'source_paths': [str(root / 'guide.md')], 'name': 'integration-skill',
                  'description': '用于根据指南核对项目的场景', 'body': '## 方法\n读取指南并核对事实。\n## 验证\n保留任务验证引用。'}
    preview = execute(client, 'assistant_skill', parameters)
    assert '## 方法' in preview['document'] and not preview['confirmed']
    assert not (data / 'governance/skill-candidates/integration-skill').exists()
    parameters['confirm'] = True
    assert execute(client, 'assistant_skill', parameters)['confirmed']
    assert execute(client, 'assistant_skill', {'action': 'validate', 'name': parameters['name']})['valid']
    assert execute(client, 'assistant_skill', {'action': 'inspect', 'name': parameters['name']})['body']
    missing = client.post('/api/v1/governance/assistant_skill', json={'parameters': {'action': 'publish', 'name': parameters['name']}})
    assert missing.status_code == 422
    pub = {'action': 'publish', 'name': parameters['name'], 'evidence_refs': ['memory-center:task:verified-test']}
    assert not execute(client, 'assistant_skill', pub)['confirmed']
    pub['confirm'] = True
    assert execute(client, 'assistant_skill', pub)['confirmed']
    assert execute(client, 'assistant_skill', {'action': 'published'})['items'][0]['name'] == parameters['name']
    assert 'SKILL.md' in execute(client, 'assistant_skill', {'action': 'export', 'name': parameters['name']})['files']
    removal = {'action': 'remove', 'name': parameters['name'], 'published': True, 'confirm': True}
    assert execute(client, 'assistant_skill', removal)['recoverable']
    assert not execute(client, 'assistant_skill', {'action': 'published'})['items']
    assert list((data / 'governance/trash').glob('*/integration-skill/SKILL.md'))


def test_unregistered_paths_and_traversal_rejected(governance, tmp_path):
    client, _, _, _ = governance
    outside = tmp_path / 'not-authorized.md'
    outside.write_text('不能读取')
    for params in [{'action': 'analyze', 'source_paths': [str(outside)]}, {'action': 'extract', 'workdir': str(tmp_path)},
                   {'action': 'create', 'name': '../escape'}]:
        response = client.post('/api/v1/governance/assistant_skill', json={'parameters': params})
        assert response.status_code == 422, response.text
    response = client.post('/api/v1/governance/assistant_knowledge', json={'parameters': {'action': 'read', 'path': '../platform.db'}})
    assert response.status_code == 422


def test_attachment_import_background_index_and_shutdown(tmp_path):
    import time

    from docx import Document

    source = tmp_path / 'attachments'
    source.mkdir()
    doc = Document()
    doc.add_paragraph('backgroundattachment verified')
    doc.save(source / 'source.docx')
    data = tmp_path / 'data'
    app = create_service_app(ServiceConfig(data))
    with TestClient(app, base_url='http://localhost') as client:
        entry = client.post('/api/v1/wiki-sources', json={'name': '附件', 'root': str(source), 'auto_sync': False}).json()
        response = client.post('/api/v1/governance/import', json={'source_id': entry['id'], 'confirm': True})
        assert response.status_code == 200, response.text
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            state = client.get('/api/v1/governance').json()['index_job']['state']
            if state == 'ready':
                break
            time.sleep(0.1)
        assert state == 'ready'
        assert execute(client, 'assistant_knowledge', {'action': 'search', 'query': 'backgroundattachment'})['hits']
    assert app.state.platform.governance.index_task.done()
    assert app.state.platform.governance.index_process.returncode == 0
