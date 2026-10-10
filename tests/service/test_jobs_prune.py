"""后台任务删除、旧索引清理与 Skill 内容读取的服务级验证。"""
import time

import pytest

from memory_center.core.foundation.catalog import CatalogError
from memory_center.platform.assistant import core as assistant_core
from tests.service.test_platform import service as service  # noqa: F401


def wait_job(platform, job):
    for _ in range(200):
        result = platform.store.get('job', job['id'])
        if result['status'] not in {'queued', 'running'}:
            assert result['status'] == 'succeeded', result
            return result
        time.sleep(.1)
    pytest.fail('索引任务未及时完成')


def test_remove_terminal_job_deletes_record(service):
    client, admin, platform, spaces = service
    a = spaces[0]['workspace_id']
    job = platform.store.create('job', {'workspace_id': a, 'owner': 'admin', 'status': 'cancelled', 'progress': 0})
    response = client.delete('/api/v1/jobs/' + job['id'], headers=admin)
    assert response.status_code == 200, response.text
    assert response.json() == {'id': job['id'], 'deleted': True, 'removed_generation': False, 'freed_bytes': 0}
    with pytest.raises(CatalogError) as exc:
        platform.store.get('job', job['id'])
    assert exc.value.code == 'RECORD_NOT_FOUND'


def test_remove_active_job_rejected(service):
    client, admin, platform, spaces = service
    a = spaces[0]['workspace_id']
    for status in ['queued', 'running']:
        job = platform.store.create('job', {'workspace_id': a, 'owner': 'admin', 'status': status, 'progress': 0})
        with pytest.raises(CatalogError) as exc:
            platform.jobs.remove(job['id'])
        assert exc.value.code == 'JOB_STATE'
        # 拒绝删除后记录与状态原样保留。
        assert platform.store.get('job', job['id'])['status'] == status
        rejected = client.delete('/api/v1/jobs/' + job['id'], headers=admin)
        assert rejected.status_code == 422 and rejected.json()['error']['code'] == 'JOB_STATE'


def test_remove_active_generation_rejected(service):
    client, admin, platform, spaces = service
    a = spaces[0]['workspace_id']
    job = platform.store.create('job', {'workspace_id': a, 'owner': 'admin', 'status': 'succeeded', 'progress': 100})
    platform.store.create('index', {'id': a, 'workspace_id': a, 'generation': job['id'],
                                    'workspace_file': '', 'revision': 1})
    with pytest.raises(CatalogError) as exc:
        platform.jobs.remove(job['id'])
    assert exc.value.code == 'JOB_ACTIVE'
    # 活跃索引任务被保护，记录仍存在。
    assert platform.store.get('job', job['id'])['id'] == job['id']
    rejected = client.delete('/api/v1/jobs/' + job['id'], headers=admin)
    assert rejected.status_code == 422 and rejected.json()['error']['code'] == 'JOB_ACTIVE'


def test_prune_keeps_active_generation_and_frees_space(service):
    client, admin, platform, spaces = service
    a = spaces[0]['workspace_id']
    generations = platform.jobs.data_dir / 'workspaces' / a / 'generations'
    active = generations / 'gen-active'
    active.mkdir(parents=True)
    (active / 'workspace.yaml').write_text('active generation', encoding='utf-8')
    stale_one = generations / 'gen-stale-one'
    stale_one.mkdir()
    (stale_one / 'code-graph.json').write_text('x' * 2048, encoding='utf-8')
    stale_two = generations / 'gen-stale-two'
    stale_two.mkdir()
    (stale_two / 'blob.bin').write_bytes(b'y' * 1024)
    # 越界符号链接不得被跟随，其指向内容不计入释放字节。
    outside = platform.jobs.data_dir / 'outside.txt'
    outside.write_bytes(b'z' * 4096)
    (stale_two / 'link.txt').symlink_to(outside)
    platform.store.create('index', {'id': a, 'workspace_id': a, 'generation': 'gen-active',
                                    'config_version': spaces[0]['config_version'], 'revision': 1})

    response = client.post(f'/api/v1/workspaces/{a}/prune-index', headers=admin, json={})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['removed'] == 2
    assert body['freed_bytes'] == 2048 + 1024
    assert body['kept'] == ['gen-active']
    assert body['workspaces'] == 1
    assert sorted(p.name for p in generations.iterdir()) == ['gen-active']
    assert outside.read_bytes() == b'z' * 4096

    # 全量 prune 幂等：活跃代际保留，已无垃圾可删。
    full = client.post('/api/v1/jobs/prune', headers=admin, json={})
    assert full.status_code == 200, full.text
    assert full.json()['removed'] == 0
    assert 'gen-active' in full.json()['kept']


def test_prune_removes_unindexed_workspace_generations(service):
    client, admin, platform, spaces = service
    a = spaces[0]['workspace_id']
    generations = platform.jobs.data_dir / 'workspaces' / a / 'generations'
    (generations / 'orphan').mkdir(parents=True)
    (generations / 'orphan' / 'code-graph.json').write_text('data', encoding='utf-8')
    # 未发布任何索引时，所有 generation 都是垃圾。
    result = platform.jobs.prune(a)
    assert result['removed'] == 1 and 'orphan' not in result['kept']
    assert not (generations / 'orphan').exists()


def test_prune_preserves_running_job_generation(service):
    client, admin, platform, spaces = service
    a = spaces[0]['workspace_id']
    generations = platform.jobs.data_dir / 'workspaces' / a / 'generations'
    # 无 index 记录（active=None）但存在运行中任务：其 generation 目录必须保留。
    running = platform.store.create('job', {'workspace_id': a, 'owner': 'admin', 'status': 'running', 'progress': 20})
    live = generations / running['id']
    live.mkdir(parents=True)
    (live / 'code-graph.json').write_text('active worker output', encoding='utf-8')
    stale = generations / 'gen-stale'
    stale.mkdir()
    (stale / 'code-graph.json').write_text('x' * 4096, encoding='utf-8')

    result = platform.jobs.prune(a)
    assert result['kept'] == [running['id']]
    assert result['removed'] == 1
    assert result['freed_bytes'] == 4096
    assert live.is_dir() and (live / 'code-graph.json').read_text() == 'active worker output'
    assert not stale.exists()
    assert platform.store.get('job', running['id'])['status'] == 'running'


def test_skill_read_returns_body_and_rejects_bad_name(service):
    client, admin, platform, spaces = service
    governance = platform.governance
    skill = governance.published / 'demo-skill'
    (skill / 'references').mkdir(parents=True)
    (skill / 'SKILL.md').write_text('# Demo\n\nskillreadbody 正文内容', encoding='utf-8')
    (skill / 'publication.json').write_text('{"state":"published"}', encoding='utf-8')
    (skill / 'references/notes.md').write_text('referencetext', encoding='utf-8')

    response = client.post('/api/v1/governance/assistant_skill', headers=admin,
                           json={'parameters': {'action': 'read', 'name': 'demo-skill', 'published': True}})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['name'] == 'demo-skill' and body['published'] is True
    assert 'skillreadbody' in body['body']
    assert body['publication'] == {'state': 'published'}
    assert set(body['files']) == {'SKILL.md', 'publication.json', 'references/notes.md'}

    # 候选目录不存在同名 Skill → 明确失败。
    with pytest.raises(CatalogError) as exc:
        governance.skill_lifecycle({'action': 'read', 'name': 'no-such-skill'})
    assert exc.value.code == 'SKILL_NOT_FOUND'
    # 非法名称（路径穿越）在到达文件系统前被 _safe_name 拒绝。
    with pytest.raises(assistant_core.WikiError):
        governance.skill_lifecycle({'action': 'read', 'name': '../escape', 'published': True})
