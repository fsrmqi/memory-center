"""持久任务目录与有界子进程；取消/超时不发布 generation。"""
import asyncio
import hashlib
import multiprocessing
import os
import time
from pathlib import Path

import yaml

from memory_center.core.foundation.catalog import CatalogError
from memory_center.platform.database import Database, PostgresCatalog
from memory_center.platform.embeddings import Embedder
from memory_center.platform.knowledge import Knowledge
from memory_center.platform.store import PlatformStore, identity, now
from memory_center.platform.wiki_sources import WikiSources

_SKIP = {'.git', '.memory-center', '.project-ai', '.claude', '.codex', '.idea', 'node_modules', 'target',
         'build', 'dist', '__pycache__', '.venv', 'venv', 'vendor'}
_EXTENSIONS = {'.java', '.py', '.go', '.ts', '.tsx', '.js', '.jsx', '.vue', '.kt', '.rs', '.c', '.h',
               '.cpp', '.cs', '.mjs', '.cjs', '.pyi', '.md', '.txt', '.yaml', '.yml', '.json', '.toml', '.xml', '.properties', '.sql'}


def source_files(root):
    count, total = 0, 0
    for parent, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in _SKIP and not d.startswith('.') and not (Path(parent) / d).is_symlink())
        for name in sorted(files):
            path = Path(parent) / name
            if name.startswith('.') or path.suffix.lower() not in _EXTENSIONS or path.is_symlink():
                continue
            size = path.stat().st_size
            if size > 1024 * 1024:
                raise CatalogError('INDEX_BUDGET', '存在超过 1 MiB 的源码文件，请缩小项目范围')
            count, total = count + 1, total + size
            if count > 10000 or total > 64 * 1024 * 1024:
                raise CatalogError('INDEX_BUDGET', '索引上限 10000 文件/64 MiB，请缩小项目范围')
            resolved = path.resolve()
            if not resolved.is_relative_to(root):
                continue
            yield path


def split_text(text, metadata):
    lines = text.splitlines()
    chunks = []
    buffer, start, size, fenced = [], 1, 0, False
    for number, line in enumerate(lines, 1):
        if line.lstrip().startswith('```'):
            fenced = not fenced
        if buffer and (size > 1800 and not fenced or size > 6000):
            chunks.append({'id': identity('chunk'), 'source_id': metadata['source_id'],
                           'content': '\n'.join(buffer), 'metadata': dict(metadata, line=start, end_line=number - 1)})
            buffer, size, start = [], 0, number
        buffer.append(line)
        size += len(line) + 1
    if buffer:
        chunks.append({'id': identity('chunk'), 'source_id': metadata['source_id'],
                       'content': '\n'.join(buffer), 'metadata': dict(metadata, line=start, end_line=len(lines))})
    return chunks


def run_index(data_dir, database_url, workspace, job_id):
    """子进程内装配旧事实引擎；派生 YAML 位于新服务 generation，绝不读源码旧配置。"""
    from memory_center.core.foundation.models import ServiceConfig, WorkspaceConfig
    from memory_center.core.indexing.reindex import reindex_workspace
    from memory_center.core.storage.catalog import CatalogStore
    from memory_center.core.storage.workspace import WorkspaceStore

    data_dir = Path(data_dir)
    db = Database(data_dir, database_url)
    store, knowledge = PlatformStore(db), Knowledge(PlatformStore(db), data_dir)
    catalog = PostgresCatalog(data_dir, database_url) if database_url else CatalogStore(data_dir)
    try:
        root = Path(workspace['root'])
        if root.resolve() != root or not root.is_dir():
            raise CatalogError('ROOT_CHANGED', '源码目录已移动，请暂停后重新登记路径')
        chunks = []
        # 所有预算先在新平台扫描验证；不会直接把无限项目交给事实引擎。
        files = list(source_files(root))
        for path in files:
            text = path.read_text(encoding='utf-8', errors='replace')
            relative = path.relative_to(root).as_posix()
            chunks.extend(split_text(text, {'kind': 'code', 'source_id': 'code:' + relative,
                                           'path': relative, 'hash': hashlib.sha256(text.encode()).hexdigest()}))
        store.update('job', job_id, {'progress': 20})
        directory = data_dir / 'workspaces' / workspace['workspace_id'] / 'generations' / job_id
        directory.mkdir(parents=True, exist_ok=True)
        import json

        from memory_center.platform.code_graph import build_code_graph, coverage_summary
        code_graph = build_code_graph(root, files)
        (directory / 'code-graph.json').write_text(json.dumps(code_graph, ensure_ascii=False), encoding='utf-8')
        store.update('job', job_id, {'code_coverage': coverage_summary(code_graph)})
        workspace_file = directory / 'workspace.yaml'
        services = [ServiceConfig(name=s['service_id'], path=s['path'], type=s['type']) for s in workspace['services']]
        config = WorkspaceConfig(workspace=workspace['workspace_id'], root=str(root), services=services)
        workspace_file.write_text(yaml.safe_dump({'workspace': config.workspace, 'root': config.root,
                                   'services': [{'name': s.name, 'path': s.path, 'type': s.type} for s in services]}), encoding='utf-8')
        # 每个文件归属最具体的服务，父服务不重复吞入子服务。
        for service in services:
            owned = []
            for path in files:
                matches = [s for s in services if path.is_relative_to(config.resolve_service_path(s))]
                best = max(matches, key=lambda s: len(config.resolve_service_path(s).parts)) if matches else None
                if best and best.name == service.name:
                    owned.append(str(path))
            reindex_workspace(config, WorkspaceStore(workspace_file), projects=[service.name],
                              paths=owned or [str(directory / 'empty-scope')], parallel=False,
                              materialize_assertions=False)
        store.update('job', job_id, {'progress': 55})
        wiki_signature = WikiSources(store).signature(workspace['workspace_id'])
        store.update('job', job_id, {'wiki_signature': wiki_signature})
        for kind, item in knowledge.active(workspace['workspace_id']):
            chunks.extend(split_text(item['content'], {'kind': kind, 'source_id': item['id'],
                          'source_revision': item['revision'], 'title': item['title'], 'owner': item.get('owner', ''),
                          **({k: item[k] for k in ['wiki_source_id', 'relative_path', 'hash', 'source_name']} |
                             {'path': item['source_name'] + '/' + item['relative_path']} if item.get('wiki_source_id') else {})}))
        if len(chunks) > 30000:
            raise CatalogError('INDEX_BUDGET', '分块上限 30000，请缩小索引范围')
        settings = store.list('model', limit=1)
        embedder = Embedder(settings[0] if settings else {})
        # 嵌入分批执行并检查取消，模型故障保留上一代索引。
        for offset in range(0, len(chunks), 16):
            if store.get('job', job_id)['status'] != 'running':
                return
            batch = chunks[offset:offset + 16]
            for chunk, vector in zip(batch, embedder.embed([c['content'] for c in batch]), strict=False):
                chunk.update(profile=embedder.profile, embedding=vector)
            store.update('job', job_id, {'progress': min(95, 55 + int(40 * (offset + len(batch)) / max(1, len(chunks))))})
        current = catalog.get(workspace['workspace_id'])
        if current['status'] != 'active' or current['config_version'] != workspace['config_version']:
            raise CatalogError('WORKSPACE_CHANGED', '项目配置已改变，未发布索引')
        if wiki_signature != WikiSources(store).signature(workspace['workspace_id']):
            raise CatalogError('WIKI_CHANGED', 'Wiki 来源已变化，等待下一轮自动索引')
        store.publish(workspace['workspace_id'], job_id, chunks, str(workspace_file), workspace['config_version'])
    except Exception as exc:
        current = store.get('job', job_id)
        if current['status'] == 'running':
            code = exc.code if isinstance(exc, CatalogError) else 'INDEX_FAILED'
            store.update('job', job_id, {'status': 'failed', 'error': code,
                          'message': exc.message if isinstance(exc, CatalogError) else '索引失败，请检查文件、模型连接与服务日志',
                          'finished_at': now()})
        # 不打印底层连接串、文档或模型响应。


class Jobs:
    def __init__(self, store, catalog, data_dir, database_url=''):
        self.store, self.catalog = store, catalog
        self.data_dir, self.database_url = data_dir, database_url
        self.processes, self.started = {}, {}
        self.stopping = False
        self.task = None
        self.wiki_task = None

    def enqueue(self, workspace_id, owner):
        workspace = self.catalog.get(workspace_id)
        if workspace['status'] != 'active':
            raise CatalogError('WORKSPACE_PAUSED', '项目已暂停')
        from filelock import FileLock
        with FileLock(str(self.data_dir / 'jobs.lock'), timeout=5):
            jobs = self.store.list('job', limit=1000)
            pending = [job for job in jobs if job['status'] in {'queued', 'running'}]
            if len(pending) >= 32:
                raise CatalogError('QUEUE_FULL', '后台队列已满，请等待现有任务完成')
            existing = next((job for job in pending if job['workspace_id'] == workspace_id), None)
            if existing:
                return existing
            return self.store.create('job', {'workspace_id': workspace_id, 'owner': owner, 'status': 'queued',
                                            'progress': 0, 'config_version': workspace['config_version']})

    def cancel(self, job_id):
        job = self.store.get('job', job_id)
        if job['status'] in {'queued', 'running'}:
            return self.store.update('job', job_id, {'status': 'cancelled', 'finished_at': now()})
        return job

    async def start(self):
        for job in self.store.list('job', limit=1000):
            if job['status'] == 'running':
                self.store.update('job', job['id'], {'status': 'interrupted', 'finished_at': now()})
        self.task = asyncio.create_task(self.loop())
        self.wiki_task = asyncio.create_task(self.wiki_loop())

    def sync_wikis(self):
        sources = WikiSources(self.store, self.catalog)
        for source in sources.sources():
            if source['status'] == 'active' and source['auto_sync']:
                try:
                    sources.sync(source['id'])
                except CatalogError:
                    pass  # 单来源失败记录在来源状态中，不中断其它来源。
        # 比较持久快照标识，避免同步与正在运行的索引重叠时丢失更新。
        associated = {w for s in sources.sources() for w in s['workspace_ids']}
        for workspace_id in associated:
            try:
                index = self.store.get('index', workspace_id)
            except CatalogError:
                index = {}
            if index.get('wiki_signature') != sources.signature(workspace_id):
                try:
                    self.enqueue(workspace_id, 'admin')
                except CatalogError:
                    pass

    async def wiki_loop(self):
        while not self.stopping:
            await asyncio.sleep(1)
            if self.stopping:
                break
            await asyncio.to_thread(self.sync_wikis)
            for _ in range(59):
                if self.stopping:
                    return
                await asyncio.sleep(1)

    async def loop(self):
        context = multiprocessing.get_context('spawn')
        while not self.stopping:
            for job_id, process in list(self.processes.items()):
                job = self.store.get('job', job_id)
                if job['status'] == 'cancelled' or time.monotonic() - self.started[job_id] > 600:
                    if process.is_alive():
                        process.terminate()
                    if job['status'] != 'cancelled':
                        self.store.update('job', job_id, {'status': 'failed', 'error': 'JOB_TIMEOUT', 'finished_at': now()})
                if not process.is_alive():
                    process.join(timeout=.1)
                    if self.store.get('job', job_id)['status'] == 'running':
                        self.store.update('job', job_id, {'status': 'failed', 'error': 'WORKER_EXITED', 'finished_at': now()})
                    self.processes.pop(job_id)
                    self.started.pop(job_id)
                    process.close()
            for job in reversed(self.store.list('job', limit=1000)):
                if len(self.processes) >= 2:
                    break
                if job['status'] != 'queued':
                    continue
                try:
                    workspace = self.catalog.get(job['workspace_id'])
                    if workspace['status'] != 'active' or workspace['config_version'] != job['config_version']:
                        raise CatalogError('WORKSPACE_CHANGED', '项目配置已改变')
                    self.store.update('job', job['id'], {'status': 'running', 'started_at': now()})
                    process = context.Process(target=run_index, args=(self.data_dir, self.database_url, workspace, job['id']))
                    process.start()
                    self.processes[job['id']], self.started[job['id']] = process, time.monotonic()
                except Exception:
                    self.store.update('job', job['id'], {'status': 'failed', 'error': 'WORKSPACE_CHANGED', 'finished_at': now()})
            await asyncio.sleep(.3)

    async def close(self):
        self.stopping = True
        if self.wiki_task:
            await asyncio.gather(self.wiki_task, return_exceptions=True)
        if self.task:
            # DB 故障可能结束调度任务；关闭时仍需收割全部子进程。
            await asyncio.gather(self.task, return_exceptions=True)
        for job_id, process in self.processes.items():
            if process.is_alive():
                process.terminate()
            await asyncio.to_thread(process.join, 3)
            if process.is_alive():
                process.kill()
                await asyncio.to_thread(process.join, 1)
            process.close()
            try:
                if self.store.get('job', job_id)['status'] == 'running':
                    self.store.update('job', job_id, {'status': 'interrupted', 'finished_at': now()})
            except Exception:
                # 下次启动会把残留 running 状态恢复为 interrupted。
                pass
        self.processes.clear()
