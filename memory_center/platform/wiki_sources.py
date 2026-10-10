"""本地 Markdown Wiki 的只读来源登记与完整快照增量同步。"""
import hashlib
import json
import os
from pathlib import Path

from filelock import FileLock

from memory_center.core.foundation.catalog import CatalogError
from memory_center.platform.store import now


class WikiSources:
    def __init__(self, store, catalog=None):
        self.store, self.catalog = store, catalog

    def lock(self):
        return FileLock(str(self.store.db.data_dir / 'wiki-sources.lock'), timeout=120)

    def sources(self):
        return self.store.list('wiki_source', limit=101)

    def validate(self, name, root, workspace_ids, existing=False):
        path = Path(root).expanduser()
        if not name.strip() or not path.is_absolute() or (not existing and (not path.is_dir() or path.is_symlink())):
            raise CatalogError('WIKI_ROOT_INVALID', '请填写名称和可读取的绝对目录；容器内需先挂载目录')
        if len(set(workspace_ids)) != len(workspace_ids):
            raise CatalogError('WIKI_SCOPE_INVALID', '关联项目不可重复')
        for workspace_id in workspace_ids:
            self.catalog.get(workspace_id)
        return {'name': name.strip(), 'root': str(path) if existing else str(path.resolve()), 'workspace_ids': workspace_ids}

    def save(self, name, root, workspace_ids, record_id='', revision=None, status='active', auto_sync=True):
        values = self.validate(name, root, workspace_ids, existing=bool(record_id))
        with self.lock():
            sources = self.sources()
            if any(s['root'] == values['root'] and s['id'] != record_id and s['status'] != 'deleted' for s in sources):
                raise CatalogError('ROOT_DUPLICATE', '此 Wiki 目录已登记，请修改已有来源的项目关联')
            values.update(status=status, auto_sync=auto_sync)
            if record_id:
                current = self.store.get('wiki_source', record_id)
                if current['root'] != values['root']:
                    raise CatalogError('WIKI_ROOT_IMMUTABLE', '目录路径不可修改，请移除后重新登记')
                result = self.store.update('wiki_source', record_id, values, revision)
            else:
                if len(sources) >= 100:
                    raise CatalogError('WIKI_SOURCE_LIMIT', '最多登记 100 个来源')
                result = self.store.create('wiki_source', dict(values, content_version=0, page_count=0,
                                                               sync_state='pending', last_sync='', error=''))
            self.store.audit('admin', 'wiki_source.save', record_id=result['id'])
            return result

    def remove(self, record_id):
        with self.lock():
            result = self.store.update('wiki_source', record_id, {'status': 'deleted'})
            self.store.audit('admin', 'wiki_source.remove', record_id=record_id)
            return result

    def signature(self, workspace_id):
        values = sorted((s['id'], s['name'], s['content_version']) for s in self.sources()
                        if s['status'] == 'active' and workspace_id in s['workspace_ids'])
        return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode()).hexdigest()

    def scan(self, root):
        root = Path(root)
        if root.is_symlink() or not root.is_dir() or root.resolve() != root:
            raise CatalogError('WIKI_ROOT_UNAVAILABLE', 'Wiki 目录不存在或挂载已失效，上次结果保持不变')
        pages, total = {}, 0

        def fail(error):
            raise error

        for parent, dirs, files in os.walk(root, followlinks=False, onerror=fail):
            dirs[:] = sorted(d for d in dirs if not d.startswith('.') and d not in {'node_modules', 'vendor'}
                             and not (Path(parent) / d).is_symlink())
            for name in sorted(files):
                path = Path(parent) / name
                if name.startswith('.') or path.suffix.lower() not in {'.md', '.markdown'} or path.is_symlink():
                    continue
                if not path.resolve().is_relative_to(root):
                    raise CatalogError('WIKI_PATH_INVALID', '文件已移出 Wiki 目录')
                # 有界读取，防止扫描期间文件增长突破预算。
                with path.open('rb') as stream:
                    raw = stream.read(1024 * 1024 + 1)
                total += len(raw)
                if len(raw) > 1024 * 1024 or len(pages) >= 2000 or total > 32 * 1024 * 1024:
                    raise CatalogError('WIKI_SCAN_LIMIT', '每个目录上限 2000 页、32 MiB，单页 1 MiB')
                text = raw.decode('utf-8-sig')
                relative = path.relative_to(root).as_posix()
                title = next((line[2:].strip() for line in text.splitlines() if line.startswith('# ')), path.stem)
                pages[relative] = {'content': text, 'hash': hashlib.sha256(text.encode()).hexdigest(),
                                   'title': title[:200] or path.stem[:200]}
        return pages

    def sync(self, record_id):
        with self.lock():
            source = self.store.get('wiki_source', record_id)
            if source['status'] != 'active':
                raise CatalogError('WIKI_SOURCE_PAUSED', 'Wiki 来源已暂停或移除')
            try:
                pages = self.scan(source['root'])
                counts = {'added': 0, 'updated': 0, 'deleted': 0, 'unchanged': 0}
                with self.store.db.connection(True) as connection:
                    rows = connection.execute("SELECT payload FROM records WHERE kind='wiki' AND workspace_id=?",
                                              (record_id,)).fetchall()
                    old = {p['relative_path']: p for row in rows if (p := json.loads(row[0]))}
                    for relative, page in pages.items():
                        current = old.get(relative)
                        if current and current['status'] == 'active' and current['hash'] == page['hash']:
                            counts['unchanged'] += 1
                            continue
                        key = 'updated' if current else 'added'
                        counts[key] += 1
                        identifier = 'wiki_' + hashlib.sha256((record_id + ':' + relative).encode()).hexdigest()
                        item = dict(page, id=identifier, workspace_id=record_id, owner='admin',
                                    wiki_source_id=record_id, relative_path=relative, readonly=True, refs=[], versions=[],
                                    status='active', revision=current['revision'] + 1 if current else 1,
                                    created_at=current['created_at'] if current else now(), updated_at=now())
                        self.store._put(connection, 'wiki', item)
                    for relative, current in old.items():
                        if relative not in pages and current['status'] != 'deleted':
                            counts['deleted'] += 1
                            self.store._put(connection, 'wiki', dict(current, status='deleted',
                                            revision=current['revision'] + 1, updated_at=now()))
                    changed = counts['added'] + counts['updated'] + counts['deleted']
                    source.update(content_version=source['content_version'] + bool(changed), page_count=len(pages),
                                  sync_state='ready', last_sync=now(), error='', last_result=counts,
                                  revision=source['revision'] + bool(changed), updated_at=now())
                    self.store._put(connection, 'wiki_source', source)
                return dict(source, changed=bool(changed))
            except (OSError, UnicodeError, CatalogError) as exc:
                code = exc.code if isinstance(exc, CatalogError) else 'WIKI_READ_FAILED'
                self.store.update('wiki_source', record_id, {'sync_state': 'failed', 'error': code, 'last_attempt': now()})
                raise CatalogError(code, 'Wiki 同步失败，请检查目录权限、挂载、UTF-8 编码及扫描预算；上次完整结果已保留') from None

    def pages(self, workspace_id):
        for source in self.sources():
            if source['status'] == 'active' and workspace_id in source['workspace_ids']:
                predicate = "payload::jsonb->>'status'='active'" if self.store.db.url else "json_extract(payload,'$.status')='active'"
                with self.store.db.connection() as connection:
                    rows = connection.execute(f"SELECT payload FROM records WHERE kind='wiki' AND workspace_id=? AND {predicate} ORDER BY id LIMIT 2000",
                                              (source['id'],)).fetchall()
                for row in rows:
                    yield dict(json.loads(row[0]), workspace_id=workspace_id, source_name=source['name'])

    def fresh(self, metadata):
        try:
            source = self.store.get('wiki_source', metadata['wiki_source_id'])
            root = Path(source['root'])
            path = root / metadata['relative_path']
            if source['status'] != 'active' or root.is_symlink() or not root.is_dir():
                return False
            if path.is_symlink() or any(p.is_symlink() for p in path.parents if p != root.parent):
                return False
            if not path.resolve().is_relative_to(root) or path.stat().st_size > 1024 * 1024:
                return False
            with path.open('rb') as stream:
                raw = stream.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                return False
            text = raw.decode('utf-8-sig')
            return hashlib.sha256(text.encode()).hexdigest() == metadata['hash']
        except (OSError, UnicodeError, CatalogError):
            return False
