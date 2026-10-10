"""持久任务目录与有界子进程；取消不发布 generation。"""
import asyncio
import hashlib
import multiprocessing
import os
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import yaml

from memory_center.core.foundation.catalog import CatalogError
from memory_center.platform.database import Database, PostgresCatalog
from memory_center.platform.embeddings import Embedder
from memory_center.platform.knowledge import Knowledge
from memory_center.platform.parse_cache import (
    JAVA_NAMESPACE,
    STRUCTURAL_NAMESPACE,
    ParseCache,
    configured_budget_bytes,
    enforce_budget,
)
from memory_center.platform.store import PlatformStore, identity, now
from memory_center.platform.wiki_sources import WikiSources
from memory_center.platform.work_pool import WorkPool, cpu_budget, share_budget

_SKIP = {'.git', '.memory-center', '.project-ai', '.claude', '.codex', '.idea', 'node_modules', 'target',
         'build', 'dist', '__pycache__', '.venv', 'venv', 'vendor'}
_EXTENSIONS = {'.java', '.py', '.go', '.ts', '.tsx', '.js', '.jsx', '.vue', '.kt', '.rs', '.c', '.h',
               '.cpp', '.cs', '.mjs', '.cjs', '.pyi', '.md', '.txt', '.yaml', '.yml', '.json', '.toml', '.xml', '.properties', '.sql'}


@dataclass(frozen=True)
class IndexLimits:
    """索引资源软上限。

    默认所有限制为 0（关闭）；显式设置正数后，超过配置上限的任务以
    ``INDEX_BUDGET_EXCEEDED`` 有序失败并给出批准方式，而不是静默截断索引范围。
    设置 ``MEMORY_CENTER_ALLOW_LARGE_INDEX=1`` 表示已确认机器资源充足，完整索引。
    ``memory_limit_bytes`` 与 ``timeout_seconds`` 默认 0，表示不施加额外约束。
    """

    max_files: int = 0
    max_total_bytes: int = 0
    max_file_bytes: int = 0
    allow_large: bool = False
    memory_limit_bytes: int = 0
    timeout_seconds: int = 0

    @classmethod
    def from_env(cls, env=None) -> 'IndexLimits':
        source = os.environ if env is None else env

        def integer(name: str, default: int) -> int:
            raw = str(source.get(name, '') or '').strip()
            try:
                value = int(raw)
            except ValueError:
                return default
            return value if value > 0 else default

        return cls(
            max_files=integer('MEMORY_CENTER_INDEX_MAX_FILES', 0),
            max_total_bytes=integer('MEMORY_CENTER_INDEX_MAX_TOTAL_MB', 0) * 1024 ** 2,
            max_file_bytes=integer('MEMORY_CENTER_INDEX_MAX_FILE_MB', 0) * 1024 ** 2,
            allow_large=str(source.get('MEMORY_CENTER_ALLOW_LARGE_INDEX', '') or '').strip() == '1',
            memory_limit_bytes=integer('MEMORY_CENTER_INDEX_MEMORY_LIMIT_MB', 0) * 1024 ** 2,
            timeout_seconds=integer('MEMORY_CENTER_INDEX_TIMEOUT_SECONDS', 0),
        )

    def describe(self, files: int, total_bytes: int) -> str:
        return (f'文件 {files}/{self.max_files}，累计 {total_bytes // (1024 ** 2)} MiB/'
                f'{self.max_total_bytes // (1024 ** 2)} MiB')


def scan_source_files(root, limits: IndexLimits, progress=None):
    """扫描已登记源码范围，超过软上限且未显式批准时失败。

    ``source_files`` 本身保持无限制，便于被其它调用方直接复用；预算只在此处施加。
    """
    files, total, oversized = [], 0, ''
    for path in source_files(root):
        try:
            size = path.stat().st_size
        except OSError:
            continue
        files.append(path)
        total += size
        if progress:
            progress('scanning', len(files), None, 'files')
        if not oversized and limits.max_file_bytes and size > limits.max_file_bytes:
            oversized = path.relative_to(root).as_posix()
        if limits.allow_large:
            continue
        if (oversized or (limits.max_files and len(files) > limits.max_files)
                or (limits.max_total_bytes and total > limits.max_total_bytes)):
            detail = limits.describe(len(files), total)
            if oversized:
                detail += f'，单文件超过 {limits.max_file_bytes // (1024 ** 2)} MiB：{oversized}'
            raise CatalogError(
                'INDEX_BUDGET_EXCEEDED',
                f'源码规模超过索引软上限（{detail}）。确认机器资源充足后设置 '
                'MEMORY_CENTER_ALLOW_LARGE_INDEX=1 重新索引；未发布任何索引，上一代索引仍可读取。',
            )
    return files


def _apply_memory_limit(limit_bytes: int) -> None:
    """尽力为索引子进程设置地址空间上限；平台不支持时不阻塞索引。"""
    if limit_bytes <= 0:
        return
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (limit_bytes, limit_bytes))
    except (ImportError, AttributeError, ValueError, OSError):
        pass


def source_files(root):
    for parent, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in _SKIP and not d.startswith('.') and not (Path(parent) / d).is_symlink())
        for name in sorted(files):
            path = Path(parent) / name
            if name.startswith('.') or path.suffix.lower() not in _EXTENSIONS or path.is_symlink():
                continue
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


class JobProgress:
    """按真实完成量报告当前阶段；未知总量不伪造百分比。"""
    def __init__(self, store, job_id):
        self.store, self.job_id = store, job_id
        self.last, self.phase, self.started = 0, '', time.monotonic()

    def __call__(self, phase, completed=0, total=None, unit='files', detail=''):
        stamp = time.monotonic()
        if phase == self.phase and stamp - self.last < 1 and completed != total:
            return
        job = self.store.get('job', self.job_id)
        if job['status'] != 'running':
            raise CatalogError('JOB_CANCELLED', '任务已取消')
        self.store.update('job', self.job_id, {
            'phase': phase, 'completed': completed, 'total': total, 'unit': unit, 'detail': detail,
            'progress_scope': 'phase', 'progress': int(100 * completed / total) if total else 0,
            'elapsed_seconds': round(stamp - self.started), 'heartbeat_at': now(),
        })
        self.last, self.phase = stamp, phase


def assign_services(config, files):
    """预先解析服务路径，按最具体范围一次分配文件。"""
    scopes = sorted(((s.name, config.resolve_service_path(s)) for s in config.services),
                    key=lambda pair: len(pair[1].parts), reverse=True)
    owned = {s.name: [] for s in config.services}
    for path in files:
        for name, scope in scopes:
            if path.is_relative_to(scope):
                owned[name].append(str(path))
                break
    return owned


def run_index(data_dir, database_url, workspace, job_id, limits=None, file_workers=0):
    """子进程内装配旧事实引擎；派生 YAML 位于新服务 generation，绝不读源码旧配置。

    ``file_workers`` 是父进程按并发项目数切分后的文件级 worker 数
    （0 表示项目内串行）。池在本进程生命周期内常驻，只服务本次索引。
    """
    from memory_center.core.foundation.models import ServiceConfig, WorkspaceConfig
    from memory_center.core.indexing.reindex import reindex_workspace
    from memory_center.core.storage.catalog import CatalogStore
    from memory_center.core.storage.workspace import WorkspaceStore

    limits = limits or IndexLimits.from_env()

    data_dir = Path(data_dir)
    db = Database(data_dir, database_url)
    store, knowledge = PlatformStore(db), Knowledge(PlatformStore(db), data_dir)
    catalog = PostgresCatalog(data_dir, database_url) if database_url else CatalogStore(data_dir)
    report = JobProgress(store, job_id)
    pool = WorkPool(file_workers, kind='parse')
    # 解析缓存落在**工作区级**目录，不在 generation 内：generation 会被 prune 清理，
    # 而缓存必须跨代际存活，「只改了几个文件的再次索引」才能跳过其余文件的解析。
    # 预算为 0（MEMORY_CENTER_PARSE_CACHE_MB=0）时完全不读不写，退回全量解析。
    cache_budget = configured_budget_bytes()
    cache_root = data_dir / 'workspaces' / workspace['workspace_id'] / 'parse-cache'
    structural_cache = ParseCache(cache_root, STRUCTURAL_NAMESPACE) if cache_budget else None
    java_cache = ParseCache(cache_root, JAVA_NAMESPACE) if cache_budget else None
    try:
        root = Path(workspace['root'])
        if root.resolve() != root or not root.is_dir():
            raise CatalogError('ROOT_CHANGED', '源码目录已移动，请暂停后重新登记路径')
        chunks = []
        _apply_memory_limit(limits.memory_limit_bytes)
        # 默认完整扫描；仅当超过软上限且未显式批准时才拒绝，且不发布任何索引。
        report('scanning')
        files = scan_source_files(root, limits, report)
        report('chunking', 0, len(files))
        for number, path in enumerate(files, 1):
            text = path.read_text(encoding='utf-8', errors='replace')
            relative = path.relative_to(root).as_posix()
            chunks.extend(split_text(text, {'kind': 'code', 'source_id': 'code:' + relative,
                                           'path': relative, 'hash': hashlib.sha256(text.encode()).hexdigest()}))
            report('chunking', number, len(files))
        directory = data_dir / 'workspaces' / workspace['workspace_id'] / 'generations' / job_id
        directory.mkdir(parents=True, exist_ok=True)
        import json

        from memory_center.platform.code_graph import build_code_graph, coverage_summary
        report('parsing', 0, None)
        code_graph = build_code_graph(root, files, report, pool, structural_cache)
        (directory / 'code-graph.json').write_text(json.dumps(code_graph, ensure_ascii=False), encoding='utf-8')
        store.update('job', job_id, {'code_coverage': coverage_summary(code_graph)})
        workspace_file = directory / 'workspace.yaml'
        services = [ServiceConfig(name=s['service_id'], path=s['path'], type=s['type']) for s in workspace['services']]
        config = WorkspaceConfig(workspace=workspace['workspace_id'], root=str(root), services=services)
        workspace_file.write_text(yaml.safe_dump({'workspace': config.workspace, 'root': config.root,
                                   'services': [{'name': s.name, 'path': s.path, 'type': s.type} for s in services]}), encoding='utf-8')
        # 每个文件归属最具体的服务，父服务不重复吞入子服务。
        owned_by_service = assign_services(config, files)
        report('services', 0, len(services), 'services')
        for number, service in enumerate(services, 1):
            owned = owned_by_service[service.name]
            def service_progress(stage, _percent, message):
                report('services', number - 1, len(services), 'services', f'{service.name} · {stage} · {message}')
            reindex_workspace(config, WorkspaceStore(workspace_file), projects=[service.name],
                              paths=owned or [str(directory / 'empty-scope')], parallel=False,
                              pool=pool, cache=java_cache,
                              materialize_assertions=False, progress=service_progress)
            report('services', number, len(services), 'services', service.name)
        report('knowledge', 0, None, 'items')
        wiki_signature = WikiSources(store).signature(workspace['workspace_id'])
        store.update('job', job_id, {'wiki_signature': wiki_signature})
        for kind, item in knowledge.active(workspace['workspace_id']):
            chunks.extend(split_text(item['content'], {'kind': kind, 'source_id': item['id'],
                          'source_revision': item['revision'], 'title': item['title'], 'owner': item.get('owner', ''),
                          **({k: item[k] for k in ['wiki_source_id', 'relative_path', 'hash', 'source_name']} |
                             {'path': item['source_name'] + '/' + item['relative_path']} if item.get('wiki_source_id') else {})}))
        settings = store.list('model', limit=1)
        embedder = Embedder(settings[0] if settings else {})
        report('embedding', 0, len(chunks), 'chunks')
        # 嵌入分批执行并检查取消，模型故障保留上一代索引。
        for offset in range(0, len(chunks), 16):
            if store.get('job', job_id)['status'] != 'running':
                return
            batch = chunks[offset:offset + 16]
            for chunk, vector in zip(batch, embedder.embed([c['content'] for c in batch]), strict=False):
                chunk.update(profile=embedder.profile, embedding=vector)
            report('embedding', offset + len(batch), len(chunks), 'chunks')
        current = catalog.get(workspace['workspace_id'])
        if current['status'] != 'active' or current['config_version'] != workspace['config_version']:
            raise CatalogError('WORKSPACE_CHANGED', '项目配置已改变，未发布索引')
        if wiki_signature != WikiSources(store).signature(workspace['workspace_id']):
            raise CatalogError('WIKI_CHANGED', 'Wiki 来源已变化，等待下一轮自动索引')
        report('publishing', 0, None, 'chunks')
        store.publish(workspace['workspace_id'], job_id, chunks, str(workspace_file), workspace['config_version'])
        # 只在发布成功后维护缓存：失败或取消的索引不应改动跨代际的缓存目录。
        if cache_budget:
            store.update('job', job_id, {'parse_cache': {'budget_bytes': cache_budget,
                                                         **enforce_budget(cache_root, cache_budget)}})
    except Exception as exc:
        current = store.get('job', job_id)
        if current['status'] == 'running':
            code = exc.code if isinstance(exc, CatalogError) else 'INDEX_FAILED'
            store.update('job', job_id, {'status': 'failed', 'error': code,
                          'message': exc.message if isinstance(exc, CatalogError) else '索引失败，请检查文件、模型连接与服务日志',
                          'finished_at': now()})
        # 不打印底层连接串、文档或模型响应。
    finally:
        pool.close()


class Jobs:
    def __init__(self, store, catalog, data_dir, database_url=''):
        self.store, self.catalog = store, catalog
        self.data_dir, self.database_url = data_dir, database_url
        self.processes, self.started = {}, {}
        self.limits = IndexLimits.from_env()
        self.lifecycle_lock = threading.RLock()
        self.stopping = False
        self.task = None
        self.wiki_task = None

    def settings(self):
        current = self.store.list('job_settings', limit=1)
        if current:
            return current[0]
        budget = cpu_budget()
        return {'max_projects': max(1, min(4, budget - 1)), 'max_queued': 0,
                'max_file_workers': 0, 'automatic': True}

    def file_workers_for(self, concurrent_jobs):
        """本项目可用的文件级 worker 数；0 表示项目内串行。

        ``max_file_workers`` 为 0（默认）时按 CPU 预算在**同时运行的项目**之间切分：
        项目进程本身也占一个槽位，故 ``worker = 份额 - 1``。这一个函数就是
        「项目并发与文件并发共用资源预算」的落点——任何一侧都不能单独把机器开满。
        显式配置正数时视为「每项目固定宽度」，由配置者自担项目数相乘后的总量。
        """
        configured = int(self.settings().get('max_file_workers') or 0)
        if configured > 0:
            return configured
        return max(0, share_budget(cpu_budget(), max(1, concurrent_jobs)) - 1)

    def configure(self, value):
        with self.lifecycle_lock:
            current = self.store.list('job_settings', limit=1)
            result = (self.store.update('job_settings', current[0]['id'], value, current[0]['revision']) if current else
                      self.store.create('job_settings', value))
            self.store.audit('admin', 'jobs.configure')
            return result

    def pending(self):
        """只查询待处理任务，历史任务数量不会挤掉排队任务。"""
        import json
        field = "payload::jsonb->>'status'" if self.store.db.url else "json_extract(payload,'$.status')"
        with self.store.db.connection() as connection:
            rows = connection.execute(f"SELECT payload FROM records WHERE kind='job' AND {field} IN ('queued','running') ORDER BY updated_at,id").fetchall()
        return [json.loads(r[0]) for r in rows]

    def enqueue(self, workspace_id, owner, *, automatic=False):
        workspace = self.catalog.get(workspace_id)
        if workspace['status'] != 'active':
            raise CatalogError('WORKSPACE_PAUSED', '项目已暂停')
        from filelock import FileLock
        with FileLock(str(self.data_dir / 'jobs.lock'), timeout=5):
            pending = self.pending()
            existing = next((job for job in pending if job['workspace_id'] == workspace_id), None)
            if existing:
                return existing
            # Persist the last attempt independently of removable job history.
            # Manual retries replace it; automatic polls never revive a failed,
            # cancelled, interrupted or deleted attempt (including after restart).
            state_id = 'wiki_index_attempt_' + workspace_id
            try:
                attempt = self.store.get('wiki_index_attempt', state_id)
            except CatalogError:
                attempt = None
            if automatic:
                if attempt:
                    try:
                        last = self.store.get('job', attempt['job_id'])
                    except CatalogError:
                        return None
                else:
                    import json
                    created = ("payload::jsonb->>'created_at'" if self.store.db.url
                               else "json_extract(payload,'$.created_at')")
                    with self.store.db.connection() as connection:
                        row = connection.execute(
                            f"SELECT payload FROM records WHERE kind='job' AND workspace_id=? "
                            f"ORDER BY {created} DESC,id DESC LIMIT 1", (workspace_id,)).fetchone()
                    last = json.loads(row[0]) if row else None
                    if last:
                        attempt = self.store.create('wiki_index_attempt',
                            {'id': state_id, 'workspace_id': workspace_id, 'job_id': last['id']})
                if last and last['status'] != 'succeeded':
                    return None
            maximum = self.settings()['max_queued']
            if maximum and sum(j['status'] == 'queued' for j in pending) >= maximum:
                raise CatalogError('QUEUE_FULL', '后台队列达到已配置上限，请等待现有任务完成')
            job = self.store.create('job', {'workspace_id': workspace_id, 'owner': owner, 'status': 'queued',
                                            'progress': 0, 'phase': 'queued', 'progress_scope': 'phase',
                                            'completed': 0, 'total': None, 'config_version': workspace['config_version']})
            if attempt:
                self.store.update('wiki_index_attempt', state_id, {'job_id': job['id']})
            else:
                self.store.create('wiki_index_attempt',
                    {'id': state_id, 'workspace_id': workspace_id, 'job_id': job['id']})
            return job

    def cancel(self, job_id):
        job = self.store.get('job', job_id)
        if job['status'] in {'queued', 'running'}:
            return self.store.update('job', job_id, {'status': 'cancelled', 'finished_at': now()})
        return job

    @staticmethod
    def directory_bytes(root):
        """统计目录内普通文件字节数；跳过符号链接，避免顺着链接统计越界内容。"""
        total = 0
        for parent, _dirs, files in os.walk(root, followlinks=False):
            for name in files:
                path = Path(parent) / name
                if path.is_symlink():
                    continue
                try:
                    total += path.stat().st_size
                except OSError:
                    continue
        return total

    @staticmethod
    def drop_generation(generations, name):
        """删除 generations 内单个代号目录；仅接受非符号链接、解析后仍在其内的目录。

        返回 ``(释放字节数, 是否真正删除)``。删除前先解析真实路径并校验归属，防止
        拼接出的名称或目录内的符号链接把删除操作引向 generations 目录之外的路径。
        """
        try:
            base = generations.resolve()
        except OSError:
            return 0, False
        target = generations / name
        if target.is_symlink() or not target.is_dir():
            return 0, False
        try:
            resolved = target.resolve()
        except OSError:
            return 0, False
        if resolved == base or not resolved.is_relative_to(base):
            return 0, False
        freed = Jobs.directory_bytes(target)
        shutil.rmtree(target)
        return freed, True

    def remove(self, job_id):
        """等待取消进程退出后，保护当前代际并删除终态任务。"""
        with self.lifecycle_lock:
            job = self.store.get('job', job_id)
            if job['status'] in {'queued', 'running'}:
                raise CatalogError('JOB_STATE', '请先取消任务再删除')
            process = self.processes.get(job_id)
            if process is not None:
                if process.is_alive():
                    process.terminate()
                process.join(timeout=5)
                if process.is_alive():
                    raise CatalogError('JOB_BUSY', '任务进程尚未退出，请稍后重试')
                self.processes.pop(job_id, None)
                self.started.pop(job_id, None)
                process.close()
            workspace_id = job['workspace_id']
            with self.store.generation_lock(workspace_id):
                try:
                    active = self.store.get('index', workspace_id)['generation']
                except CatalogError:
                    active = None
                if active == job_id:
                    raise CatalogError('JOB_ACTIVE', '该任务是当前生效索引，请先重新索引后再删除')
                generations = self.data_dir / 'workspaces' / workspace_id / 'generations'
                freed, removed = self.drop_generation(generations, job_id)
                self.store.delete('job', job_id)
                self.store.audit('admin', 'job.remove', workspace_id, job_id)
                return {'id': job_id, 'deleted': True, 'removed_generation': removed, 'freed_bytes': freed}

    def prune(self, workspace_id=None):
        """清理非活跃 generation 目录：保留活跃索引与排队/运行中任务的代际，删除其余垃圾。

        ``workspace_id`` 为空时对所有已登记项目执行；返回删除数量、释放字节、保留的
        代号与处理的项目数。活跃 generation 的目录被 ``index.workspace_file`` 引用，
        删除会破坏查询；``queued``/``running`` 任务的目录正被子进程写入，删除会损坏
        在途索引，因此二者都始终保留。
        """
        with self.lifecycle_lock:
            workspace_ids = ([item['workspace_id'] for item in self.catalog.list(1000)['items']]
                             if workspace_id is None else [workspace_id])
            removed, freed, kept, workspaces = 0, 0, [], 0
            for wid in workspace_ids:
                with self.store.generation_lock(wid):
                    generations = self.data_dir / 'workspaces' / wid / 'generations'
                    if generations.is_symlink() or not generations.is_dir():
                        continue
                    try:
                        active = self.store.get('index', wid)['generation']
                    except CatalogError:
                        active = None
                    # 除活跃索引外，还必须保留排队/运行中任务的代际目录：索引子进程正在其中写入，
                    # 删除会损坏在途索引，随后成功发布还会指向一个已不存在的 generation。
                    protected = {job['id'] for job in self.store.list('job', workspace_id=wid, limit=1000)
                                 if job['status'] in {'queued', 'running'}}
                    protected.update(self.processes)
                    if active:
                        protected.add(active)
                    workspaces += 1
                    for entry in sorted(generations.iterdir()):
                        if entry.name in protected:
                            kept.append(entry.name)
                            continue
                        count, deleted = self.drop_generation(generations, entry.name)
                        if deleted:
                            removed += 1
                            freed += count
            self.store.audit('admin', 'job.prune', workspace_id or '')
            return {'removed': removed, 'freed_bytes': freed, 'kept': kept, 'workspaces': workspaces}

    async def start(self):
        for job in self.pending():
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
        associated = {w for s in sources.sources() if s['status'] == 'active' and s['auto_sync']
                      for w in s['workspace_ids']}
        for workspace_id in associated:
            try:
                index = self.store.get('index', workspace_id)
            except CatalogError:
                index = {}
            if index.get('wiki_signature') != sources.signature(workspace_id):
                try:
                    self.enqueue(workspace_id, 'admin', automatic=True)
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
            with self.lifecycle_lock:
                for job_id, process in list(self.processes.items()):
                    job = self.store.get('job', job_id)
                    if job['status'] == 'cancelled':
                        if process.is_alive():
                            process.terminate()
                    if (self.limits.timeout_seconds and process.is_alive()
                            and time.monotonic() - self.started.get(job_id, 0) > self.limits.timeout_seconds):
                        # 可选看门狗：默认关闭（timeout_seconds=0），开启后超时有序失败并保留上一代索引。
                        process.terminate()
                        self.store.update('job', job_id, {'status': 'failed', 'error': 'INDEX_TIMEOUT',
                                                          'message': f'索引超过 {self.limits.timeout_seconds} 秒未完成，已终止；上一代索引仍可读取。',
                                                          'finished_at': now()})
                    if not process.is_alive():
                        process.join(timeout=.1)
                        if self.store.get('job', job_id)['status'] == 'running':
                            self.store.update('job', job_id, {'status': 'failed', 'error': 'WORKER_EXITED', 'finished_at': now()})
                        self.processes.pop(job_id)
                        self.started.pop(job_id)
                        process.close()
                for job in self.pending():
                    if len(self.processes) >= self.settings()['max_projects']:
                        break
                    if job['status'] != 'queued':
                        continue
                    try:
                        workspace = self.catalog.get(job['workspace_id'])
                        if workspace['status'] != 'active' or workspace['config_version'] != job['config_version']:
                            raise CatalogError('WORKSPACE_CHANGED', '项目配置已改变')
                        self.store.update('job', job['id'], {'status': 'running', 'started_at': now()})
                        # 准入时一次性切分文件级预算：含本任务在内的并发项目数。
                        workers = self.file_workers_for(len(self.processes) + 1)
                        process = context.Process(target=run_index, args=(
                            self.data_dir, self.database_url, workspace, job['id'], self.limits, workers))
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
