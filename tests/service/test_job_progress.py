"""真实阶段计数、取消与可配置调度。"""
import asyncio
from types import SimpleNamespace

import pytest

from memory_center.core.foundation.catalog import CatalogError
from memory_center.core.foundation.models import ServiceConfig, WorkspaceConfig
from memory_center.platform.code_graph import build_code_graph
from memory_center.platform.database import Database
from memory_center.platform.jobs import JobProgress, Jobs, assign_services
from memory_center.platform.store import PlatformStore
from test_platform import service  # noqa: F401


def test_counts_and_cancellation(tmp_path):
    db = Database(tmp_path); db.initialize(); store = PlatformStore(db)
    job = store.create('job', {'status': 'running'})
    progress = JobProgress(store, job['id'])
    progress('scanning', 3, None)
    current = store.get('job', job['id'])
    assert current['total'] is None and current['completed'] == 3 and current['progress'] == 0
    progress('parsing', 2, 4)
    assert store.get('job', job['id'])['progress'] == 50
    progress('parsing', 4, 4)
    assert store.get('job', job['id'])['completed'] == 4
    store.update('job', job['id'], {'status': 'cancelled'})
    with pytest.raises(CatalogError):
        progress('relations', 0, 4)
    assert store.get('job', job['id'])['status'] == 'cancelled'


def test_graph_reports_real_file_counts(tmp_path):
    files = []
    for name in ['a.py', 'b.py']:
        path = tmp_path / name; path.write_text('def foo():\n    return 1\n'); files.append(path)
    calls = []
    graph = build_code_graph(tmp_path, files, lambda *args: calls.append(args))
    assert ('parsing', 2, 2, 'files') in calls
    assert ('relations', 2, 2, 'files') in calls
    assert len(graph['coverage']) == 2


def test_assignment_uses_most_specific_scope(tmp_path):
    config = WorkspaceConfig(workspace='test', root=str(tmp_path), services=[
        ServiceConfig(name='root', path='.'), ServiceConfig(name='child', path='sub')])
    paths = [tmp_path / 'a.py', tmp_path / 'sub' / 'b.py']
    assert assign_services(config, paths) == {'root': [str(paths[0])], 'child': [str(paths[1])]}


def test_settings_validation_and_queue_idempotency(service):
    client, headers, platform, spaces = service
    path = '/api/v1/job-settings'
    assert client.get(path, headers=headers).json()['max_queued'] == 0
    assert client.put(path, headers=headers, json={'max_projects': 0}).status_code == 422
    assert client.put(path, headers=headers, json={'max_projects': 3, 'max_queued': 1}).json()['max_projects'] == 3
    # 阻止真实调度消费队列，直接验证同项目去重及可选队列上限。
    with platform.jobs.lifecycle_lock:
        job = platform.jobs.enqueue(spaces[0]['workspace_id'], 'admin')
        assert platform.jobs.enqueue(spaces[0]['workspace_id'], 'admin')['id'] == job['id']
        with pytest.raises(CatalogError, match='上限'):
            platform.jobs.enqueue(spaces[1]['workspace_id'], 'admin')
        platform.jobs.cancel(job['id'])


@pytest.mark.parametrize(("cpu_budget", "expected"), [(2, 2), (4, 3)])
def test_scheduler_starts_configured_number_and_finds_old_queue(tmp_path, monkeypatch, cpu_budget, expected):
    monkeypatch.setattr('memory_center.platform.jobs.cpu_budget', lambda: cpu_budget)
    db = Database(tmp_path); db.initialize(); store = PlatformStore(db)
    workspaces = {f'w{i}': {'workspace_id': f'w{i}', 'status': 'active', 'config_version': 1} for i in range(5)}
    jobs = Jobs(store, SimpleNamespace(get=lambda key: workspaces[key]), tmp_path)
    jobs.configure({'max_projects': 3, 'max_queued': 0})
    for i in range(5):
        jobs.enqueue(f'w{i}', 'admin')
    # 超过旧的历史记录读取窗口，排队任务仍应被调度。
    with db.connection(True) as connection:
        for i in range(1001):
            store._put(connection, 'job', {'id': f'history{i}', 'status': 'succeeded', 'revision': 1})
    async def exercise():
        started = asyncio.Event()
        starts = 0

        class Process:
            alive = False
            def __init__(self, **kwargs): pass
            def start(self):
                nonlocal starts
                self.alive = True
                starts += 1
                if starts == expected:
                    started.set()
            def is_alive(self): return self.alive
            def terminate(self): self.alive = False
            def join(self, *args, **kwargs): pass
            def close(self): pass

        monkeypatch.setattr('multiprocessing.get_context', lambda *_: SimpleNamespace(Process=Process))
        task = asyncio.create_task(jobs.loop())
        try:
            await asyncio.wait_for(started.wait(), timeout=5)
            assert len(jobs.processes) == expected
            assert len([j for j in jobs.pending() if j['status'] == 'queued']) == 5 - expected
        finally:
            jobs.stopping = True
            await task
            await jobs.close()

    asyncio.run(exercise())
