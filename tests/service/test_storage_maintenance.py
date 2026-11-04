"""存储治理验收：项目隔离、预览门禁、缓存与在途代际保护。"""
import json

import pytest

from memory_center.core.foundation.catalog import CatalogError
from memory_center.platform.storage_maintenance import StorageMaintenance
from tests.service.test_platform import service  # noqa: F401


def generations(platform, workspace_id):
    root = platform.store.db.data_dir / 'workspaces' / workspace_id
    for name, size in (('current', 40), ('older', 30), ('newer', 20), ('failed', 10)):
        directory = root / 'generations' / name
        directory.mkdir(parents=True)
        (directory / 'index.bin').write_bytes(b'x' * size)
        platform.store.create('job', {'id': name+'_'+workspace_id, 'workspace_id': workspace_id,
                                    'status': 'failed' if name == 'failed' else 'succeeded',
                                    'finished_at': {'current': '3', 'newer': '2', 'older': '1', 'failed': '4'}[name]})
        # 目录名称与真实任务 ID 必须对应。
        directory.rename(directory.with_name(name+'_'+workspace_id))
    platform.store.create('index', {'id': workspace_id, 'workspace_id': workspace_id,
                                    'generation': 'current_'+workspace_id, 'config_version': 1})
    return root


def test_retention_preview_confirm_and_scope(service):
    client, headers, platform, spaces = service
    a, b = [s['workspace_id'] for s in spaces]
    root, foreign = generations(platform, a), generations(platform, b)
    service = StorageMaintenance(platform)
    settings = client.get(f'/api/v1/workspaces/{a}/storage-policy', headers=headers).json()
    assert settings['keep_history'] == 2 and settings['revision'] == 0
    policy = client.put(f'/api/v1/workspaces/{a}/storage-policy', headers=headers,
                       json={'keep_history': 1, 'revision': 0}).json()
    assert policy['revision'] == 1
    stale = client.put(f'/api/v1/workspaces/{a}/storage-policy', headers=headers,
                       json={'keep_history': 0, 'revision': 0})
    assert stale.json()['error']['code'] == 'REVISION_CONFLICT'
    preview = client.post(f'/api/v1/workspaces/{a}/storage-cleanup/preview', headers=headers, json={}).json()
    assert preview['bytes'] == 40
    assert preview['retained_history'] == ['newer_'+a]
    assert (root/'generations'/('older_'+a)).exists()  # 预览不删除。
    payload = {'preview_id': preview['id'], 'revision': preview['revision']}
    rejected = client.post(f'/api/v1/workspaces/{a}/storage-cleanup/apply', headers=headers, json=payload)
    assert rejected.json()['error']['code'] == 'CONFIRM_REQUIRED'
    foreign_apply = client.post(f'/api/v1/workspaces/{b}/storage-cleanup/apply', headers=headers,
                               json=dict(payload, confirm=True))
    assert foreign_apply.json()['error']['code'] == 'FORBIDDEN'
    result = client.post(f'/api/v1/workspaces/{a}/storage-cleanup/apply', headers=headers,
                         json=dict(payload, confirm=True)).json()
    assert result['status'] == 'succeeded' and result['freed_bytes'] == 40
    assert (root/'generations'/('current_'+a)).exists() and (root/'generations'/('newer_'+a)).exists()
    assert len(list((foreign/'generations').iterdir())) == 4
    assert platform.store.get('job', 'failed_'+a)['status'] == 'failed'  # 不删历史记录。
    with pytest.raises(CatalogError):
        service.apply(a, preview['id'], preview['revision'], True)


@pytest.mark.parametrize('change', ['file', 'policy', 'active', 'job'])
def test_changed_preview_refused(service, change):
    _, _, platform, spaces = service
    a = spaces[0]['workspace_id']
    root = generations(platform, a)
    maintenance = StorageMaintenance(platform)
    preview = maintenance.preview(a)
    if change == 'file':
        (root/'generations'/('failed_'+a)/'new-file').write_bytes(b'changed')
    elif change == 'policy':
        maintenance.configure(a, 0, 0)
    elif change == 'active':
        platform.store.update('index', a, {'generation': 'failed_'+a})
    else:
        platform.store.create('job', {'id': 'waiting_'+a, 'workspace_id': a, 'status': 'running'})
    with pytest.raises(CatalogError) as exc:
        maintenance.apply(a, preview['id'], preview['revision'], True)
    assert exc.value.code == 'STORAGE_PREVIEW_STALE'
    assert (root/'generations'/('failed_'+a)).exists()


def test_cache_clear_busy_and_symlink_guard(service):
    _, _, platform, spaces = service
    a = spaces[0]['workspace_id']
    root = generations(platform, a)
    for name in ('parse-cache','embedding-cache'):
        (root/name).mkdir()
        (root/name/'cache').write_bytes(b'cache')
    maintenance = StorageMaintenance(platform)
    job = platform.store.create('job', {'workspace_id': a, 'status': 'running'})
    with pytest.raises(CatalogError) as exc:
        maintenance.preview(a, True, True)
    assert exc.value.code == 'STORAGE_BUSY'
    platform.store.update('job', job['id'], {'status': 'cancelled'})
    preview = maintenance.preview(a, True, True)
    result = maintenance.apply(a, preview['id'], preview['revision'], True)
    assert result['freed_bytes'] == 20
    assert not (root/'parse-cache').exists() and not (root/'embedding-cache').exists()
    target = platform.store.db.data_dir/'private'
    target.mkdir()
    (target/'keep').write_bytes(b'keep')
    (root/'parse-cache').symlink_to(target, target_is_directory=True)
    with pytest.raises(CatalogError) as exc:
        maintenance.preview(a, True)
    assert exc.value.code == 'STORAGE_UNSAFE'
    assert (target/'keep').read_bytes() == b'keep'


def test_expired_and_partial_cleanup_not_replayed(service, monkeypatch):
    _, _, platform, spaces = service
    a = spaces[0]['workspace_id']
    generations(platform, a)
    maintenance = StorageMaintenance(platform)
    maintenance.configure(a, 0, 0)
    preview = maintenance.preview(a)
    platform.store.update('storage_cleanup_preview', preview['id'], {'expires_at': '2000-01-01T00:00:00+00:00'})
    with pytest.raises(CatalogError):
        maintenance.apply(a, preview['id'], preview['revision']+1, True)
    preview = maintenance.preview(a)
    import shutil
    original = shutil.rmtree
    calls = []

    def partial(path):
        calls.append(path)
        if len(calls) == 2:
            raise PermissionError('fixture')
        return original(path)

    monkeypatch.setattr(shutil, 'rmtree', partial)
    result = maintenance.apply(a, preview['id'], preview['revision'], True)
    assert result['status'] == 'partial' and len(result['removed']) == 1
    assert platform.store.get('storage_cleanup_preview', preview['id'])['status'] == 'partial'
    with pytest.raises(CatalogError):
        maintenance.apply(a, preview['id'], preview['revision'], True)


def test_pending_beyond_history_limit_is_protected(service):
    _, _, platform, spaces = service
    a = spaces[0]['workspace_id']
    root = generations(platform, a)
    with platform.store.db.connection(True) as connection:
        for i in range(1001):
            platform.store._put(connection, 'job', {'id': 'busy_'+str(i), 'workspace_id': a, 'status': 'running'})
    (root/'generations'/'busy_0').mkdir()
    (root/'generations'/'busy_1000').mkdir()
    preview = StorageMaintenance(platform).preview(a)
    assert 'busy_0' in preview['protected'] and 'busy_1000' in preview['protected']
    assert len(preview['protected']) == 1004
    assert preview['bytes'] == 10
