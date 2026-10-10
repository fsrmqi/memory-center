"""统一空间范围与证据；HTTP/MCP 共享应用对象。"""
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from memory_center.core.foundation.catalog import CatalogError
from memory_center.platform.embeddings import Embedder
from memory_center.platform.jobs import Jobs
from memory_center.platform.knowledge import Knowledge
from memory_center.platform.retrieval import Retrieval, initialize_terms
from memory_center.platform.security import WRITE_TOOLS, Access, Principal
from memory_center.platform.store import PlatformStore
from memory_center.platform.wiki_sources import WikiSources


class Platform:
    def __init__(self, database, catalog):
        self.store, self.catalog = PlatformStore(database), catalog
        self.knowledge = Knowledge(self.store, database.data_dir)
        self.wiki_sources = WikiSources(self.store, catalog)
        self.access = Access(self.store, catalog)
        self.retrieval = Retrieval(self.store, self.knowledge)
        self.jobs = Jobs(self.store, catalog, database.data_dir, database.url)
        initialize_terms(database)

    def administrator(self):
        workspaces = self.catalog.list(1000)['items']
        return Principal('admin', tuple(w['workspace_id'] for w in workspaces), frozenset(WRITE_TOOLS), True)

    def indexed(self, actor, workspace_id):
        workspace = self.access.scope(actor, workspace_id)
        index = self.store.get('index', workspace_id)
        if index['config_version'] != workspace['config_version']:
            raise CatalogError('INDEX_STALE', '项目配置已变化，请重新索引')
        return workspace, index

    def lookup(self, actor, workspace_id, query, mode='hybrid', limit=10, session_id=''):
        workspace = self.access.scope(actor, workspace_id)
        if session_id:
            session = self.access.owned(actor, 'session', session_id, workspace_id)
            if session['status'] != 'active':
                raise CatalogError('SESSION_CLOSED', '会话已关闭')
        if mode in {'symbol', 'callers', 'callees', 'context'}:
            from memory_center.core.orchestrator.query import (
                memory_callees,
                memory_callers,
                memory_context,
                memory_symbol,
            )
            _, index = self.indexed(actor, workspace_id)
            methods = {'symbol': memory_symbol, 'callers': memory_callers, 'callees': memory_callees, 'context': memory_context}
            if mode in {'symbol', 'callers', 'callees'}:
                result = methods[mode](index['workspace_file'], query, limit=min(limit, 50), view='minimal')
            else:
                result = memory_context(index['workspace_file'], query, view='minimal')
            result['workspace_id'] = workspace_id
            result['generation'] = index['generation']
        else:
            result = self.retrieval.search(workspace, actor, query, mode, limit)
            # 源码命中实时核对哈希，只核对有界候选，不重建索引。
            for item in result.get('items', []):
                source = item['source']
                if source['kind'] == 'code':
                    path = Path(workspace['root']) / source['path']
                    try:
                        valid = not path.is_symlink() and path.resolve().is_relative_to(Path(workspace['root']))
                        valid = valid and path.stat().st_size <= 1024 * 1024
                        content = path.read_text(encoding='utf-8', errors='replace') if valid else ''
                        item['freshness'] = 'CURRENT' if valid and hashlib.sha256(content.encode()).hexdigest() == source['hash'] else 'STALE'
                    except OSError:
                        item['freshness'] = 'STALE'
                elif source.get('wiki_source_id'):
                    item['freshness'] = 'CURRENT' if self.wiki_sources.fresh(source) else 'STALE'
                else:
                    item['freshness'] = 'CURRENT'
        result['ref_id'] = self.access.reference(actor, workspace_id, result)
        self.store.audit(actor.id, 'lookup', workspace_id)
        return result

    def analyze(self, actor, workspace_id, target):
        from memory_center.core.orchestrator.impact import memory_impact
        _, index = self.indexed(actor, workspace_id)
        result = memory_impact(index['workspace_file'], target, view='minimal', budget='low')
        result['workspace_id'], result['generation'] = workspace_id, index['generation']
        result['ref_id'] = self.access.reference(actor, workspace_id, result)
        return result

    def model(self, settings):
        Embedder.validate(settings)
        current = self.store.list('model', limit=1)
        value = self.store.update('model', current[0]['id'], settings, current[0]['revision']) if current else self.store.create('model', settings)
        self.store.audit('admin', 'model.update')
        return dict(value, reindex_required=True)

    def wiki_draft(self, actor, workspace_id, title, query):
        result = self.lookup(actor, workspace_id, query, 'hybrid', 10)
        items = [item for item in result.get('items', []) if item.get('freshness') != 'STALE']
        body = '# ' + title + '\n\n以下内容依据已索引来源摘录生成，待人工整理。\n'
        for item in items:
            source = item['source']
            name = source.get('path') or source.get('title', source['source_id'])
            body += f'\n## {name}\n\n{item["content"]}\n\n来源：{name}，行 {source["line"]}–{source["end_line"]}\n'
        return {'title': title, 'content': body, 'refs': [result['ref_id']], 'requires_review': True,
                'generation': result.get('generation'), 'source_count': len(items)}

    def resolve_reference(self, actor, ref_id):
        record = self.access.owned(actor, 'ref', ref_id)
        workspace, index = self.indexed(actor, record['workspace_id'])
        evidence = record['evidence']
        if evidence.get('generation') != index['generation']:
            raise CatalogError('REF_STALE', '引用所属索引已更新，请重新查询')
        active = {item['id']: item for _, item in self.knowledge.active(record['workspace_id'])}
        replaced = {item.get('replaces') for item in active.values() if item.get('replaces')}
        for item in evidence.get('items', []):
            source = item['source']
            if source['kind'] == 'code':
                path = Path(workspace['root']) / source['path']
                try:
                    if path.is_symlink() or not path.resolve().is_relative_to(Path(workspace['root'])) or path.stat().st_size > 1024 * 1024:
                        raise OSError()
                    text = path.read_text(encoding='utf-8', errors='replace')
                    if hashlib.sha256(text.encode()).hexdigest() != source['hash']:
                        raise OSError()
                except OSError:
                    raise CatalogError('REF_STALE', '引用源码已变化或失效，请重新查询') from None
            elif source['source_id'] in replaced or source['source_id'] not in active or active[source['source_id']]['revision'] != source['source_revision']:
                raise CatalogError('REF_STALE', '引用来源已删除或修订，请重新查询')
            elif source.get('wiki_source_id') and not self.wiki_sources.fresh(source):
                raise CatalogError('REF_STALE', '引用 Wiki 文件已变化或目录失效，请同步后重新查询')
            elif active[source['source_id']].get('expires_at') and datetime.fromisoformat(active[source['source_id']]['expires_at']) < datetime.now(timezone.utc):
                raise CatalogError('REF_STALE', '引用记忆已过期，请重新查询')
        return record

    def validate_wiki_refs(self, actor, workspace_id, refs):
        for ref_id in refs:
            record = self.resolve_reference(actor, ref_id)
            if record['workspace_id'] != workspace_id:
                raise CatalogError('FORBIDDEN', 'Wiki 来源引用不属于当前项目')
