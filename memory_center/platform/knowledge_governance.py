"""模型辅助的重复／冲突建议；来源引文可核对，决定需人工确认并原子保存。"""
import collections
import hashlib
import itertools
import json
import math
from datetime import datetime, timedelta, timezone

from memory_center.core.foundation.catalog import CatalogError
from memory_center.platform.diagnostics import failure_receipt
from memory_center.platform.intelligence import ChatModel, Intelligence
from memory_center.platform.retrieval import tokens
from memory_center.platform.store import identity, now


class GovernanceCancelled(Exception):
    pass


def text_field(value, maximum, required=True):
    if not isinstance(value, str) or len(value) > maximum or (required and not value.strip()):
        raise CatalogError('CHAT_RESPONSE_INVALID', '治理模型字段无效，请检查模型或减少资料后手动重试')
    return value.strip()


def candidate_pairs(summaries, limit):
    """小库全配对；大库以模型摘要词项召回，每条最多八个邻居，并显式报告覆盖。"""
    ids = sorted(summaries)
    possible = len(ids) * (len(ids) - 1) // 2
    if len(ids) <= 32:
        pairs = list(itertools.combinations(ids, 2))
    else:
        postings = collections.defaultdict(set)
        words = {}
        for key, summary in summaries.items():
            words[key] = set(tokens(summary))
            for word in words[key]:
                postings[word].add(key)
        ranked = {}
        for key in ids:
            scores = collections.Counter()
            for word in words[key]:
                # 普遍词不作为全库两两展开的依据。
                if len(postings[word]) > 200:
                    continue
                for other in postings[word]:
                    if other != key:
                        scores[other] += 1 / len(postings[word])
            for other, score in sorted(scores.items(), key=lambda x: (-x[1], x[0]))[:8]:
                pair = tuple(sorted((key, other)))
                ranked[pair] = max(ranked.get(pair, 0), score)
        pairs = sorted(ranked, key=lambda p: (-ranked[p], p))
    return pairs[:limit], {'possible_pairs': possible, 'candidate_pairs': len(pairs),
                          'compared_pairs': 0, 'exhaustive': len(pairs) == possible and len(pairs) <= limit,
                          'budget_limited': len(pairs) > limit, 'pair_limit': limit,
                          'recall': 'all_pairs' if len(ids) <= 32 else 'model_summary_keywords_top8'}


class KnowledgeGovernance:
    def __init__(self, platform):
        self.platform, self.store = platform, platform.store
        self.intelligence = Intelligence(platform)

    def list_page(self, workspace_id, kind, page, page_size, status, category):
        field = lambda n: f"payload::jsonb->>'{n}'" if self.store.db.url else f"json_extract(payload,'$.{n}')"
        where, args = f"kind='governance_preview' AND workspace_id=? AND {field('kind')}=?", [workspace_id, kind]
        for name, value in [('status', status), ('category', category)]:
            if value:
                where += f' AND {field(name)}=?'
                args.append(value)
        with self.store.db.connection() as c:
            if self.store.db.url:
                c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            total = c.execute(f'SELECT count(*) FROM records WHERE {where}', args).fetchone()[0]
            pages = max(1, math.ceil(total / page_size)); page = min(page, pages)
            rows = c.execute(f'SELECT payload FROM records WHERE {where} ORDER BY updated_at DESC,id DESC LIMIT ? OFFSET ?',
                             (*args, page_size, (page - 1) * page_size)).fetchall()
        return {'items': [json.loads(r[0]) for r in rows], 'total': total, 'page': page, 'page_size': page_size, 'pages': pages}

    def read(self, workspace_id, preview_id):
        draft = self.store.get('governance_preview', preview_id)
        if draft['workspace_id'] != workspace_id:
            raise CatalogError('FORBIDDEN', '治理建议不属于当前项目')
        sources = []
        for saved in draft['sources']:
            item = dict(saved)
            try:
                current = self.intelligence.source(workspace_id, draft['kind'], saved['id'])
                item.update(content=current['content'], current_revision=current['revision'],
                            stale=current['revision'] != saved['revision'])
            except CatalogError as error:
                item.update(stale=True, unavailable=error.message)
            sources.append(item)
        return dict(draft, sources=sources)

    def run(self, task_id):
        tasks = self.platform.knowledge_tasks
        with tasks.lock:
            task = self.store.get('knowledge_task', task_id)
            if task['status'] != 'queued':
                return
            self.store.update('knowledge_task', task_id, {'status': 'running', 'phase': 'summarizing', 'started_at': now()})
        def check():
            if tasks.stopping or self.store.get('knowledge_task', task_id)['status'] != 'running':
                raise GovernanceCancelled()
        workspace_id, kind = task['workspace_id'], task['kind']
        snapshots = {s['id']: s['revision'] for s in task['sources']}
        def source(key):
            item = self.intelligence.source(workspace_id, kind, key)
            if item['revision'] != snapshots[key]:
                raise CatalogError('REVISION_CONFLICT', '治理来源已变化，请重新分析；原文未改动')
            return item
        settings = self.store.list('chat_model', limit=1)
        model = ChatModel(settings[0] if settings else {})
        metrics = {'requests': 0, 'duration_seconds': 0.0, 'input_tokens': 0, 'output_tokens': 0}
        def ask(contract, records):
            check()
            text = contract + '\n资料 JSON：\n' + json.dumps(records, ensure_ascii=False)
            if len(text) > 120000:
                raise CatalogError('CHAT_INPUT_LIMIT', '治理比较输入超出 12 万字符，请拆分超大来源')
            result = model.generate(text, structured=True)
            check()
            metrics['requests'] += 1
            m = getattr(model, 'metrics', {})
            metrics['duration_seconds'] += m.get('duration_seconds', 0)
            for k in ('input_tokens', 'output_tokens'):
                metrics[k] = (metrics[k] + m[k]) if metrics[k] is not None and m.get(k) is not None else None
            try:
                value = json.loads(result)
                if not isinstance(value, dict):
                    raise ValueError()
                return value
            except (ValueError, TypeError) as exc:
                raise CatalogError('CHAT_RESPONSE_INVALID', '治理模型未返回 JSON 对象，未发布建议') from exc
        try:
            summaries = {}
            # 每篇完整阅读，不截断来源；提取出的摘要仅用于候选召回，最终判断仍使用原文。
            for key in snapshots:
                check(); item = source(key)
                value = ask('提取资料的主题、实体和关键事实，用简体中文统一表述同义概念。返回 {"summary":"不超过2000字的摘要"}。',
                            {'id': key, 'title': item['title'], 'content': item['content']})
                summaries[key] = item['title'] + ' ' + text_field(value.get('summary'), 2000)
                self.store.update('knowledge_task', task_id, {'completed': len(summaries), 'chat_metrics': metrics})
            pairs, coverage = candidate_pairs(summaries, task.get('pair_limit', 500))
            self.store.update('knowledge_task', task_id, {'phase': 'comparing', 'completed': 0, 'total': len(pairs), 'coverage': coverage})
            previews = []
            for a, b in pairs:
                check(); originals = [source(a), source(b)]
                value = ask('比较两份完整来源：同一事实的不同表达为 duplicate；同一时间和范围内不相容的主张为 conflict；其它为 unrelated。'
                            '冲突合并稿必须保留两种主张并注明待核实，不选择真伪。返回 {"category":"duplicate|conflict|unrelated",'
                            '"confidence":0.0到1.0,"reason":"理由","title":"合并标题","content":"合并 Markdown 正文",'
                            '"quotes":{"第一个来源id":"原文逐字引文","第二个来源id":"原文逐字引文"}}。unrelated 只需 category。',
                            [{'id': i['id'], 'title': i['title'], 'content': i['content'],
                              'status': i['status'], 'expires_at': i.get('expires_at', ''),
                              'updated_at': i['updated_at']} for i in originals])
                category = value.get('category')
                if category not in {'duplicate', 'conflict', 'unrelated'}:
                    raise CatalogError('CHAT_RESPONSE_INVALID', '治理分类无效，未发布建议')
                if category != 'unrelated':
                    confidence = value.get('confidence')
                    if type(confidence) not in (float, int) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
                        raise CatalogError('CHAT_RESPONSE_INVALID', '治理置信度无效，未发布建议')
                    quotes = value.get('quotes')
                    if not isinstance(quotes, dict) or set(quotes) != {a, b}:
                        raise CatalogError('CHAT_RESPONSE_INVALID', '治理引用来源不匹配，未发布建议')
                    sources = []
                    for item in originals:
                        quote = text_field(quotes[item['id']], 2000)
                        if quote not in item['content']:
                            raise CatalogError('CHAT_EVIDENCE_INVALID', '模型引文不能在原文中找到，未发布建议')
                        sources.append({k: item[k] for k in ('id', 'revision', 'title')})
                        sources[-1].update(quote=quote, readonly=bool(item.get('readonly')), status=item['status'],
                            expires_at=item.get('expires_at', ''),
                            hash=hashlib.sha256(item['content'].encode()).hexdigest())
                    previews.append({'id': identity('governance_preview'), 'workspace_id': workspace_id, 'kind': kind,
                        'task_id': task_id, 'category': category, 'confidence': confidence,
                        'reason': text_field(value.get('reason'), 4000), 'title': text_field(value.get('title'), 200),
                        'content': text_field(value.get('content'), 10000 if kind == 'memory' else 200000),
                        'sources': sources, 'status': 'pending', 'model': model.settings['model'], 'requires_review': True,
                        'expires_at': (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()})
                coverage['compared_pairs'] += 1
                self.store.update('knowledge_task', task_id, {'completed': coverage['compared_pairs'], 'coverage': coverage,
                                  'chat_metrics': metrics, 'suggestion_count': len(previews)})
            # 不发布半套建议：取消、来源修订改变或异常时原文和建议列表均保持不变。
            with tasks.lock, self.store.generation_lock(workspace_id), self.platform.wiki_sources.lock(), self.store.db.connection(True) as c:
                check()
                suffix = ' FOR UPDATE' if self.store.db.url else ''
                for key in sorted(snapshots):
                    source(key)
                    row = c.execute('SELECT payload FROM records WHERE kind=? AND id=?' + suffix, (kind, key)).fetchone()
                    if not row or json.loads(row[0])['revision'] != snapshots[key]:
                        raise CatalogError('REVISION_CONFLICT', '治理来源已变化，未发布建议')
                stamp = now()
                for preview in previews:
                    preview.update(revision=1, created_at=stamp, updated_at=stamp)
                    self.store._put(c, 'governance_preview', preview)
                current = self.store.get('knowledge_task', task_id)
                current.update(status='succeeded', phase='review', preview_ids=[p['id'] for p in previews],
                               coverage=coverage, chat_metrics=metrics, finished_at=stamp, revision=current['revision'] + 1)
                self.store._put(c, 'knowledge_task', current)
        except GovernanceCancelled:
            return
        except Exception as exc:
            with tasks.lock:
                if self.store.get('knowledge_task', task_id)['status'] == 'running':
                    self.store.update('knowledge_task', task_id, {'status': 'failed', 'finished_at': now(),
                        **failure_receipt(exc, phase='governance', subject=task_id)})

    def decide(self, workspace_id, preview_id, revision, decision, confirm=False, title='', content='',
               retire_source_ids=None, confirm_memory=False):
        if not confirm:
            raise CatalogError('CONFIRM_REQUIRED', '请审阅来源和合并稿后明确确认处理')
        retired = sorted(set(retire_source_ids or []))
        digest = hashlib.sha256(json.dumps([decision, title, content, retired, confirm_memory], ensure_ascii=False).encode()).hexdigest()
        with self.store.generation_lock(workspace_id), self.platform.wiki_sources.lock(), self.store.db.connection(True) as c:
            suffix = ' FOR UPDATE' if self.store.db.url else ''
            row = c.execute("SELECT payload FROM records WHERE kind='governance_preview' AND id=?" + suffix, (preview_id,)).fetchone()
            if not row:
                raise CatalogError('RECORD_NOT_FOUND', '治理建议不存在')
            draft = json.loads(row[0])
            if draft['workspace_id'] != workspace_id:
                raise CatalogError('FORBIDDEN', '治理建议不属于当前项目')
            if draft['status'] != 'pending':
                if draft.get('decision_hash') != digest:
                    raise CatalogError('REVISION_CONFLICT', '此建议已处理，请刷新')
                return draft
            if revision != draft['revision']:
                raise CatalogError('REVISION_CONFLICT', '建议已变化，请刷新')
            if decision != 'dismiss' and datetime.now(timezone.utc) > datetime.fromisoformat(draft['expires_at']):
                raise CatalogError('PREVIEW_EXPIRED', '治理建议已过期，请重新分析')
            if self.store.get('knowledge_task', draft['task_id'])['status'] != 'succeeded':
                raise CatalogError('JOB_STATE', '分析任务未完成，不能保存治理建议')
            kind = draft['kind']; items = []
            for s in sorted(draft['sources'], key=lambda s: s['id']) if decision != 'dismiss' else []:
                original = self.intelligence.source(workspace_id, kind, s['id'])
                row = c.execute('SELECT payload FROM records WHERE kind=? AND id=?' + suffix, (kind, s['id'])).fetchone()
                if not row:
                    raise CatalogError('REVISION_CONFLICT', '来源已移除，请重新分析')
                current = json.loads(row[0])
                if current['revision'] != s['revision'] or hashlib.sha256(current['content'].encode()).hexdigest() != s['hash']:
                    raise CatalogError('REVISION_CONFLICT', '来源已改变，请重新分析；原内容未覆盖')
                items.append(original)
            if retired and (decision != 'merge' or not set(retired) <= {i['id'] for i in items} or
                            any(i.get('readonly') for i in items if i['id'] in retired)):
                raise CatalogError('GOVERNANCE_RETIRE_INVALID', '仅合并时可移除本组可编辑来源，目录原文件只读')
            stamp = now(); result_id = ''
            if decision == 'merge':
                title = text_field(title, 200); content = text_field(content, 10000 if kind == 'memory' else 200000)
                if retired and kind == 'memory' and not confirm_memory:
                    raise CatalogError('MEMORY_CONFIRM_REQUIRED', '请先确认合并后的记忆为事实，再移除原记忆')
                result_id = identity(kind)
                merged = {'id': result_id, 'workspace_id': workspace_id, 'owner': 'admin', 'title': title if kind == 'wiki' else content[:80],
                    'content': content, 'status': 'active' if kind == 'wiki' else ('confirmed' if confirm_memory else 'pending'),
                    'refs': list(dict.fromkeys(ref for i in items for ref in i.get('refs', []))), 'versions': [],
                    'governance_sources': draft['sources'], 'governance_model': draft['model'], 'governance_preview_id': preview_id,
                    'revision': 1, 'created_at': stamp, 'updated_at': stamp}
                if kind == 'memory':
                    expiries = [i['expires_at'] for i in items if i.get('expires_at')]
                    merged['expires_at'] = min(expiries, key=datetime.fromisoformat) if expiries else ''
                self.store._put(c, kind, merged)
                for original in items:
                    if original['id'] in retired:
                        removed = dict(original, status='deleted', governance_retired_by=result_id,
                                       revision=original['revision'] + 1, updated_at=stamp)
                        self.store._put(c, kind, removed)
            draft.update(status={'merge': 'merged', 'keep_both': 'kept', 'dismiss': 'dismissed'}[decision],
                decision=decision, decision_hash=digest, result_id=result_id, retired_source_ids=retired,
                revision=revision + 1, updated_at=stamp)
            if decision == 'merge':
                draft.update(reviewed_title=title, reviewed_content=content)
            self.store._put(c, 'governance_preview', draft)
            self.store._put(c, 'audit', {'id': identity('audit'), 'workspace_id': workspace_id, 'owner': 'admin',
                'action': 'governance.' + decision, 'target': preview_id, 'result_id': result_id,
                'revision': 1, 'created_at': stamp, 'updated_at': stamp})
            return draft
