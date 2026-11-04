"""Wiki 定时同步只能自动提交一次失败尝试，手动重试可恢复。"""
from types import SimpleNamespace

import pytest

from memory_center.platform.database import Database
from memory_center.platform.jobs import Jobs
from memory_center.platform.store import PlatformStore
from memory_center.platform.wiki_sources import WikiSources


@pytest.fixture
def jobs(tmp_path):
    db = Database(tmp_path)
    db.initialize()
    store = PlatformStore(db)
    catalog = SimpleNamespace(get=lambda wid: {'workspace_id': wid, 'status': 'active', 'config_version': 1})
    return Jobs(store, catalog, tmp_path)


def source(jobs, tmp_path, auto_sync=True):
    root = tmp_path / 'wiki'
    root.mkdir()
    (root / 'page.md').write_text('first version')
    return WikiSources(jobs.store, jobs.catalog).save('Wiki', str(root), ['demo'], auto_sync=auto_sync)


@pytest.mark.parametrize('status', ['failed', 'cancelled', 'interrupted'])
def test_terminal_attempt_stops_polls_restart_and_deletion(jobs, tmp_path, status):
    item = source(jobs, tmp_path)
    jobs.sync_wikis()
    first = jobs.pending()[0]
    jobs.store.update('job', first['id'], {'status': status})
    # Source changes must not silently resume a stopped project.
    (tmp_path / 'wiki/page.md').write_text('second version')
    for _ in range(3):
        jobs.sync_wikis()
    assert len(jobs.store.list('job')) == 1
    assert jobs.store.get('wiki_source', item['id'])['content_version'] == 2
    restarted = Jobs(jobs.store, jobs.catalog, jobs.data_dir)
    restarted.sync_wikis()
    assert restarted.pending() == []
    restarted.remove(first['id'])
    restarted.sync_wikis()
    assert restarted.store.list('job') == []
    manual = restarted.enqueue('demo', 'admin')
    assert manual['status'] == 'queued'
    restarted.sync_wikis()
    assert len(restarted.store.list('job')) == 1
    # A successful manual attempt re-enables indexing of later Wiki changes.
    signature = WikiSources(jobs.store).signature('demo')
    jobs.store.update('job', manual['id'], {'status': 'succeeded'})
    jobs.store.create('index', {'id': 'demo', 'wiki_signature': signature})
    restarted.sync_wikis()
    assert restarted.pending() == []
    (tmp_path / 'wiki/page.md').write_text('third version')
    restarted.sync_wikis()
    assert len(restarted.pending()) == 1


def test_existing_failed_job_before_upgrade_is_not_retried(jobs, tmp_path):
    source(jobs, tmp_path)
    old = jobs.store.create('job', {'workspace_id': 'demo', 'status': 'failed'})
    jobs.sync_wikis()
    assert jobs.pending() == []
    jobs.remove(old['id'])
    jobs.sync_wikis()
    assert jobs.store.list('job') == []


def test_disabled_or_paused_source_does_not_enqueue(jobs, tmp_path):
    item = source(jobs, tmp_path, auto_sync=False)
    jobs.sync_wikis()
    assert jobs.store.list('job') == []
    jobs.store.update('wiki_source', item['id'], {'status': 'paused', 'auto_sync': True})
    jobs.sync_wikis()
    assert jobs.store.list('job') == []


def test_pending_task_is_deduplicated(jobs, tmp_path):
    source(jobs, tmp_path)
    for _ in range(3):
        jobs.sync_wikis()
    assert len(jobs.pending()) == 1
    assert jobs.enqueue('demo', 'admin')['id'] == jobs.pending()[0]['id']
