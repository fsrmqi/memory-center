"""自动同步的去抖、失败停止、隔离与知识刷新闭环。"""
import time
from pathlib import Path

from tests.service.test_platform import service  # noqa: F401
from tests.service.test_incremental_index import build
from tests.service.test_project_embedding import settings


def enable(platform, wid):
    sync=platform.jobs.source_sync
    return sync.configure(wid,{'enabled':True,'interval_seconds':10,'debounce_seconds':2},sync.settings(wid)['revision'])


def test_settings_auth_revision_scope_and_default(service):
    client,headers,platform,spaces=service
    a,b=[w['workspace_id'] for w in spaces]
    path=f'/api/v1/workspaces/{a}/sync-settings'
    assert client.get(path).status_code==401
    assert client.get(path,headers=headers).json()['enabled'] is False
    configured=enable(platform,a)
    assert platform.jobs.source_sync.settings(b)['enabled'] is False
    assert client.put(path,headers=headers,json={'enabled':False,'revision':0}).json()['error']['code']=='REVISION_CONFLICT'
    same=client.put(path,headers=headers,json={'enabled':True,'interval_seconds':10,'debounce_seconds':2,'revision':configured['revision']}).json()
    assert same['revision']==configured['revision']
    assert client.put(path,headers=headers,json={'enabled':True,'interval_seconds':0,'revision':same['revision']}).status_code==422


def test_debounce_coalesce_failure_restart_and_manual_success(service):
    _,_,platform,spaces=service
    space=spaces[0];wid=space['workspace_id'];sync=platform.jobs.source_sync
    platform.jobs.stopping=True
    settings(platform,wid,'off');build(platform,space);enable(platform,wid)
    assert sync.check(wid,stamp=100)['state']=='current'
    file=Path(space['root'])/'Entry.java'
    file.write_text('class Entry { void modified() {} }')
    assert sync.check(wid,stamp=101)['changed_files']==1
    assert not platform.jobs.pending()
    file.write_text('class Entry { void moreChanges() {} }')
    sync.check(wid,stamp=102);sync.check(wid,stamp=103)
    assert not platform.jobs.pending()
    state=sync.check(wid,stamp=104)
    assert state['schedule_state']=='pending'
    task=platform.jobs.pending()[0];assert task['trigger']=='source_sync'
    sync.check(wid,stamp=110);assert len(platform.jobs.pending())==1
    platform.jobs.cancel(task['id'])
    assert sync.check(wid,stamp=120)['schedule_state']=='blocked'
    from memory_center.platform.project_sync import ProjectSync
    restarted=ProjectSync(platform.jobs)
    assert restarted.check(wid,stamp=130)['schedule_state']=='blocked'
    platform.store.delete('job',task['id'])
    assert restarted.check(wid,stamp=140)['schedule_state']=='blocked'
    # 用户显式手动索引成功后恢复，不因重启或删除历史复活失败任务。
    manual=platform.jobs.enqueue(wid,'admin');platform.store.update('job',manual['id'],{'status':'running'})
    from memory_center.platform.jobs import run_index
    run_index(platform.store.db.data_dir,platform.store.db.url,space,manual['id'])
    assert restarted.state(wid)['state']=='current'
    assert restarted.check(wid,stamp=150)['state']=='current'
    assert restarted.state(wid)['schedule_state']=='watching'


def test_paused_disabled_and_scan_failure(service, monkeypatch):
    _,_,platform,spaces=service
    space=spaces[0];wid=space['workspace_id'];sync=platform.jobs.source_sync
    platform.jobs.stopping=True
    assert sync.check(wid,stamp=1)['state']=='unchecked'
    enable(platform,wid)
    platform.catalog.update(wid,space['revision'],status='paused')
    assert sync.check(wid,stamp=10)['state']=='unchecked'
    platform.catalog.update(wid,platform.catalog.get(wid)['revision'],status='active')
    file=Path(space['root'])/'Entry.java'
    original=Path.read_text
    def fail(self,*args,**kwargs):
        if self==file:raise OSError('fixture')
        return original(self,*args,**kwargs)
    monkeypatch.setattr(Path,'read_text',fail)
    assert sync.check(wid,stamp=20)['state']=='error'
    monkeypatch.setattr(Path,'read_text',original)
    assert sync.check(wid,stamp=30)['state']=='error'
    assert sync.check(wid,manual=True,stamp=31)['state']=='not_indexed'


def test_tick_paginates_all_projects(service,monkeypatch):
    _,_,platform,spaces=service
    sync=platform.jobs.source_sync;platform.jobs.stopping=False
    for space in spaces:enable(platform,space['workspace_id'])
    real=platform.store.list_page
    def small_pages(kind,**kw):
        if kind=='source_sync_settings':kw['page_size']=1
        return real(kind,**kw)
    monkeypatch.setattr(platform.store,'list_page',small_pages)
    seen=[]
    monkeypatch.setattr(sync,'check',lambda wid,**kw:seen.append(wid) or {'state':'current','schedule_state':'watching'})
    sync.tick();assert set(seen)=={w['workspace_id'] for w in spaces}


def test_knowledge_revision_refresh_removal_pending_and_paging(service):
    client,headers,platform,spaces=service
    space=spaces[0];wid=space['workspace_id'];settings(platform,wid,'off');build(platform,space)
    platform.knowledge_tasks.stopping=True
    records=[]
    for i in range(12):
        records.append(platform.store.create('wiki',{'workspace_id':wid,'title':f'Note {i}','content':f'content {i}','status':'active','owner':'admin'}))
    platform.store.create('memory',{'workspace_id':wid,'title':'待确认','content':'candidate','status':'pending','owner':'admin'})
    path=f'/api/v1/workspaces/{wid}/knowledge-index-status'
    assert client.get(path).status_code==401
    data=client.get(path+'?kind=wiki&page=2&page_size=10',headers=headers).json()
    assert data['total']==12 and len(data['items'])==2
    task=platform.knowledge_tasks.enqueue_refresh(wid)
    platform.knowledge_tasks.stopping=False;platform.knowledge_tasks.run_refresh(task['id']);platform.knowledge_tasks.stopping=True
    synced=client.get(path,headers=headers).json()
    assert synced['state']=='current' and synced['awaiting_confirmation']==1
    first=records[0];platform.store.update('wiki',first['id'],{'content':'reviewed merge'},first['revision'])
    updated=client.get(path,headers=headers).json();assert updated['items'][0]['reason']=='updated'
    platform.store.update('wiki',records[1]['id'],{'status':'deleted'})
    changed=client.get(path,headers=headers).json();assert changed['total']==2
    assert {row['reason'] for row in changed['items']}=={'updated','removed'}
    other=client.get(f'/api/v1/workspaces/{spaces[1]["workspace_id"]}/knowledge-index-status',headers=headers).json()
    assert other['total']==0 and other['state']=='not_indexed'


def test_original_wiki_changes_need_sync_before_refresh(service, monkeypatch):
    client,headers,platform,spaces=service
    wid=spaces[0]['workspace_id']
    platform.store.create('wiki',{'workspace_id':wid,'title':'目录 Wiki','content':'original','status':'active','owner':'admin','wiki_source_id':'fixture'})
    monkeypatch.setattr(platform.wiki_sources,'fresh',lambda item:False)
    data=client.get(f'/api/v1/workspaces/{wid}/knowledge-index-status?kind=wiki',headers=headers).json()
    assert data['needs_source_sync']==1 and data['items'][0]['reason']=='source_changed'


def test_project_config_change_is_not_reported_as_current(service):
    _,_,platform,spaces=service
    space=spaces[0];wid=space['workspace_id'];settings(platform,wid,'off');build(platform,space)
    platform.catalog.update(wid,platform.catalog.get(wid)['revision'],name='renamed')
    state=platform.jobs.source_sync.check(wid,manual=True,stamp=1)
    assert state['state']=='config_changed'


def test_queue_capacity_defers_without_blocking_source_checks(service):
    _,_,platform,spaces=service
    space=spaces[0];wid=space['workspace_id'];platform.jobs.stopping=True
    settings(platform,wid,'off');build(platform,space);enable(platform,wid)
    platform.jobs.configure({'max_projects':1,'max_queued':1,'max_file_workers':0,'automatic':True})
    occupied=platform.jobs.enqueue(spaces[1]['workspace_id'],'admin')
    (Path(space['root'])/'Entry.java').write_text('class Changed {}')
    platform.jobs.source_sync.check(wid,stamp=1)
    result=platform.jobs.source_sync.check(wid,stamp=3)
    assert result['state']=='changed' and result['schedule_state']=='waiting_capacity'
    platform.jobs.cancel(occupied['id'])
    result=platform.jobs.source_sync.check(wid,stamp=4)
    assert result['schedule_state']=='pending'
