"""全局 Skill 发现的只读扫描、启停与新鲜度控制。"""
from pathlib import Path

from test_governance import governance  # noqa: F401
from test_platform import service  # noqa: F401


def test_discovery_controls_preserve_files(governance, tmp_path):
    client, _, _, _ = governance
    root = tmp_path / 'global-skills'
    root.mkdir()
    for i in range(25):
        folder = root / f'skill-{i:02}'
        folder.mkdir()
        (folder / 'SKILL.md').write_text(f'---\nname: skill-{i:02}\ndescription: 全局能力 {i}\n---\n# 使用方法\n只读验收\n')
    (root / 'alias').symlink_to(root / 'skill-00', target_is_directory=True)
    originals = {str(p): p.read_bytes() for p in root.glob('*/SKILL.md')}
    base = '/api/v1/governance'
    source = client.post(base + '/skill-sources', json={'name': '全局目录', 'root': str(root)}).json()
    assert not source['enabled']
    assert client.post(base + '/skill-sources/' + source['id'] + '/scan', json={}).status_code == 422
    def update_source(enabled):
        current = client.get(base + '/skill-sources').json()['items'][0]
        return client.patch(base + '/skill-sources/' + source['id'], json={
            'name': current['name'], 'root': current['root'], 'enabled': enabled,
            'max_depth': current['max_depth'], 'revision': current['revision']})
    assert update_source(True).status_code == 200
    result = client.post(base + '/skill-sources/' + source['id'] + '/scan', json={}).json()
    assert result['found'] == 25 and result['skipped_symlinks'] == 1
    listing = client.get(base + '/discovered-skills?page=1&page_size=10').json()
    assert listing['total'] == 25 and listing['pages'] == 3 and len(listing['items']) == 10
    assert all(i['status'] == 'disabled' for i in listing['items'])
    manager = client.app.state.platform.governance
    assert manager.call('assistant_skill', {'action': 'discovered'})['items'] == []
    item = listing['items'][0]
    route = base + '/discovered-skills/' + item['id']
    assert client.get(route).json()['body'].startswith('---')
    assert client.patch(route, json={'enabled': True, 'revision': item['revision']}).status_code == 200
    assert manager.call('assistant_skill', {'action': 'discovered'})['items'][0]['id'] == item['id']
    assert client.patch(route, json={'enabled': False, 'revision': item['revision']}).status_code == 409
    assert update_source(False).status_code == 200
    assert manager.call('assistant_skill', {'action': 'discovered'})['items'] == []
    assert client.get(route).status_code == 422
    assert update_source(True).status_code == 200
    assert manager.call('assistant_skill', {'action': 'discovered_read', 'name': item['id']})['body']
    path = root / item['relative_path']
    path.write_text(path.read_text() + '\n内容更新\n')
    assert client.get(route).status_code == 422
    client.post(base + '/skill-sources/' + source['id'] + '/scan', json={})
    assert manager.call('assistant_skill', {'action': 'discovered'})['items'] == []
    current = client.get(base + '/discovered-skills', params={'q': item['name']}).json()['items'][0]
    assert current['status'] == 'disabled' and current['revision'] > item['revision']
    # 读取失败不会用不完整扫描替换上次完整快照。
    broken = root / 'broken'
    broken.mkdir()
    (broken / 'SKILL.md').write_bytes(b'\xff')
    assert client.post(base + '/skill-sources/' + source['id'] + '/scan', json={}).status_code == 422
    assert client.get(base + '/discovered-skills').json()['total'] == 25
    (broken / 'SKILL.md').unlink()
    path.unlink()
    client.post(base + '/skill-sources/' + source['id'] + '/scan', json={})
    assert client.get(route).status_code == 422
    assert client.get(base + '/discovered-skills?status=missing').json()['total'] == 1
    for p, body in originals.items():
        if Path(p) != path and Path(p).is_file():
            assert Path(p).read_bytes() == body
    current_source = client.get(base + '/skill-sources').json()['items'][0]
    assert client.delete(base + '/skill-sources/' + source['id'], params={'revision': current_source['revision']}).status_code == 200
    assert client.get(base + '/discovered-skills').json()['total'] == 0
    assert (root / 'skill-00/SKILL.md').is_file() or path.parent.name == 'skill-00'


def test_discovery_depth_and_source_validation(governance, tmp_path):
    client, _, _, _ = governance
    root = tmp_path / 'depth'
    folder = root / 'one/two'
    folder.mkdir(parents=True)
    (folder / 'SKILL.md').write_text('# Skill')
    base = '/api/v1/governance/skill-sources'
    for body in [{'name': 'bad', 'root': 'relative'}, {'name': 'bad', 'root': str(root), 'max_depth': 9}]:
        assert client.post(base, json=body).status_code == 422
    source = client.post(base, json={'name': '浅目录', 'root': str(root), 'enabled': True, 'max_depth': 1}).json()
    assert client.post(base + '/' + source['id'] + '/scan', json={}).json()['found'] == 0
    assert client.post(base, json={'name': '重复', 'root': str(root)}).status_code == 422
    assert client.patch(base + '/' + source['id'], json={'name': '浅目录', 'root': str(root)}).status_code == 422


def test_jobs_pagination_beyond_old_cap(service):
    client, headers, platform, spaces = service
    a, b = [s['workspace_id'] for s in spaces]
    with platform.store.db.connection(True) as connection:
        for i in range(1105):
            platform.store._put(connection, 'job', {'id': f'job_test_{i:04}', 'workspace_id': a,
                                'status': 'succeeded', 'progress': 100, 'revision': 1})
        platform.store._put(connection, 'job', {'id': 'job_other', 'workspace_id': b,
                            'status': 'failed', 'progress': 0, 'revision': 1})
    path = '/api/v1/jobs'
    first = client.get(path, headers=headers, params={'page': 1, 'page_size': 50}).json()
    assert first['total'] == 1106 and first['pages'] == 23 and len(first['items']) == 50
    last = client.get(path, headers=headers, params={'page': 999, 'page_size': 50}).json()
    assert last['page'] == 23 and len(last['items']) == 6
    scoped = client.get(path, headers=headers, params={'page': 1, 'workspace_id': a, 'status': 'failed'}).json()
    assert scoped['total'] == 0
    assert client.get(path, headers=headers, params={'page': 1, 'status': 'failed'}).json()['total'] == 1
    assert 'total' not in client.get(path, headers=headers).json()


def test_global_skills_not_implicitly_managed(governance, tmp_path):
    client, _, _, _ = governance
    root = tmp_path / 'external'
    folder = root / 'existing-skill'
    folder.mkdir(parents=True)
    original = '# 外部能力\n原目录保持不变'
    (folder / 'SKILL.md').write_text(original)
    manager = client.app.state.platform.governance
    manager.published = root
    assert manager.call('assistant_skill', {'action': 'published'})['items'] == []
    for action in ['read', 'remove']:
        response = client.post('/api/v1/governance/assistant_skill', json={'parameters': {
            'action': action, 'name': 'existing-skill', 'published': True, 'confirm': True}})
        assert response.status_code == 422
    assert (folder / 'SKILL.md').read_text() == original


def test_discovery_requires_administrator(service):
    client, headers, _, spaces = service
    cred = client.post('/api/v1/credentials', headers=headers, json={
        'name': 'limited', 'workspace_ids': [spaces[0]['workspace_id']]}).json()
    for route in ['/api/v1/governance/skill-sources', '/api/v1/governance/discovered-skills']:
        assert client.get(route).status_code == 401
        assert client.get(route, headers={'Authorization': 'Bearer '+cred['token']}).status_code == 401
