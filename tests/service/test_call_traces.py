"""统一 MCP 调用切面、失败记录、隔离与计量统计。"""
import asyncio,json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from memory_center.core.foundation.catalog import CatalogError
from memory_center.platform.call_traces import CallTraces,observe_mcp_call,span
from tests.service.test_platform import service,mcp_connect,credential  # noqa: F401


def call(client,headers,name,args):
    return client.post('/mcp',headers=headers,json={'jsonrpc':'2.0','id':17,'method':'tools/call','params':{'name':name,'arguments':args}}).json()


def test_success_failure_identity_redaction_and_stats(service):
    client,headers,platform,spaces=service
    cred=credential(client,headers,[spaces[0]['workspace_id']]);mcp=mcp_connect(client,cred['token'])
    success=call(client,mcp,'mc_workspaces',{})
    assert 'error' not in success
    secret='secret-input-do-not-store'
    failed=call(client,mcp,'mc_lookup',{'workspace_id':spaces[0]['workspace_id'],'query':secret,'limit':100})
    assert failed['result']['isError']
    rows=client.get('/api/v1/call-traces',headers=headers).json()['items']
    assert len(rows)==2 and {r['status'] for r in rows}=={'succeeded','failed'}
    assert all(r['client']=='test' and r['actor']==cred['id'] and r['caller']['identity_assurance']=='credential' for r in rows)
    assert secret not in json.dumps(rows) and cred['token'] not in json.dumps(rows)
    bad=next(r for r in rows if r['status']=='failed');assert bad['error_code']=='QUERY_INVALID'
    detail=client.get('/api/v1/call-traces/'+bad['id'],headers=headers).json()
    assert [s['name'] for s in detail['spans']]==['authorize','tool.execute']
    assert detail['spans'][-1]['status']=='failed' and detail['duration_ms']>=0 and detail['finished_at']
    stats=client.get('/api/v1/call-traces/statistics',headers=headers).json()
    assert stats['total']==2 and stats['failed']==1 and stats['success_rate']==.5
    assert platform.call_traces.list_page(actor=cred['id'])['total']==2
    assert client.get('/api/v1/call-traces').status_code==401
    assert client.get('/api/v1/call-traces',headers={'Authorization':'Bearer '+cred['token']}).status_code==401
    assert client.get('/api/v1/call-traces?start=bad',headers=headers).status_code==422


def test_permissions_and_transport_failures_are_distinct(service):
    client,headers,platform,spaces=service
    cred=credential(client,headers,[spaces[0]['workspace_id']],False);mcp=mcp_connect(client,cred['token'])
    assert call(client,mcp,'mc_memory_write',{'workspace_id':spaces[0]['workspace_id'],'content':'private'})['result']['isError']
    client.post('/mcp',headers={'Authorization':'Bearer invalid-secret'},json={})
    rows=platform.call_traces.list_page()['items'];assert len(rows)==2
    assert all(r['status']=='rejected' for r in rows)
    assert {r['kind'] for r in rows}=={'tool','transport'}
    assert 'private' not in json.dumps(rows) and 'invalid-secret' not in json.dumps(rows)


def test_paging_time_filters_and_restart_interruption(service):
    _,_,platform,spaces=service
    traces=platform.call_traces
    for i in range(23):
        value=traces.begin('fixture',{}, {'actor':'tester','client':'fixture'})
        traces.finish(value,'succeeded',i/1000)
    assert traces.list_page(3,10)['total']==23 and len(traces.list_page(3,10)['items'])==3
    assert traces.list_page(tool='other')['total']==0
    assert traces.statistics(tool='fixture')['avg_ms']==11
    value=traces.begin('unfinished',{}, {'actor':'tester','client':'fixture'})
    reloaded=CallTraces(platform.store)
    assert reloaded.detail(value['id'])['status']=='interrupted'
    assert reloaded.detail(value['id'])['error_code']=='SERVICE_RESTARTED'


def test_job_links_and_parallel_records(service):
    _,_,platform,spaces=service
    job=platform.store.create('job',{'workspace_id':spaces[0]['workspace_id'],'status':'failed','error':'fixture'})
    traces=platform.call_traces
    value=traces.begin('mc_index',{'workspace_id':spaces[0]['workspace_id']},{'actor':'admin','client':'fixture'})
    traces.finish(value,'succeeded',.01,result=([],job))
    assert traces.detail(value['id'])['linked_job']['status']=='failed'
    platform.store.delete('job',job['id'])
    assert traces.detail(value['id'])['linked_job_missing']
    def write(i):
        record=traces.begin('parallel',{}, {'actor':str(i),'client':'fixture'})
        traces.finish(record,'succeeded',.01)
    with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(write,range(20)))
    assert traces.statistics(tool='parallel')['total']==20


def test_aspect_cancellation_and_record_failure_do_not_change_result(service,monkeypatch):
    _,_,platform,_=service
    class Fake:
        def __init__(self):self.platform=platform
        def caller_metadata(self):return {'actor':'admin','client':'fixture'}
        @observe_mcp_call
        async def call_tool(self,name,arguments):
            with span('tool.execute'):
                if name=='cancel':raise asyncio.CancelledError()
                return {'items':[1]}
    fake=Fake()
    with pytest.raises(asyncio.CancelledError):asyncio.run(fake.call_tool('cancel',{}))
    assert platform.call_traces.list_page()['items'][0]['status']=='cancelled'
    monkeypatch.setattr(platform.call_traces,'_put',lambda *args:(_ for _ in ()).throw(OSError('secret-error')))
    assert asyncio.run(fake.call_tool('ok',{}))=={'items':[1]}
    assert platform.call_traces.dropped==2
