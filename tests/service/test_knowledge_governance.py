"""智能治理的模型合同、来源证据、人工决策和事务边界。"""
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from memory_center.platform.intelligence import ChatModel
from memory_center.platform.knowledge_governance import KnowledgeGovernance, candidate_pairs
from memory_center.core.foundation.catalog import CatalogError
from test_platform import service  # noqa: F401


@pytest.fixture
def governance(service, monkeypatch):
    client, headers, platform, spaces = service
    # 禁止异步 worker 竞争测试的显式执行；close 仍会终止循环。
    platform.knowledge_tasks.stopping = True
    platform.store.create('chat_model', {'url': 'http://localhost:11434', 'model': 'fixture', 'protocol': 'ollama'})
    calls = []
    def generate(self, prompt, structured=False):
        assert structured
        data = json.loads(prompt.split('资料 JSON：\n')[1]); calls.append(data)
        self.metrics = {'duration_seconds': .01, 'input_tokens': 10, 'output_tokens': 10}
        if isinstance(data, dict):
            return json.dumps({'summary': '部署服务 端口配置'}, ensure_ascii=False)
        category = 'conflict' if any('9000' in d['content'] for d in data) else 'duplicate'
        return json.dumps({'category': category, 'confidence': .8, 'title': '部署配置汇总',
            'reason': '同主题事实存在不同表述或取值，请核实适用范围', 'content': '端口配置待核实：8080 与 9000，保留双方来源。',
            'quotes': {d['id']: d['content'] for d in data}}, ensure_ascii=False)
    monkeypatch.setattr(ChatModel, 'generate', generate)
    return client, headers, platform, spaces, calls


def scan(g, kind='wiki', contents=('服务使用8080端口', '服务监听端口是8080'), pair_limit=500):
    client, headers, p, spaces, _ = g; w = spaces[0]['workspace_id']
    records = [(p.knowledge.wiki('admin', w, f'来源{i}', content) if kind == 'wiki' else
                p.knowledge.memory('admin', w, content, confirmed=True)) for i, content in enumerate(contents)]
    task = p.knowledge_tasks.enqueue(w, kind, 'governance', pair_limit)
    p.knowledge_tasks.stopping = False
    KnowledgeGovernance(p).run(task['id'])
    p.knowledge_tasks.stopping = True
    task = p.store.get('knowledge_task', task['id'])
    return w, records, task


def decision(g, w, draft, **kw):
    client, headers, *_ = g
    return client.post(f'/api/v1/workspaces/{w}/knowledge-governance/{draft}/decision', headers=headers, json={
        'revision': 1, 'decision': 'merge', 'confirm': True, 'title': '审阅标题', 'content': '审阅后的真实事实', **kw})


def test_semantic_scan_and_atomic_merge_retains_provenance(governance):
    g=governance; client, headers, p, spaces, calls=g
    w, records, task=scan(g)
    assert task['status']=='succeeded' and task['coverage']['exhaustive'] and task['coverage']['compared_pairs']==1
    assert len(calls)==3
    assert all(p.store.get('wiki', r['id'])['revision']==1 for r in records)
    base=f'/api/v1/workspaces/{w}/knowledge-governance'
    assert client.get(base,headers={}).status_code==401
    listed=client.get(base,headers=headers).json()
    draft=listed['items'][0]; assert draft['category']=='duplicate' and len(draft['sources'])==2
    assert client.get(base+'/latest',headers=headers).json()['task']['id']==task['id']
    assert decision(g,w,draft['id'],confirm=False).json()['error']['code']=='CONFIRM_REQUIRED'
    out=decision(g,w,draft['id'],retire_source_ids=[r['id'] for r in records])
    assert out.status_code==200,out.text
    saved=p.store.get('wiki',out.json()['result_id'])
    assert saved['content']=='审阅后的真实事实' and len(saved['governance_sources'])==2
    assert all(p.store.get('wiki', r['id'])['status']=='deleted' for r in records)
    assert all(p.store.get('wiki', r['id'])['content']==r['content'] for r in records)
    assert decision(g,w,draft['id'],retire_source_ids=[r['id'] for r in records]).json()['result_id']==saved['id']
    assert decision(g,w,draft['id'],content='改了正文').json()['error']['code']=='REVISION_CONFLICT'
    assert client.get(base,headers=headers).json()['total']==0
    assert client.get(base+'?status=merged',headers=headers).json()['total']==1


def test_conflict_keep_both_and_ignore(governance):
    g=governance; _,_,p,_,_=g
    w, records, task=scan(g,contents=('端口8080','端口9000','端口8080的新表述'))
    drafts=[p.store.get('governance_preview',i) for i in task['preview_ids']]
    conflict=next(d for d in drafts if d['category']=='conflict')
    assert decision(g,w,conflict['id'],decision='keep_both',title='',content='').json()['status']=='kept'
    remaining=next(d for d in drafts if d['id']!=conflict['id'])
    assert decision(g,w,remaining['id'],decision='dismiss',title='',content='').json()['status']=='dismissed'
    assert all(p.store.get('wiki',r['id'])['revision']==1 for r in records)


def test_source_changes_scope_and_expiry_prevent_save(governance):
    g=governance; _,_,p,spaces,_=g
    w,records,task=scan(g); draft=task['preview_ids'][0]
    assert decision(g,spaces[1]['workspace_id'],draft).json()['error']['code']=='FORBIDDEN'
    p.knowledge.wiki('admin',w,'变更','新事实',records[0]['id'],1)
    assert decision(g,w,draft).json()['error']['code']=='REVISION_CONFLICT'
    assert len(p.store.list('wiki',w))==2
    p.store.update('governance_preview',draft,{'expires_at':'2000-01-01T00:00:00+00:00'})
    assert decision(g,w,draft,revision=2).json()['error']['code']=='PREVIEW_EXPIRED'


def test_memory_default_pending_and_explicit_confirm(governance):
    g=governance; _,_,p,_,_=g
    w,records,task=scan(g,kind='memory'); draft=task['preview_ids'][0]
    assert decision(g,w,draft,retire_source_ids=[records[0]['id']]).json()['error']['code']=='MEMORY_CONFIRM_REQUIRED'
    out=decision(g,w,draft)
    assert p.store.get('memory',out.json()['result_id'])['status']=='pending'
    assert all(p.store.get('memory',r['id'])['status']=='confirmed' for r in records)
    w,records,task=scan(g,kind='memory',contents=('新的配置A','配置A另一种说法'))
    matching=next(i for i in task['preview_ids'] if records[0]['id'] in [s['id'] for s in p.store.get('governance_preview',i)['sources']])
    out=decision(g,w,matching,confirm_memory=True,retire_source_ids=[records[0]['id']])
    assert out.status_code==200,out.text
    assert p.store.get('memory',out.json()['result_id'])['status']=='confirmed'


def test_readonly_source_stays_intact_and_freshness_is_checked(governance,tmp_path):
    g=governance; _,_,p,spaces,_=g; w=spaces[0]['workspace_id']
    root=tmp_path/'wiki';root.mkdir();path=root/'source.md';path.write_text('来源原文')
    src=p.wiki_sources.save('目录',str(root),[w]);p.wiki_sources.sync(src['id'])
    p.knowledge.wiki('admin',w,'项目页','项目原文')
    task=p.knowledge_tasks.enqueue(w,'wiki','governance');p.knowledge_tasks.stopping=False
    KnowledgeGovernance(p).run(task['id']);p.knowledge_tasks.stopping=True
    draft=p.store.get('governance_preview',p.store.get('knowledge_task',task['id'])['preview_ids'][0])
    readonly=next(s for s in draft['sources'] if s['readonly'])
    assert decision(g,w,draft['id'],retire_source_ids=[readonly['id']]).json()['error']['code']=='GOVERNANCE_RETIRE_INVALID'
    path.write_text('来源已修改')
    assert decision(g,w,draft['id']).json()['error']['code']=='WIKI_CHANGED'


@pytest.mark.parametrize('failure',['invalid_json','fake_quote','cancel','source_change'])
def test_failed_or_cancelled_analysis_publishes_no_partial_suggestions(governance,monkeypatch,failure):
    g=governance; _,_,p,spaces,_=g;w=spaces[0]['workspace_id']
    pages=[p.knowledge.wiki('admin',w,str(i),f'原文{i}') for i in range(3)]
    task=p.knowledge_tasks.enqueue(w,'wiki','governance')
    original=ChatModel.generate
    count=0
    def generate(self,prompt,structured=False):
        nonlocal count
        result=original(self,prompt,structured);count+=1
        if count==5:
            if failure=='invalid_json': return '不是JSON'
            if failure=='fake_quote':
                d=json.loads(result);d['quotes'][pages[0]['id']]='伪造来源';return json.dumps(d)
            if failure=='cancel':p.knowledge_tasks.cancel(task['id'])
            if failure=='source_change':p.knowledge.wiki('admin',w,'新','修改',pages[0]['id'],1)
        return result
    monkeypatch.setattr(ChatModel,'generate',generate)
    p.knowledge_tasks.stopping=False;KnowledgeGovernance(p).run(task['id']);p.knowledge_tasks.stopping=True
    result=p.store.get('knowledge_task',task['id'])
    assert result['status']=='cancelled' if failure=='cancel' else result['status']=='failed'
    assert not p.store.list('governance_preview',w)
    assert not result['preview_ids']
    assert not p.knowledge_tasks.enqueue(w,'wiki','governance')['id']==task['id']


def test_budget_pagination_and_transaction_rollback(governance,monkeypatch):
    g=governance;client,headers,p,_,_=g
    w,records,task=scan(g,contents=tuple(f'事实{i}' for i in range(7)),pair_limit=12)
    assert task['coverage']['budget_limited'] and not task['coverage']['exhaustive']
    base=f'/api/v1/workspaces/{w}/knowledge-governance'
    page1=client.get(base+'?page_size=10',headers=headers).json();page2=client.get(base+'?page_size=10&page=2',headers=headers).json()
    assert page1['total']==12 and len(page1['items'])==10 and len(page2['items'])==2
    draft=page1['items'][0];before=len(p.store.list('wiki',w));put=p.store._put
    def fail(c,kind,item):
        if kind=='audit':raise RuntimeError('模拟保存中断')
        return put(c,kind,item)
    monkeypatch.setattr(p.store,'_put',fail)
    with pytest.raises(RuntimeError):
        KnowledgeGovernance(p).decide(w,draft['id'],1,'merge',True,'合并','事实', [draft['sources'][0]['id']])
    assert len(p.store.list('wiki',w))==before
    assert p.store.get('governance_preview',draft['id'])['status']=='pending'
    assert p.store.get('wiki',draft['sources'][0]['id'])['status']=='active'


def test_candidate_coverage_for_large_corpus():
    pairs,coverage=candidate_pairs({str(i):'部署端口 8080' for i in range(100)},25)
    assert len(pairs)==25 and coverage['budget_limited'] and not coverage['exhaustive']
    assert len(set(pairs))==len(pairs)


def test_concurrent_confirmation_is_idempotent(governance):
    g=governance; _,_,p,_,_=g
    w,records,task=scan(g);draft=task['preview_ids'][0]
    gate=threading.Barrier(2)
    def apply():
        gate.wait()
        return KnowledgeGovernance(p).decide(w,draft,1,'merge',True,'标题','审阅正文')
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:apply(),range(2)))
    assert results[0]['result_id']==results[1]['result_id']
    assert len(p.store.list('wiki',w))==3


def test_governance_no_embedding_and_preserves_memory_expiry(governance,monkeypatch):
    g=governance;_,_,p,spaces,_=g;w=spaces[0]['workspace_id']
    def forbidden(*a,**kw):pytest.fail('智能治理不应调用向量模型')
    monkeypatch.setattr('memory_center.platform.embeddings.Embedder.embed',forbidden)
    a=p.knowledge.memory('admin',w,'事实A',confirmed=True,expires_at='2098-01-01T00:00:00+00:00')
    p.knowledge.memory('admin',w,'事实A的表述',confirmed=True,expires_at='2099-01-01T00:00:00+00:00')
    task=p.knowledge_tasks.enqueue(w,'memory','governance');p.knowledge_tasks.stopping=False
    KnowledgeGovernance(p).run(task['id']);p.knowledge_tasks.stopping=True
    task=p.store.get('knowledge_task',task['id'])
    saved=decision(g,w,task['preview_ids'][0],confirm_memory=True).json()
    assert p.store.get('memory',saved['result_id'])['expires_at']==a['expires_at']


def test_detail_scope_and_stale_original(governance):
    g=governance;client,headers,p,spaces,_=g
    w,records,task=scan(g);id=task['preview_ids'][0]
    detail=client.get(f'/api/v1/workspaces/{w}/knowledge-governance/{id}',headers=headers).json()
    assert all(s['content'] and not s['stale'] for s in detail['sources'])
    p.knowledge.wiki('admin',w,'改了','内容改变',records[0]['id'],1)
    detail=client.get(f'/api/v1/workspaces/{w}/knowledge-governance/{id}',headers=headers).json()
    assert any(s['stale'] for s in detail['sources'])
    assert client.get(f'/api/v1/workspaces/{spaces[1]["workspace_id"]}/knowledge-governance/{id}',headers=headers).json()['error']['code']=='FORBIDDEN'


def test_stale_suggestion_can_be_dismissed_without_modifying_sources(governance):
    g=governance;_,_,p,_,_=g
    w,records,task=scan(g);draft=task['preview_ids'][0]
    p.knowledge.wiki('admin',w,'新标题','新内容',records[0]['id'],1)
    p.store.update('governance_preview',draft,{'expires_at':'2000-01-01T00:00:00+00:00'})
    response=decision(g,w,draft,revision=2,decision='dismiss',title='',content='')
    assert response.status_code==200,response.text
    assert response.json()['status']=='dismissed'
    assert p.store.get('wiki',records[0]['id'])['content']=='新内容'
