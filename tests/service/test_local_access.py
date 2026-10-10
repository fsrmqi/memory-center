"""个人本机模式免认证，项目路由与浏览器来源边界继续有效。"""
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from memory_center.platform.governance import ASSISTANT_TOOLS
from memory_center.platform.security import WRITE_TOOLS
from memory_center.service.app import create_service_app
from memory_center.service.config import ServiceConfig
from tests.service.test_platform import call, mcp_connect


def test_local_management_and_dynamic_mcp_scope(tmp_path):
    with TestClient(create_service_app(ServiceConfig(tmp_path / 'data')), base_url='http://localhost') as client:
        assert client.get('/api/v1/service/status').json()['auth_mode'] == 'local'
        assert client.get('/api/v1/workspaces').status_code == 200
        headers = mcp_connect(client)
        listing = client.post('/mcp', headers=headers, json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}).json()
        assert {tool['name'] for tool in listing['result']['tools']} == WRITE_TOOLS | ASSISTANT_TOOLS
        assert call(client, headers, 'mc_workspaces', {})['structuredContent']['items'] == []
        spaces = []
        for name in ['a', 'b']:
            source = tmp_path / name
            source.mkdir()
            (source / 'pyproject.toml').write_text('[project]\nname="example"')
            res = client.post('/api/v1/workspaces', json={'name': name, 'root': str(source)})
            assert res.status_code == 201, res.text
            spaces.append(res.json()['workspace_id'])
        assert len(call(client, headers, 'mc_workspaces', {})['structuredContent']['items']) == 2
        started = call(client, headers, 'mc_start', {'workspace_id': spaces[0], 'intent': 'local session'})['structuredContent']
        assert call(client, headers, 'mc_lookup', {'workspace_id': spaces[1], 'query': 'example', 'session_id': started['id']})['isError']
        memory = call(client, headers, 'mc_memory_write', {'workspace_id': spaces[0], 'content': '明确事实', 'confirmed': True})
        assert not memory.get('isError') and memory['structuredContent']['workspace_id'] == spaces[0]
        assert not call(client, headers, 'mc_wiki_write', {'workspace_id': spaces[1], 'title': '说明', 'content': '内容'}).get('isError')
        assert not call(client, headers, 'mc_close', {'session_id': started['id'], 'outcome': 'done'}).get('isError')
        assert client.get('/api/v1/workspaces', headers={'Authorization': 'Bearer unused'}).status_code == 200


@pytest.mark.parametrize('origin', ['https://outside.example', 'null', 'http://127.0.0.1'])
def test_local_origin_and_host_guards(tmp_path, origin):
    with TestClient(create_service_app(ServiceConfig(tmp_path / 'data')), base_url='http://localhost') as client:
        assert client.get('/api/v1/workspaces', headers={'Origin': origin}).status_code in {403, 421}
        response = client.post('/mcp', headers={'Origin': origin, 'Accept': 'application/json,text/event-stream'},
                               json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'})
        assert response.status_code in {403, 421}
        assert client.get('/api/v1/workspaces', headers={'Host': 'outside.example'}).status_code in {403, 421}
        assert client.post('/mcp', headers={'Host': 'outside.example'}, json={}).status_code in {403, 421}
        assert client.post('/api/v1/models/test', content='plain').status_code in {400, 403}
        assert client.get('/api/v1/workspaces', headers={'Origin': 'http://localhost'}).status_code == 200


def test_local_listen_policy_and_cli(tmp_path):
    with pytest.raises(ValueError, match='只允许监听本机'):
        ServiceConfig(tmp_path, host='0.0.0.0')
    assert ServiceConfig(tmp_path, host='0.0.0.0', auth_mode='token')
    assert ServiceConfig(tmp_path, host='0.0.0.0', container_local=True)
    rejected = subprocess.run([sys.executable, '-m', 'memory_center.service.main', '--host', '0.0.0.0'],
                               capture_output=True, text=True, timeout=10)
    assert rejected.returncode == 2 and '只允许监听本机' in rejected.stderr
