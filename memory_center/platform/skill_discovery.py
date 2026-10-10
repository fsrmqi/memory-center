"""管理员显式登记全局 Skill 目录，扫描只读，启停仅作用于本服务。"""
import hashlib
import json
import os
from pathlib import Path

import yaml
from filelock import FileLock

from memory_center.core.foundation.catalog import CatalogError
from memory_center.platform.store import now


class SkillDiscovery:
    def __init__(self, store, base):
        self.store = store
        self.lock = FileLock(str(base / 'skill-discovery.lock'), timeout=120)

    def sources(self):
        return self.store.list('skill_source', limit=51)

    def configure(self, name, root, enabled=False, max_depth=4, record_id='', revision=None):
        path = Path(root).expanduser()
        if not path.is_absolute() or path.is_symlink() or (not path.is_dir() and (not record_id or enabled)):
            raise CatalogError('SKILL_ROOT_INVALID', '目录必须是服务可读取的绝对路径，且不能是符号链接')
        path = path.resolve()
        with self.lock:
            sources = self.sources()
            if any(s['root'] == str(path) and s['id'] != record_id for s in sources):
                raise CatalogError('SKILL_SOURCE_EXISTS', '该目录已登记')
            if not record_id and len(sources) >= 50:
                raise CatalogError('SKILL_SOURCE_LIMIT', '最多登记 50 个扫描目录')
            changes = {'name': name, 'root': str(path), 'enabled': enabled, 'max_depth': max_depth}
            if record_id:
                current = self.store.get('skill_source', record_id)
                if current['root'] != str(path):
                    raise CatalogError('SKILL_ROOT_IMMUTABLE', '请移除原目录后重新登记新目录')
                item = self.store.update('skill_source', record_id, changes, revision)
            else:
                item = self.store.create('skill_source', dict(changes, last_scan='', scan_count=0))
            self.store.audit('admin', 'skill_discovery.configure', record_id=item['id'])
            return item

    def remove_source(self, source_id, revision):
        with self.lock, self.store.db.connection(True) as connection:
            row = connection.execute("SELECT payload FROM records WHERE kind='skill_source' AND id=?", (source_id,)).fetchone()
            if not row:
                raise CatalogError('RECORD_NOT_FOUND', '扫描目录不存在')
            if json.loads(row[0])['revision'] != revision:
                raise CatalogError('REVISION_CONFLICT', '配置已改变，请刷新后重试')
            connection.execute("DELETE FROM records WHERE kind='discovered_skill' AND workspace_id=?", (source_id,))
            connection.execute("DELETE FROM records WHERE kind='skill_source' AND id=?", (source_id,))
        return {'removed': True, 'original_files_unchanged': True}

    def scan(self, source_id):
        with self.lock:
            source = self.store.get('skill_source', source_id)
            if not source['enabled']:
                raise CatalogError('SKILL_SOURCE_DISABLED', '请先启用扫描目录')
            root = Path(source['root'])
            if not root.is_dir() or root.is_symlink():
                raise CatalogError('SKILL_ROOT_INVALID', '扫描目录不可读取，请检查挂载')
            found, entries, skipped = {}, 0, 0
            def failed(error):
                raise error
            try:
                for parent, dirs, files in os.walk(root, followlinks=False, onerror=failed):
                    folder = Path(parent)
                    depth = len(folder.relative_to(root).parts)
                    entries += len(dirs) + len(files)
                    if entries > 20000:
                        raise CatalogError('SKILL_SCAN_LIMIT', '扫描超过 20000 个目录项，请缩小范围；原快照保留')
                    skipped += sum((folder / d).is_symlink() for d in dirs)
                    dirs[:] = sorted(d for d in dirs if d not in {'.git', 'node_modules', '.venv', 'vendor'}
                                     and not (folder / d).is_symlink() and depth < source['max_depth'])
                    if 'SKILL.md' not in files:
                        continue
                    path = folder / 'SKILL.md'
                    if path.is_symlink() or any(p.is_symlink() for p in path.parents if p != root.parent):
                        skipped += 1
                        continue
                    with path.open('rb') as stream:
                        raw = stream.read(1024 * 1024 + 1)
                    if len(raw) > 1024 * 1024:
                        raise CatalogError('SKILL_SCAN_LIMIT', '单份 SKILL.md 超过 1 MiB；原快照保留')
                    text = raw.decode('utf-8-sig').replace('\r\n', '\n')
                    metadata = {}
                    if text.startswith('---\n'):
                        sections = text.split('---', 2)
                        if len(sections) == 3:
                            parsed = yaml.safe_load(sections[1])
                            if isinstance(parsed, dict):
                                metadata = parsed
                                if any(not isinstance(metadata.get(key, ''), str) for key in ('name', 'description')):
                                    raise CatalogError('SKILL_METADATA_INVALID', 'Skill 名称和描述必须是文本；原快照保留')
                    relative = path.relative_to(root).as_posix()
                    record_id = 'discovered_' + hashlib.sha256((source_id + ':' + relative).encode()).hexdigest()
                    found[record_id] = {'id': record_id, 'workspace_id': source_id, 'source_id': source_id,
                                        'name': str(metadata.get('name') or folder.name)[:200],
                                        'description': str(metadata.get('description') or '')[:2000],
                                        'relative_path': relative, 'sha256': hashlib.sha256(raw).hexdigest()}
            except (OSError, UnicodeError, yaml.YAMLError) as exc:
                raise CatalogError('SKILL_SCAN_FAILED', '扫描失败，请检查权限、UTF-8 和 Skill 元数据；原快照保留') from exc
            timestamp = now()
            with self.store.db.connection(True) as connection:
                rows = connection.execute("SELECT payload FROM records WHERE kind='discovered_skill' AND workspace_id=?", (source_id,)).fetchall()
                previous = {i['id']: i for i in (json.loads(r[0]) for r in rows)}
                for record_id, item in found.items():
                    old = previous.get(record_id, {})
                    enabled = old.get('status') == 'enabled' and old.get('sha256') == item['sha256']
                    self.store._put(connection, 'discovered_skill', dict(item, status='enabled' if enabled else 'disabled',
                                    revision=old.get('revision', 0) + 1, created_at=old.get('created_at', timestamp), updated_at=timestamp))
                for record_id, old in previous.items():
                    if record_id not in found:
                        self.store._put(connection, 'discovered_skill', dict(old, status='missing', revision=old['revision'] + 1, updated_at=timestamp))
                source.update(last_scan=timestamp, scan_count=len(found), revision=source['revision'] + 1)
                self.store._put(connection, 'skill_source', source)
            self.store.audit('admin', 'skill_discovery.scan', record_id=source_id)
            return {'found': len(found), 'skipped_symlinks': skipped, 'original_files_unchanged': True}

    def list_page(self, page=1, page_size=20, query='', status='', source_id=''):
        result = self.store.list_page('discovered_skill', page, page_size, query, status,
                                      ('name', 'description', 'relative_path'), source_id or None)
        sources = {s['id']: s for s in self.sources()}
        for item in result['items']:
            source = sources.get(item['source_id'], {})
            item.update(source_name=source.get('name', '已移除目录'), source_enabled=source.get('enabled', False),
                        available=item['status'] == 'enabled' and source.get('enabled', False))
        return result

    def set_enabled(self, record_id, enabled, revision):
        with self.lock:
            item = self.store.get('discovered_skill', record_id)
            if enabled:
                self.read(record_id, allow_disabled=True)
            value = self.store.update('discovered_skill', record_id, {'status': 'enabled' if enabled else 'disabled'}, revision)
            self.store.audit('admin', 'skill_discovery.enable' if enabled else 'skill_discovery.disable', record_id=record_id)
            return value

    def read(self, record_id, allow_disabled=True):
        item = self.store.get('discovered_skill', record_id)
        source = self.store.get('skill_source', item['source_id'])
        if not source['enabled'] or item['status'] == 'missing' or (not allow_disabled and item['status'] != 'enabled'):
            raise CatalogError('SKILL_UNAVAILABLE', 'Skill 或扫描目录未启用，或文件已不存在')
        root = Path(source['root'])
        path = root / item['relative_path']
        if root.is_symlink() or path.is_symlink() or not path.resolve().is_relative_to(root.resolve()) or any(p.is_symlink() for p in path.parents if p != root.parent):
            raise CatalogError('SKILL_UNAVAILABLE', 'Skill 路径已经改变，请重新扫描')
        try:
            with path.open('rb') as stream:
                raw = stream.read(1024 * 1024 + 1)
            if hashlib.sha256(raw).hexdigest() != item['sha256'] or len(raw) > 1024 * 1024:
                raise CatalogError('SKILL_STALE', 'Skill 内容已改变，请重新扫描并审阅后启用')
            return dict(item, body=raw.decode('utf-8-sig'), source_name=source['name'])
        except (OSError, UnicodeError) as exc:
            raise CatalogError('SKILL_UNAVAILABLE', 'Skill 文件不可读取，请重新扫描') from exc
