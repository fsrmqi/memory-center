"""发布/清理并发、取消回收与项目级分析配置回归。"""
import threading

import pytest

from memory_center.core.foundation.catalog import CatalogError
from memory_center.platform.jobs import IndexLimits, scan_source_files
from tests.service.test_jobs_prune import wait_job
from tests.service.test_platform import service as service  # noqa: F401


def test_default_scan_accepts_file_above_old_limit(tmp_path):
    path = tmp_path / 'large.sql'
    with path.open('wb') as file:
        file.truncate(65 * 1024 ** 2)
    assert scan_source_files(tmp_path, IndexLimits.from_env({})) == [path]
    with pytest.raises(CatalogError, match='软上限'):
        scan_source_files(tmp_path, IndexLimits(max_file_bytes=64 * 1024 ** 2))


def test_cancelled_worker_reaped_before_record_removal(service):
    client, headers, platform, spaces = service
    wid = spaces[0]['workspace_id']
    job = platform.store.create('job', {'workspace_id': wid, 'status': 'cancelled'})

    class Worker:
        alive = True
        closed = False

        def is_alive(self):
            return self.alive

        def terminate(self):
            self.alive = False

        def join(self, timeout):
            assert not self.alive

        def close(self):
            self.closed = True

    worker = Worker()
    with platform.jobs.lifecycle_lock:
        platform.jobs.processes[job['id']] = worker
        platform.jobs.remove(job['id'])
    assert worker.closed and job['id'] not in platform.jobs.processes
    # 删除后继续通过真实调度器创建/完成新任务，不能只检查取消记录已消失。
    queued = client.post(f'/api/v1/workspaces/{wid}/index', headers=headers, json={}).json()
    assert wait_job(platform, queued)['status'] == 'succeeded'
    assert not platform.jobs.task.done()


def test_prune_serializes_with_atomic_publication(service, monkeypatch):
    client, headers, platform, spaces = service
    wid = spaces[0]['workspace_id']
    store = platform.store
    old = store.create('job', {'workspace_id': wid, 'status': 'succeeded'})
    new = store.create('job', {'workspace_id': wid, 'status': 'running'})
    directory = platform.jobs.data_dir / 'workspaces' / wid / 'generations'
    for job in [old, new]:
        (directory / job['id']).mkdir(parents=True)
        (directory / job['id'] / 'workspace.yaml').write_text('fixture')
    store.create('index', {'id': wid, 'workspace_id': wid, 'generation': old['id']})
    attempted = threading.Event()
    errors = []

    def publish():
        attempted.set()
        try:
            store.publish(wid, new['id'], [], str(directory / new['id'] / 'workspace.yaml'), 1)
        except Exception as error:
            errors.append(error)

    original = store.get
    publisher = threading.Thread(target=publish)

    def get(kind, record_id):
        result = original(kind, record_id)
        if kind == 'index' and record_id == wid and not attempted.is_set():
            publisher.start()
            assert attempted.wait(3)
        return result

    monkeypatch.setattr(store, 'get', get)
    platform.jobs.prune(wid)
    publisher.join(timeout=5)
    assert not publisher.is_alive() and not errors
    assert original('index', wid)['generation'] == new['id']
    assert (directory / new['id'] / 'workspace.yaml').is_file()


def test_removal_failure_keeps_job_record(service, monkeypatch):
    _, _, platform, spaces = service
    job = platform.store.create('job', {'workspace_id': spaces[0]['workspace_id'], 'status': 'cancelled'})
    path = platform.jobs.data_dir / 'workspaces' / job['workspace_id'] / 'generations' / job['id']
    path.mkdir(parents=True)

    def denied(*args, **kwargs):
        raise PermissionError('fixture')

    monkeypatch.setattr('memory_center.platform.jobs.shutil.rmtree', denied)
    with pytest.raises(PermissionError):
        platform.jobs.remove(job['id'])
    assert platform.store.get('job', job['id'])['status'] == 'cancelled'


@pytest.mark.parametrize('engine,language,expected', [
    ('auto', 'java', 'java'), ('auto', 'python', 'generic'),
    ('generic', 'java', 'generic'), ('java', 'java', 'java'),
])
def test_project_analysis_engine_and_index_identity(service, monkeypatch, engine, language, expected):
    client, headers, platform, spaces = service
    wid = spaces[0]['workspace_id']
    platform.store.create('index', {'id': wid, 'workspace_id': wid, 'generation': 'fixture',
                                   'config_version': spaces[0]['config_version'], 'workspace_file': 'fixture'})
    url = f'/api/v1/workspaces/{wid}/analysis-settings'
    assert client.get(url, headers=headers).json()['engine'] == 'auto'
    saved = client.put(url, headers=headers, json={'engine': engine, 'revision': 0})
    assert saved.status_code == 200, saved.text
    assert client.put(url, headers=headers, json={'engine': engine, 'revision': 0}).status_code == 409
    assert platform.store.get('index', wid)['generation'] == 'fixture'
    assert client.get(f'/api/v1/workspaces/{spaces[1]["workspace_id"]}/analysis-settings', headers=headers).json()['engine'] == 'auto'
    monkeypatch.setattr('memory_center.platform.application.query_code_graph', lambda *args: {
        'state': 'FOUND', 'symbols': [{'name': 'entry', 'language': language}], 'chain': [],
        'coverage': {'languages': {'java': 1, 'python': 1}}, 'negative_claim_allowed': False,
    })
    monkeypatch.setattr('memory_center.core.orchestrator.impact.memory_impact', lambda *args, **kwargs: {'specialized': True})
    result = platform.analyze(platform.administrator(), wid, 'entry')
    assert result['analysis_engine'] == expected
    assert bool(result.get('specialized')) == (expected == 'java')


def test_unmatched_anchor_does_not_fall_back_to_java(service, monkeypatch):
    client, headers, platform, spaces = service
    wid = spaces[0]['workspace_id']
    platform.store.create('index', {'id': wid, 'workspace_id': wid, 'generation': 'fixture',
                                   'config_version': spaces[0]['config_version'], 'workspace_file': 'fixture'})
    monkeypatch.setattr('memory_center.platform.application.query_code_graph', lambda *args: {
        'state': 'NOT_FOUND', 'symbols': [], 'chain': [], 'negative_claim_allowed': False,
    })

    def forbidden(*args, **kwargs):
        pytest.fail('缺失锚点不应回落到 Java 专用分析')

    monkeypatch.setattr('memory_center.core.orchestrator.impact.memory_impact', forbidden)
    assert platform.analyze(platform.administrator(), wid, 'missing')['state'] == 'NOT_FOUND'
