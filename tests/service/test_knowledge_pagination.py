"""项目知识与关联目录的统一分页合同。"""
import pytest

from test_platform import service  # noqa: F401


def test_large_library_pagination_scope_and_filters(service):
    client, headers, platform, spaces = service
    a, b = [s['workspace_id'] for s in spaces]
    stamp = '2026-01-01T00:00:00+00:00'
    with platform.store.db.connection(True) as connection:
        for i in range(1005):
            platform.store._put(connection, 'wiki', {
                'id': f'page_{i:04}', 'workspace_id': a, 'title': f'指南 {i:04}',
                'content': '正文', 'status': 'active', 'revision': 1, 'updated_at': stamp})
    platform.knowledge.wiki('admin', b, '别的项目秘密', '不可泄漏')
    platform.knowledge.wiki('admin', a, '100%_准确', '字符筛选')
    deleted = platform.knowledge.wiki('admin', a, '已移除', '已移除正文')
    platform.store.update('wiki', deleted['id'], {'status': 'deleted'})
    for source_id, source_status, linked in [('source_ok', 'active', [a]),
                                             ('source_paused', 'paused', [a]),
                                             ('source_other', 'active', [b])]:
        platform.store.create('wiki_source', {'id': source_id, 'name': source_id,
                                            'status': source_status, 'workspace_ids': linked})
        platform.store.create('wiki', {'workspace_id': source_id, 'title': source_id,
                                      'content': '只读来源', 'status': 'active', 'readonly': True,
                                      'relative_path': '指南/配置.md'})
    path = f'/api/v1/workspaces/{a}/knowledge/wiki'
    def get(**params):
        response = client.get(path, headers=headers, params={'page': 1, 'page_size': 50, **params})
        assert response.status_code == 200, response.text
        return response.json()
    first = get()
    assert first['total'] == 1007 and first['pages'] == 21
    assert len(first['items']) == 50
    ids = [i['id'] for p in range(1, 22) for i in get(page=p)['items']]
    assert len(ids) == len(set(ids)) == 1007
    assert get(page=999)['page'] == 21
    assert get(q='100%_')['total'] == 1
    assert get(q="' OR 1=1 --")['total'] == 0
    sourced = get(q='配置.md')
    assert sourced['total'] == 1
    assert sourced['items'][0]['source_name'] == 'source_ok'
    assert sourced['items'][0]['workspace_id'] == a
    assert get(q='秘密')['total'] == 0
    assert get(status='deleted')['total'] == 1
    assert get(q='不存在')['pages'] == 1
    assert 'total' not in client.get(path, headers=headers).json()  # 保持原读取合同
    for params in [{'page': 0}, {'page_size': 51}, {'status': 'invalid'}]:
        assert client.get(path, headers=headers, params={'page': 1, **params}).status_code == 422


@pytest.mark.parametrize('kind', ['document', 'memory'])
def test_pagination_kinds_and_page_after_removal(service, kind):
    client, headers, platform, spaces = service
    a = spaces[0]['workspace_id']
    for i in range(11):
        platform.store.create(kind, {'workspace_id': a, 'title': str(i), 'content': str(i),
                                     'status': 'pending' if kind == 'memory' else 'active'})
    path = f'/api/v1/workspaces/{a}/knowledge/{kind}'
    page = client.get(path, headers=headers, params={'page': 2, 'page_size': 10}).json()
    assert len(page['items']) == 1
    platform.store.update(kind, page['items'][0]['id'], {'status': 'deleted'})
    page = client.get(path, headers=headers, params={'page': 2, 'page_size': 10}).json()
    assert page['page'] == 1 and page['pages'] == 1 and page['total'] == 10
