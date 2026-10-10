"""真实目录、事务增量同步、共享检索和只读边界验证。"""
import time

import pytest

from memory_center.core.foundation.catalog import CatalogError
from tests.service.test_platform import call, credential, mcp_connect
from tests.service.test_platform import service as service  # noqa: F401


def register(client, headers, root, spaces=(), name='技术 Wiki', auto_sync=False):
    response = client.post('/api/v1/wiki-sources', headers=headers,
                           json={'name': name, 'root': str(root), 'workspace_ids': list(spaces), 'auto_sync': auto_sync})
    assert response.status_code == 201, response.text
    return response.json()


def wait_job(platform, job):
    for _ in range(200):
        result = platform.store.get('job', job['id'])
        if result['status'] not in {'queued', 'running'}:
            assert result['status'] == 'succeeded', result
            return result
        time.sleep(.1)
    pytest.fail('Wiki 索引任务未及时完成')


def test_multi_directory_shared_search_and_refs(service, tmp_path):
    client, headers, platform, spaces = service
    a, b = [s['workspace_id'] for s in spaces]
    first, second = tmp_path / 'wiki-one', tmp_path / 'wiki-two'
    for root in [first, second]:
        (root / 'guide').mkdir(parents=True)
    (first / 'guide/start.md').write_text('# 启动\nsharedwikifirst 共用来源', encoding='utf-8')
    (second / 'guide/start.md').write_text('# 启动\nsecondwikionly 第二目录', encoding='utf-8')
    one = register(client, headers, first, [a, b])
    two = register(client, headers, second, [a], '第二 Wiki')
    for source in [one, two]:
        response = client.post('/api/v1/wiki-sources/' + source['id'] + '/sync', headers=headers, json={})
        assert response.status_code == 200, response.text
    # 若同步期间已有索引，下一轮持久快照检查必须重新排队。
    for workspace in [a, b]:
        wait_job(platform, platform.jobs.enqueue(workspace, 'admin'))
    platform.jobs.sync_wikis()
    for workspace in [a, b]:
        wait_job(platform, platform.jobs.enqueue(workspace, 'admin'))
    actor = platform.administrator()
    hit = platform.lookup(actor, a, 'sharedwikifirst', 'keyword')
    assert hit['items'] and hit['items'][0]['source']['wiki_source_id'] == one['id']
    assert hit['items'][0]['source']['relative_path'] == 'guide/start.md'
    assert hit['items'][0]['freshness'] == 'CURRENT'
    assert platform.lookup(actor, b, 'sharedwikifirst', 'keyword')['items']
    assert platform.lookup(actor, b, 'secondwikionly', 'keyword')['items'] == []
    assert platform.resolve_reference(actor, hit['ref_id'])
    (first / 'guide/start.md').write_text('# 启动\nchangedwikicontent', encoding='utf-8')
    assert platform.lookup(actor, a, 'sharedwikifirst', 'keyword')['items'][0]['freshness'] == 'STALE'
    with pytest.raises(CatalogError, match='Wiki 文件'):
        platform.resolve_reference(actor, hit['ref_id'])
    page = next(p for _, p in platform.knowledge.active(a) if p.get('wiki_source_id') == one['id'])
    response = client.patch(f'/api/v1/workspaces/{a}/wiki/{page["id"]}', headers=headers,
                            json={'title': '不可写', 'content': '不可写', 'revision': page['revision']})
    assert response.status_code == 422 and response.json()['error']['code'] == 'WIKI_READ_ONLY'
    mcp_headers = mcp_connect(client, credential(client, headers, [a])['token'])
    assert call(client, mcp_headers, 'mc_wiki_write', {'workspace_id': a, 'title': '不可写', 'content': '不可写',
                'record_id': page['id'], 'revision': page['revision']})['isError']
    assert 'changedwikicontent' in (first / 'guide/start.md').read_text()


def test_incremental_sync_delete_restore_and_failure(service, tmp_path):
    client, headers, platform, spaces = service
    a = spaces[0]['workspace_id']
    root = tmp_path / 'wiki'
    root.mkdir()
    page = root / 'page.md'
    page.write_text('# 原文\nfirstversion', encoding='utf-8')
    source = register(client, headers, root, [a])
    sources = platform.wiki_sources
    first = sources.sync(source['id'])
    identifier = next(sources.pages(a))['id']
    revision = next(sources.pages(a))['revision']
    unchanged = sources.sync(source['id'])
    assert unchanged['last_result'] == {'added': 0, 'updated': 0, 'deleted': 0, 'unchanged': 1}
    assert unchanged['content_version'] == first['content_version']
    assert next(sources.pages(a))['revision'] == revision
    page.write_text('# 原文\nsecondversion', encoding='utf-8')
    assert sources.sync(source['id'])['last_result']['updated'] == 1
    assert next(sources.pages(a))['id'] == identifier
    broken = root / 'broken.md'
    broken.write_bytes(b'\xff\xff')
    with pytest.raises(CatalogError):
        sources.sync(source['id'])
    assert next(sources.pages(a))['content'].endswith('secondversion')
    assert sources.store.get('wiki_source', source['id'])['sync_state'] == 'failed'
    broken.unlink()
    page.unlink()
    assert sources.sync(source['id'])['last_result']['deleted'] == 1
    assert list(sources.pages(a)) == []
    page.write_text('restoredversion', encoding='utf-8')
    sources.sync(source['id'])
    assert next(sources.pages(a))['id'] == identifier
    root.rename(tmp_path / 'offline')
    with pytest.raises(CatalogError):
        sources.sync(source['id'])
    assert next(sources.pages(a))['content'] == 'restoredversion'
    # 挂载失效时仍可暂停来源，不要求失效目录重新可读。
    current = sources.store.get('wiki_source', source['id'])
    response = client.patch('/api/v1/wiki-sources/' + source['id'], headers=headers,
                            json={k: current[k] for k in ['name', 'root', 'workspace_ids', 'revision']} | {'status': 'paused'})
    assert response.status_code == 200, response.text
    assert list(sources.pages(a)) == []


def test_independent_registration_association_and_removal(service, tmp_path):
    client, headers, platform, spaces = service
    a, b = [s['workspace_id'] for s in spaces]
    root = tmp_path / 'independent'
    root.mkdir()
    (root / 'wiki.markdown').write_text('independentwikicontent', encoding='utf-8')
    source = register(client, headers, root)
    current = platform.wiki_sources.sync(source['id'])
    assert current['page_count'] == 1 and list(platform.wiki_sources.pages(a)) == []
    response = client.patch('/api/v1/wiki-sources/' + source['id'], headers=headers,
                            json={k: current[k] for k in ['name', 'root', 'revision']} | {'workspace_ids': [a, b]})
    assert response.status_code == 200
    assert len(list(platform.wiki_sources.pages(a))) == len(list(platform.wiki_sources.pages(b))) == 1
    assert client.delete('/api/v1/wiki-sources/' + source['id'], headers=headers).status_code == 200
    assert not list(platform.wiki_sources.pages(a))
    assert (root / 'wiki.markdown').read_text() == 'independentwikicontent'


def test_scan_budget_symlinks_and_duplicate_sources(service, tmp_path):
    client, headers, platform, spaces = service
    a = spaces[0]['workspace_id']
    root = tmp_path / 'bounded'
    root.mkdir()
    (root / 'good.md').write_text('withinbudget', encoding='utf-8')
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'private.md').write_text('mustnotimport', encoding='utf-8')
    (root / 'escape.md').symlink_to(outside / 'private.md')
    (root / 'linked').symlink_to(outside, target_is_directory=True)
    (root / '.hidden').mkdir()
    (root / '.hidden/page.md').write_text('hidden')
    source = register(client, headers, root, [a])
    assert platform.wiki_sources.sync(source['id'])['page_count'] == 1
    response = client.post('/api/v1/wiki-sources', headers=headers,
                           json={'name': '重复', 'root': str(root), 'workspace_ids': []})
    assert response.status_code == 409
    (root / 'large.md').write_bytes(b'x' * (1024 * 1024 + 1))
    with pytest.raises(CatalogError, match='同步失败'):
        platform.wiki_sources.sync(source['id'])
    assert [p['relative_path'] for p in platform.wiki_sources.pages(a)] == ['good.md']
    assert client.post('/api/v1/wiki-sources', headers=headers,
                       json={'name': '相对', 'root': 'relative', 'workspace_ids': []}).status_code == 422


def test_auto_sync_rebuild_and_paused_source_visibility(service, tmp_path):
    client, headers, platform, spaces = service
    a = spaces[0]['workspace_id']
    root = tmp_path / 'automatic'
    root.mkdir()
    file = root / 'page.md'
    file.write_text('autosyncfirst', encoding='utf-8')
    source = register(client, headers, root, [a], auto_sync=True)
    platform.jobs.sync_wikis()
    wait_job(platform, platform.jobs.enqueue(a, 'admin'))
    assert platform.lookup(platform.administrator(), a, 'autosyncfirst', 'keyword')['items']
    file.write_text('autosyncsecond', encoding='utf-8')
    platform.jobs.sync_wikis()
    wait_job(platform, platform.jobs.enqueue(a, 'admin'))
    assert platform.lookup(platform.administrator(), a, 'autosyncsecond', 'keyword')['items']
    assert not platform.lookup(platform.administrator(), a, 'autosyncfirst', 'keyword')['items']
    current = platform.store.get('wiki_source', source['id'])
    platform.wiki_sources.save(current['name'], current['root'], [a], current['id'], current['revision'], status='paused')
    assert not platform.lookup(platform.administrator(), a, 'autosyncsecond', 'keyword')['items']
    # 目录仍存在、原文件仍保持最新正文。
    assert file.read_text() == 'autosyncsecond'
