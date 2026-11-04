"""统一空间范围与证据；HTTP/MCP 共享应用对象。"""
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from memory_center.core.foundation.catalog import CatalogError
from memory_center.core.foundation.continuation import (
    CONTINUE_SESSION,
    REBUILD_FROM_PACKET,
    content_boundary,
    continuation_contract,
    session_handle,
)
from memory_center.platform.code_graph import query_code_graph, symbol_fresh
from memory_center.platform.embeddings import Embedder
from memory_center.platform.governance import ASSISTANT_TOOLS, Governance
from memory_center.platform.jobs import Jobs
from memory_center.platform.knowledge import Knowledge
from memory_center.platform.knowledge_tasks import KnowledgeTasks
from memory_center.platform.retrieval import Retrieval, initialize_terms
from memory_center.platform.security import WRITE_TOOLS, Access, Principal
from memory_center.platform.store import PlatformStore
from memory_center.platform.wiki_sources import WikiSources


class Platform:
    def __init__(self, database, catalog):
        self.store, self.catalog = PlatformStore(database), catalog
        self.knowledge = Knowledge(self.store, database.data_dir)
        self.wiki_sources = WikiSources(self.store, catalog)
        self.governance = Governance(self.store, catalog, self.wiki_sources, database.data_dir)
        self.access = Access(self.store, catalog)
        self.retrieval = Retrieval(self.store, self.knowledge)
        self.jobs = Jobs(self.store, catalog, database.data_dir, database.url)
        self.knowledge_tasks = KnowledgeTasks(self)
        self.jobs.knowledge_tasks = self.knowledge_tasks
        initialize_terms(database)
        from memory_center.platform.call_traces import CallTraces
        self.call_traces = CallTraces(self.store)

    def administrator(self):
        workspaces = self.catalog.list(1000)['items']
        return Principal('admin', tuple(w['workspace_id'] for w in workspaces), frozenset(WRITE_TOOLS | ASSISTANT_TOOLS), True)

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
            generic = query_code_graph(index['workspace_file'], query, mode, limit)
            if mode == 'context' and generic and any(s['language'] == 'java' for s in generic['symbols']):
                generic = None
            if generic is not None:
                result = generic
                for symbol in [*result.get('symbols', []), *[e['symbol'] for e in result.get('chain', [])]]:
                    symbol['freshness'] = 'CURRENT' if symbol_fresh(workspace['root'], symbol) else 'STALE'
            elif mode in {'symbol', 'callers', 'callees'}:
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
        result['content_boundary'] = content_boundary(
            data=['items', 'symbols', 'chain'],
            metadata=['generation', 'coverage', 'state', 'freshness', 'ref_id'],
        )
        result['ref_id'] = self.access.reference(actor, workspace_id, result)
        self.store.audit(actor.id, 'lookup', workspace_id)
        return result

    def resume(self, actor, session_id):
        """恢复会话；同时给出接续契约：原会话能不能续、续不上从哪继续。"""
        session = self.access.owned(actor, 'session', session_id)
        state = 'open' if session.get('status') == 'active' else 'closed'
        index_state = self.index_state(session['workspace_id'])
        context_ready = index_state == 'fresh'
        workspace_id = session['workspace_id']
        intent = str(session.get('intent', ''))[:200]
        if state == 'open':
            reason = 'session_active' if context_ready else 'session_active_index_' + index_state
            strategy = CONTINUE_SESSION
            next_action = (
                {'tool': 'mc_lookup', 'argument': {'workspace_id': workspace_id, 'query': intent},
                 'why': '会话仍开启且索引新鲜；继续按 intent 查询项目事实。'}
                if context_ready else
                {'tool': 'mc_index', 'argument': {'workspace_id': workspace_id},
                 'why': '会话仍开启但索引缺失或过期；先重建索引再继续，避免读到旧事实。'}
            )
        else:
            reason = 'session_closed' if context_ready else 'session_closed_index_' + index_state
            strategy = REBUILD_FROM_PACKET
            next_action = (
                {'tool': 'mc_start', 'argument': {'workspace_id': workspace_id, 'intent': intent},
                 'why': '原会话已关闭；按上次 intent 与 outcome 开新会话接手，不重做已完成部分。'}
                if context_ready else
                {'tool': 'mc_index', 'argument': {'workspace_id': workspace_id},
                 'why': '原会话已关闭且索引不可用；先重建索引，再开新会话接手。'}
            )
        continuation = continuation_contract(
            strategy=strategy,
            reason=reason,
            workspace_id=workspace_id,
            session_handle=session_handle('memory-center', session_id, state),
            packet_self_sufficient=context_ready,
            next_action=next_action,
            must_read=[session_id],
        )
        boundary = content_boundary(
            data=['session.intent', 'session.outcome'],
            instruction=['continuation.next_action'],
            metadata=['session.id', 'session.status', 'continuation'],
        )
        return {**session, 'continuation': continuation, 'content_boundary': boundary}

    def index_state(self, workspace_id):
        """索引可用性：fresh / stale / missing；不抛错，交给调用方决定下一步。"""
        try:
            index = self.store.get('index', workspace_id)
        except CatalogError as exc:
            if exc.code == 'RECORD_NOT_FOUND':
                return 'missing'
            raise
        workspace = self.catalog.get(workspace_id)
        return 'fresh' if index.get('config_version') == workspace.get('config_version') else 'stale'

    def analysis_settings(self, actor, workspace_id):
        if actor.id == 'admin':
            self.catalog.get(workspace_id)
        else:
            self.access.scope(actor, workspace_id)
        try:
            return self.store.get('analysis_settings', 'analysis_' + workspace_id)
        except CatalogError as exc:
            if exc.code != 'RECORD_NOT_FOUND':
                raise
            return {'id': workspace_id, 'workspace_id': workspace_id, 'engine': 'auto', 'revision': 0}

    def configure_analysis(self, actor, workspace_id, engine, revision):
        if actor.id == 'admin':
            self.catalog.get(workspace_id)
        else:
            self.access.scope(actor, workspace_id, write=True)
        if engine not in {'auto', 'generic', 'java'}:
            raise CatalogError('ANALYSIS_ENGINE_INVALID', '请选择自动、通用或 Java/Spring 专用分析')
        # 与设置保存共享锁，避免首次创建时两个 revision=0 请求互相覆盖。
        with self.store.generation_lock(workspace_id):
            current = self.analysis_settings(actor, workspace_id)
            if current['revision'] != revision:
                raise CatalogError('REVISION_CONFLICT', '分析设置已改变，请刷新后重试')
            value = {'workspace_id': workspace_id, 'engine': engine}
            result = (self.store.update('analysis_settings', 'analysis_' + workspace_id, value, revision) if revision
                      else self.store.create('analysis_settings', dict(value, id='analysis_' + workspace_id)))
            self.store.audit(actor.id, 'analysis.configure', workspace_id)
            return result

    def analyze(self, actor, workspace_id, target):
        from memory_center.core.orchestrator.impact import memory_impact
        _, index = self.indexed(actor, workspace_id)
        engine = self.analysis_settings(actor, workspace_id)['engine']
        generic = query_code_graph(index['workspace_file'], target, 'analyze', 50)
        symbols = (generic or {}).get('symbols', [])
        java_anchor = len(symbols) == 1 and symbols[0]['language'] == 'java' and not generic.get('truncated')
        use_java = engine == 'java' or (engine == 'auto' and (java_anchor or generic is None))
        if use_java and generic is not None and (not java_anchor):
            # 显式专用配置也不得把非 Java、未命中或歧义锚点转成否定结论。
            result = generic
            result['negative_claim_allowed'] = False
            result['message'] = 'Java/Spring 专用分析需要唯一 Java 锚点，请确认符号或切换分析引擎'
            result['analysis_engine'] = 'java'
        elif use_java:
            result = memory_impact(index['workspace_file'], target, view='minimal', budget='low')
            result['analysis_engine'] = 'java'
        else:
            result = generic if generic is not None else {
                'state': 'INSUFFICIENT_EVIDENCE', 'symbols': [], 'chain': [],
                'negative_claim_allowed': False, 'message': '当前索引没有通用代码图，请重新索引',
            }
            result['analysis_engine'] = 'generic'
            result['impact_scope'] = {
                'FOUND': 'direct_static_callers',
                'INSUFFICIENT_EVIDENCE': 'no_static_callers_in_scope',
                'AMBIGUOUS': 'ambiguous_anchor',
            }.get(result['state'], 'anchor_not_found')
        result['configured_engine'] = engine
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
        for symbol in [*evidence.get('symbols', []), *[e['symbol'] for e in evidence.get('chain', [])]]:
            if symbol.get('hash') and not symbol_fresh(workspace['root'], symbol):
                raise CatalogError('REF_STALE', '代码符号来源已变化，请重新索引后查询')
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
