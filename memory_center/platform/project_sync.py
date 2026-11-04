"""项目源码轮询、去抖调度与知识检索覆盖状态。"""
import asyncio
import hashlib
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from filelock import FileLock
from memory_center.core.foundation.catalog import CatalogError
from memory_center.platform.store import now


class ProjectSync:
    def __init__(self, jobs):
        self.jobs, self.store, self.catalog = jobs, jobs.store, jobs.catalog
        self.task = None
        self.closing = False
        self.lock = threading.RLock()
        self.due = {}
        self.baseline_signatures = {}

    def settings(self, workspace_id):
        self.catalog.get(workspace_id)
        try:
            return self.store.get('source_sync_settings', 'source_sync_' + workspace_id)
        except CatalogError:
            return {'enabled': False, 'interval_seconds': 120, 'debounce_seconds': 10, 'revision': 0}

    def configure(self, workspace_id, value, revision):
        with self.lock:
            current = self.settings(workspace_id)
            if current['revision'] != revision:
                raise CatalogError('REVISION_CONFLICT', '自动同步设置已变化，请刷新')
            if all(current.get(k) == v for k, v in value.items()):
                return current
            record_id = 'source_sync_' + workspace_id
            result = (self.store.update('source_sync_settings', record_id, value, revision) if revision else
                      self.store.create('source_sync_settings', {'id': record_id, 'workspace_id': workspace_id, **value}))
            self.due.pop(workspace_id, None)
            self.store.audit('admin', 'source_sync.configure', workspace_id)
            return result

    def state(self, workspace_id):
        self.catalog.get(workspace_id)
        try:
            value = self.store.get('source_sync_state', 'source_state_' + workspace_id)
        except CatalogError:
            value = {'state': 'unchecked', 'changed_files': None, 'checked_at': None}
        settings = self.settings(workspace_id)
        value = dict(value, enabled=settings['enabled'], interval_seconds=settings['interval_seconds'],
                     debounce_seconds=settings['debounce_seconds'])
        try:
            index = self.store.get('index', workspace_id)
            value['last_success_at'] = self.store.get('job', index['generation']).get('finished_at')
            if value.get('checked_at') and value.get('baseline_generation') != index['generation'] and value['state'] != 'error':
                try:
                    path = Path(index['workspace_file']).parent / 'source-manifest.json'
                    if path.is_symlink():
                        raise ValueError('基线清单无效')
                    stat = path.stat()
                    key = (str(path), stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)
                    cached = self.baseline_signatures.get(workspace_id)
                    if not cached or cached[0] != key:
                        cached = (key, hashlib.sha256(json.dumps(json.loads(path.read_text()), sort_keys=True).encode()).hexdigest())
                        self.baseline_signatures[workspace_id] = cached
                    if cached[1] == value.get('observed_signature') and index['config_version'] == self.catalog.get(workspace_id)['config_version']:
                        value.update(state='current', changed_files=0)
                    else:
                        value.update(state='unchecked', changed_files=None)
                except (OSError, ValueError, KeyError, TypeError):
                    value.update(state='unchecked', changed_files=None)
        except CatalogError:
            value['last_success_at'] = None
        attempt = self._attempt(workspace_id)
        if attempt and attempt['status'] != 'succeeded':
            value['schedule_state'] = 'pending' if attempt['status'] in {'queued','running'} else 'blocked'
            value['last_job_id'] = attempt['id']
        else:
            value['schedule_state'] = 'disabled' if not settings['enabled'] else 'waiting_capacity' if value.get('waiting_capacity') else 'watching'
        return value

    def _attempt(self, workspace_id):
        try:
            attempt = self.store.get('wiki_index_attempt', 'wiki_index_attempt_' + workspace_id)
            try:
                return self.store.get('job', attempt['job_id'])
            except CatalogError:
                return {'id': attempt['job_id'], 'status': 'missing'}
        except CatalogError:
            return None

    def _save(self, workspace_id, patch):
        record_id = 'source_state_' + workspace_id
        try:
            self.store.get('source_sync_state', record_id)
            return self.store.update('source_sync_state', record_id, patch)
        except CatalogError as exc:
            if exc.code != 'RECORD_NOT_FOUND':
                raise
            return self.store.create('source_sync_state', {'id': record_id, 'workspace_id': workspace_id, **patch})

    def check(self, workspace_id, manual=False, stamp=None):
        from memory_center.platform.jobs import scan_source_files
        from memory_center.platform.incremental_index import source_manifest, plan_incremental
        stamp = time.time() if stamp is None else stamp
        with self.lock, FileLock(str(self.store.db.data_dir / 'source-sync.lock')):
            workspace = self.catalog.get(workspace_id)
            settings = self.settings(workspace_id)
            previous_state = self.state(workspace_id)
            if not manual and (not settings['enabled'] or workspace['status'] != 'active' or previous_state.get('state') == 'error'):
                return previous_state
            try:
                root = Path(workspace['root'])
                if not root.is_dir():
                    raise OSError('源码目录不可读取')
                def check_stop(*_args):
                    if self.closing:
                        raise InterruptedError('源码检查停止')
                files = scan_source_files(root, self.jobs.limits, check_stop)
                digests = {}
                for path in files:
                    check_stop()
                    digests[str(path)] = hashlib.sha256(path.read_text(encoding='utf-8', errors='replace').encode()).hexdigest()
                from memory_center.core.foundation.models import WorkspaceConfig, ServiceConfig
                from memory_center.platform.jobs import assign_services
                config = WorkspaceConfig(workspace=workspace_id, root=str(root), services=[ServiceConfig(name=s['service_id'], path=s['path'], type=s['type']) for s in workspace['services']])
                manifest = source_manifest(root, workspace, digests, assign_services(config, files))
                signature = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
                with self.store.generation_lock(workspace_id):
                    try:
                        index = self.store.get('index', workspace_id)
                    except CatalogError:
                        index = None
                    baseline = None
                    if index:
                        try:
                            baseline_path = Path(index['workspace_file']).parent / 'source-manifest.json'
                            baseline = json.loads(baseline_path.read_text()) if not baseline_path.is_symlink() else None
                        except (OSError, ValueError):
                            pass
                if not isinstance(baseline, dict) or not isinstance(baseline.get('files'), dict):
                    baseline = None
                plan = plan_incremental(baseline, manifest, [s['service_id'] for s in workspace['services']])
                config_changed = bool(index and index['config_version'] != workspace['config_version'])
                changed = plan['mode'] != 'unchanged' or config_changed
                same = previous_state.get('observed_signature') == signature
                since = previous_state.get('changed_since_epoch', stamp) if same else stamp
                patch = {'state': 'not_indexed' if not index else 'config_changed' if config_changed else 'baseline_required' if plan['mode']=='full' else 'changed' if changed else 'current',
                         'changed_files': None if plan['mode']=='full' else sum(plan[k] for k in ['added_files','modified_files','deleted_files']),
                         'added_files': plan['added_files'], 'modified_files': plan['modified_files'], 'deleted_files': plan['deleted_files'],
                         'baseline_generation':index['generation'] if index else None, 'checked_at': now(), 'observed_signature': signature, 'changed_since_epoch': since, 'waiting_capacity':False, 'error': ''}
                self._save(workspace_id, patch)
                if settings['enabled'] and workspace['status']=='active' and changed and stamp-since>=settings['debounce_seconds']:
                    try:
                        job = self.jobs.enqueue(workspace_id, 'admin', automatic=True, trigger='source_sync')
                    except CatalogError as exc:
                        if exc.code != 'QUEUE_FULL':
                            raise
                        self._save(workspace_id, {'waiting_capacity':True})
                        job = None
                    if job:
                        self._save(workspace_id, {'last_scheduled_job': job['id']})
            except (CatalogError, OSError, ValueError, KeyError, TypeError) as exc:
                if self.closing:
                    return previous_state
                self._save(workspace_id, {'state':'error', 'checked_at':now(), 'error':'源码检查失败，请检查目录和资源配置后手动检查；自动检查已停止'})
            return self.state(workspace_id)

    def tick(self):
        # 只遍历已配置记录；默认关闭的项目不反复扫描源码和服务目录。
        page = 1
        while not self.jobs.stopping:
            data = self.store.list_page('source_sync_settings', page=page, page_size=50)
            for settings in data['items']:
                if not settings['enabled']:
                    continue
                wid = settings['workspace_id']
                stamp = time.time()
                if stamp < self.due.get(wid, 0):
                    continue
                try:
                    workspace = self.catalog.get(wid)
                except CatalogError:
                    continue
                if workspace['status'] != 'active':
                    continue
                result = self.check(wid, stamp=stamp)
                delay = min(settings['interval_seconds'], max(1, settings['debounce_seconds'])) if result['state'] in {'changed','config_changed','not_indexed','baseline_required'} and result['schedule_state'] not in {'pending','blocked','waiting_capacity'} else settings['interval_seconds']
                self.due[wid] = stamp + delay
            if page >= data['pages']:
                return
            page += 1

    async def loop(self):
        while not self.jobs.stopping:
            try:
                await asyncio.to_thread(self.tick)
            except Exception:
                # 单次存储故障不杀掉其它调度；源码检查错误已持久化为阻止状态。
                pass
            await asyncio.sleep(1)


def knowledge_index_status(platform, workspace_id, kind='', page=1, page_size=10):
    platform.catalog.get(workspace_id)
    try:
        index = platform.store.get('index', workspace_id)
    except CatalogError:
        index = None
    field = "metadata::jsonb->>'kind'" if platform.store.db.url else "json_extract(metadata,'$.kind')"
    with platform.store.db.connection() as db:
        rows = db.execute(f"SELECT DISTINCT source_id,metadata FROM chunks WHERE workspace_id=? AND {field}!='code'", (workspace_id,)).fetchall()
    indexed = {}
    for row in rows:
        source_id, metadata = row[0], row[1]
        meta=json.loads(metadata);indexed[(meta['kind'],source_id)] = meta.get('source_revision')
    current = {(k,item['id']):item for k,item in platform.knowledge.active(workspace_id)}
    changes = []
    for key, item in current.items():
        if kind and key[0]!=kind:continue
        if not item.get('content','').strip():continue
        if item.get('wiki_source_id') and not platform.wiki_sources.fresh(item):
            changes.append({'id':item['id'],'kind':key[0],'title':item.get('title',''), 'revision':item['revision'], 'reason':'source_changed'})
            continue
        if indexed.get(key)!=item['revision']:
            changes.append({'id':item['id'],'kind':key[0],'title':item.get('title',''), 'revision':item['revision'],
                            'reason':'updated' if key in indexed else 'added'})
    for key in indexed.keys()-current.keys():
        if kind and key[0]!=kind:continue
        changes.append({'id':key[1], 'kind':key[0], 'title':'已移除或不再可见的来源', 'reason':'removed'})
    pending = platform.store.list_page('memory',workspace_id=workspace_id,status='pending',page=1,page_size=1)['total'] if kind in ('','memory') else 0
    changes.sort(key=lambda row:(row['kind'],row['id']))
    total=len(changes);pages=max(1,(total+page_size-1)//page_size);page=min(page,pages)
    active=[]
    for status in ('queued','running'):
        active.extend(t for t in platform.store.list_page('knowledge_task',workspace_id=workspace_id,status=status,page_size=50)['items'] if t['kind']=='refresh')
    return {'state':'not_indexed' if not index else 'changed' if total else 'current', 'last_refreshed_at':index.get('updated_at') if index else None,
            'items':changes[(page-1)*page_size:page*page_size], 'total':total,'page':page,'pages':pages,'page_size':page_size,
            'awaiting_confirmation':pending, 'needs_source_sync':sum(row['reason']=='source_changed' for row in changes), 'refresh_task':active[0] if active else None}
