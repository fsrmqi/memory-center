"""按项目预览与执行索引／缓存清理；不清理源码、知识记录或当前索引。"""
import hashlib
import json
import os
import shutil
import stat
from datetime import datetime, timedelta, timezone

from filelock import FileLock

from memory_center.core.foundation.catalog import CatalogError
from memory_center.platform.store import now


class StorageMaintenance:
    def __init__(self, platform):
        self.platform = platform
        self.store, self.jobs = platform.store, platform.jobs

    def settings(self, workspace_id):
        try:
            return self.store.get('storage_policy', 'storage_policy_' + workspace_id)
        except CatalogError:
            return {'workspace_id': workspace_id, 'keep_history': 2, 'revision': 0}

    def configure(self, workspace_id, keep_history, revision):
        if not isinstance(keep_history, int) or isinstance(keep_history, bool) or not 0 <= keep_history <= 100:
            raise CatalogError('STORAGE_POLICY_INVALID', '历史成功代际保留数量需介于 0–100')
        with self.jobs.lifecycle_lock, self.store.db.connection(True) as connection:
            current = self.settings(workspace_id)
            if current['revision'] != revision:
                raise CatalogError('REVISION_CONFLICT', '保留策略已改变，请刷新后重试')
            value = dict(current, id='storage_policy_' + workspace_id, keep_history=keep_history,
                         revision=revision + 1, updated_at=now())
            self.store._put(connection, 'storage_policy', value)
        self.store.audit('admin', 'storage.configure', workspace_id)
        return value

    def _root(self, workspace_id):
        # 仅接受目录控制面已登记的项目；祖先不可通过符号链接指向其它空间。
        self.platform.catalog.get(workspace_id)
        base = self.jobs.data_dir / 'workspaces'
        root = base / workspace_id
        if base.is_symlink() or root.is_symlink() or (root.exists() and not root.is_dir()):
            raise CatalogError('STORAGE_UNSAFE', '项目存储目录异常，不允许清理')
        return root

    @staticmethod
    def _manifest(directory):
        digest, total, files = hashlib.sha256(), 0, 0

        def read_error(error):
            raise error

        for parent, dirs, names in os.walk(directory, followlinks=False, onerror=read_error):
            dirs.sort()
            for name in sorted(dirs + names):
                path = os.path.join(parent, name)
                info = os.lstat(path)
                relative = os.path.relpath(path, directory)
                digest.update(json.dumps([relative, info.st_mode, info.st_size, info.st_mtime_ns,
                                          info.st_ino, info.st_dev], ensure_ascii=False).encode())
                if stat.S_ISREG(info.st_mode):
                    total += info.st_size
                    files += 1
        root_stat = directory.lstat()
        digest.update(str((root_stat.st_dev, root_stat.st_ino, root_stat.st_mtime_ns)).encode())
        return {'bytes': total, 'files': files, 'fingerprint': digest.hexdigest()}

    def _plan(self, workspace_id, clear_parse_cache=False, clear_embedding_cache=False):
        root = self._root(workspace_id)
        policy = self.settings(workspace_id)
        index = self.store.list('index', workspace_id=workspace_id, limit=1)
        active = index[0]['generation'] if index else ''
        pending = {job['id'] for job in self.jobs.pending() if job['workspace_id'] == workspace_id}
        # 状态已取消但进程尚未退出时，仍不可删除它正在写入的目录／缓存。
        for job_id, process in self.jobs.processes.items():
            if self.store.get('job', job_id)['workspace_id'] == workspace_id:
                pending.add(job_id)
        if pending and (clear_parse_cache or clear_embedding_cache):
            raise CatalogError('STORAGE_BUSY', '项目仍有排队或运行中任务，请等待任务退出后清理缓存')
        protected = set(pending)
        if active:
            protected.add(active)
        # 只保留可确定为成功的历史代际，按成功完成时间排序，不按目录修改时间猜测。
        with self.store.db.connection() as connection:
            rows = connection.execute("SELECT id,payload FROM records WHERE kind='job' AND workspace_id=?", (workspace_id,)).fetchall()
        successful = {row['id']: json.loads(row['payload']).get('finished_at', '') for row in rows
                      if json.loads(row['payload']).get('status') == 'succeeded'}
        generations = root / 'generations'
        if generations.is_symlink():
            raise CatalogError('STORAGE_UNSAFE', '索引代际目录为符号链接，不允许清理')
        entries = sorted(generations.iterdir()) if generations.exists() else []
        history = sorted((entry.name for entry in entries if entry.name not in protected and entry.name in successful
                          and entry.is_dir() and not entry.is_symlink()), key=lambda name: (successful[name], name), reverse=True)
        retained = history[:policy['keep_history']]
        protected.update(retained)
        candidates, skipped = [], []
        for entry in entries:
            if entry.name in protected:
                continue
            if entry.is_symlink() or not entry.is_dir():
                skipped.append('generations/' + entry.name)
                continue
            candidates.append({'path': 'generations/' + entry.name, 'kind': 'generation', **self._manifest(entry)})
        for name, enabled, kind in (('parse-cache', clear_parse_cache, 'parse_cache'),
                                    ('embedding-cache', clear_embedding_cache, 'embedding_cache')):
            directory = root / name
            if enabled and directory.is_symlink():
                raise CatalogError('STORAGE_UNSAFE', '缓存目录为符号链接，不允许清理')
            if enabled and directory.exists():
                if not directory.is_dir():
                    raise CatalogError('STORAGE_UNSAFE', '缓存目录类型异常，不允许清理')
                candidates.append({'path': name, 'kind': kind, **self._manifest(directory)})
        return {'workspace_id': workspace_id, 'policy_revision': policy['revision'], 'keep_history': policy['keep_history'],
                'active_generation': active, 'protected': sorted(protected), 'retained_history': retained,
                'clear_parse_cache': clear_parse_cache, 'clear_embedding_cache': clear_embedding_cache,
                'candidates': candidates, 'skipped': skipped,
                'bytes': sum(item['bytes'] for item in candidates), 'files': sum(item['files'] for item in candidates)}

    def preview(self, workspace_id, clear_parse_cache=False, clear_embedding_cache=False):
        self._root(workspace_id)
        try:
            with self.jobs.lifecycle_lock, FileLock(str(self.jobs.data_dir / 'jobs.lock'), timeout=5), self.store.generation_lock(workspace_id):
                plan = self._plan(workspace_id, clear_parse_cache, clear_embedding_cache)
                return self.store.create('storage_cleanup_preview', dict(plan, status='pending',
                    expires_at=(datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()))
        except OSError as error:
            raise CatalogError('STORAGE_READ_FAILED', '读取存储失败，未生成清理预览') from error

    def apply(self, workspace_id, preview_id, revision, confirm=False):
        self._root(workspace_id)
        if not confirm:
            raise CatalogError('CONFIRM_REQUIRED', '请先检查清理预览并明确确认')
        with self.jobs.lifecycle_lock, FileLock(str(self.jobs.data_dir / 'jobs.lock'), timeout=5), self.store.generation_lock(workspace_id):
            preview = self.store.get('storage_cleanup_preview', preview_id)
            if preview['workspace_id'] != workspace_id:
                raise CatalogError('FORBIDDEN', '清理预览不属于当前项目')
            if preview['status'] != 'pending' or preview['revision'] != revision:
                raise CatalogError('REVISION_CONFLICT', '清理预览已处理，请重新预览')
            if datetime.fromisoformat(preview['expires_at']) <= datetime.now(timezone.utc):
                raise CatalogError('STORAGE_PREVIEW_EXPIRED', '清理预览已过期，请重新预览')
            try:
                current = self._plan(workspace_id, preview['clear_parse_cache'], preview['clear_embedding_cache'])
            except OSError as error:
                raise CatalogError('STORAGE_READ_FAILED', '存储读取失败，未执行清理') from error
            if any(preview[key] != value for key, value in current.items()):
                raise CatalogError('STORAGE_PREVIEW_STALE', '任务、保留策略或文件已改变，请重新预览')
            root = self._root(workspace_id)
            removed, freed = [], 0
            # 先持久化执行状态，部分失败也不可重放旧预览。下一次必须重新核对剩余目录。
            self.store.update('storage_cleanup_preview', preview_id, {'status': 'applying'}, revision)
            for candidate in current['candidates']:
                try:
                    shutil.rmtree(root / candidate['path'])
                    removed.append(candidate['path'])
                    freed += candidate['bytes']
                except OSError:
                    result = {'status': 'partial', 'removed': removed, 'freed_bytes': freed,
                              'message': '部分目录删除失败，请重新预览剩余目录后重试'}
                    self.store.update('storage_cleanup_preview', preview_id, result)
                    self.store.audit('admin', 'storage.cleanup.partial', workspace_id, preview_id)
                    return result
            result = {'status': 'succeeded', 'removed': removed, 'freed_bytes': freed}
            self.store.update('storage_cleanup_preview', preview_id, result)
            self.store.audit('admin', 'storage.cleanup', workspace_id, preview_id)
            return result
