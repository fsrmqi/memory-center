"""MCP 服务执行轨迹：只保存身份声明和计量元数据，不保存参数／响应正文。"""
import contextvars
import hashlib
import json
import math
import re
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4

from memory_center.core.foundation.catalog import CatalogError
from memory_center.platform.store import now

current_trace = contextvars.ContextVar('mc_call_trace', default=None)


def bounded(value, length=200):
    return str(value or '').replace('\n', ' ').replace('\r', ' ')[:length]


def error_code(exc):
    seen=set()
    while exc and id(exc) not in seen:
        seen.add(id(exc))
        if isinstance(exc, CatalogError):return bounded(exc.code,100)
        if type(exc).__name__ in {'ValidationError','ArgumentValidationError'}:return 'INVALID_ARGUMENTS'
        exc=exc.__cause__ or exc.__context__
    return 'TOOL_FAILED'


@contextmanager
def span(name):
    trace=current_trace.get()
    if trace is None:
        yield
        return
    started=time.monotonic();row={'name':name,'started_at':now(),'status':'running'}
    trace['spans'].append(row)
    try:
        yield
    except BaseException as exc:
        row['status']='cancelled' if type(exc).__name__=='CancelledError' else 'failed'
        row['error_code']='CALL_CANCELLED' if row['status']=='cancelled' else error_code(exc)
        raise
    else:
        row['status']='succeeded'
    finally:
        row['duration_ms']=round((time.monotonic()-started)*1000,3)
        row['finished_at']=now()


class CallTraces:
    def __init__(self, store):
        self.store,self.db=store,store.db
        self.dropped=0
        with self.db.connection(True) as db:
            db.execute('''CREATE TABLE IF NOT EXISTS mcp_calls (
                id TEXT PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT,
                status TEXT NOT NULL, duration_ms DOUBLE PRECISION NOT NULL,
                tool TEXT NOT NULL, actor TEXT NOT NULL, client TEXT NOT NULL,
                workspace_id TEXT NOT NULL, error_code TEXT NOT NULL, payload TEXT NOT NULL)''')
            for name,columns in [('time','started_at,id'),('status','status,started_at'),('tool','tool,started_at'),('workspace','workspace_id,started_at'),('actor','actor,started_at')]:
                db.execute(f'CREATE INDEX IF NOT EXISTS mcp_calls_{name} ON mcp_calls({columns})')
            rows=db.execute("SELECT payload FROM mcp_calls WHERE status='running'").fetchall()
            for row in rows:
                value=json.loads(row[0]);value.update(status='interrupted',finished_at=now(),error_code='SERVICE_RESTARTED')
                value['duration_ms']=max(0,(datetime.now(timezone.utc)-datetime.fromisoformat(value['started_at'])).total_seconds()*1000)
                self._put(db,value)

    def _put(self,db,value):
        db.execute('''INSERT INTO mcp_calls VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                    started_at=excluded.started_at,finished_at=excluded.finished_at,status=excluded.status,duration_ms=excluded.duration_ms,
                    actor=excluded.actor,client=excluded.client,
                    workspace_id=excluded.workspace_id,error_code=excluded.error_code,payload=excluded.payload''',
            (value['id'],value['started_at'],value.get('finished_at'),value['status'],value.get('duration_ms',0),
             value['tool'],value['actor'],value['client'],value.get('workspace_id',''),value.get('error_code',''),json.dumps(value,ensure_ascii=False)))

    def begin(self,tool,arguments,caller,kind='tool'):
        record={'id':uuid4().hex,'started_at':now(),'finished_at':None,'status':'running','duration_ms':0,
                'kind':kind,'tool':bounded(tool),'workspace_id':'','actor':bounded(caller.get('actor','unverified')),
                'client':bounded(caller.get('client','unknown')), 'caller':caller,'error_code':'','spans':[],
                'argument_keys':sorted(bounded(k,80) for k in arguments)[:30]}
        for key in ('workspace_id','session_id','job_id'):
            value=arguments.get(key,'')
            if isinstance(value,str) and re.fullmatch(r'(?:ws|session|job)_[a-zA-Z0-9_-]{1,100}',value):record[key]=value
        mode=arguments.get('mode')
        if mode in ('hybrid','keyword','vector','symbol','callers','callees','context'):record['mode']=mode
        try:
            with self.db.connection(True) as db:self._put(db,record)
        except Exception:
            self.dropped+=1
        return record

    def checkpoint(self,record):
        try:
            with self.db.connection(True) as db:self._put(db,record)
        except Exception:
            self.dropped+=1

    def finish(self,record,status,elapsed,code='',result=None):
        record.update(status=status,finished_at=now(),duration_ms=round(elapsed*1000,3),error_code=bounded(code,100))
        data = result[1] if isinstance(result,tuple) and len(result)==2 and isinstance(result[1],dict) else result
        if isinstance(data,dict):
            for key in ('id','workspace_id','session_id','job_id'):
                value=data.get(key,'')
                if isinstance(value,str) and re.fullmatch(r'(?:ws|session|job)_[a-zA-Z0-9_-]{1,100}',value):
                    record['job_id' if value.startswith('job_') else key]=value
            if data.get('state') in {'FOUND','NOT_FOUND','STALE','NOT_INDEXED','INSUFFICIENT_EVIDENCE'}:record['outcome']=data['state']
            if isinstance(data.get('items'),list):record['result_count']=len(data['items'])
        try:
            with self.db.connection(True) as db:self._put(db,record)
        except Exception:
            self.dropped+=1

    def filters(self,**filters):
        where,args=[],[]
        for field in ('tool','status','workspace_id','actor','client'):
            if filters.get(field):where.append(field+'=?');args.append(filters[field])
        for field,operator in [('start','>='),('end','<=')]:
            if filters.get(field):where.append('started_at'+operator+'?');args.append(filters[field])
        if filters.get('trace_id'):where.append('id=?');args.append(filters['trace_id'])
        return (' WHERE '+' AND '.join(where) if where else ''),args

    def list_page(self,page=1,page_size=20,**filters):
        where,args=self.filters(**filters)
        with self.db.connection() as db:
            if self.db.url:db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            total=db.execute('SELECT COUNT(*) FROM mcp_calls'+where,args).fetchone()[0]
            pages=max(1,math.ceil(total/page_size));page=min(page,pages)
            rows=db.execute('SELECT payload FROM mcp_calls'+where+' ORDER BY started_at DESC,id DESC LIMIT ? OFFSET ?',(*args,page_size,(page-1)*page_size)).fetchall()
        return {'items':[json.loads(row[0]) for row in rows],'total':total,'page':page,'pages':pages,'page_size':page_size,'dropped_records':self.dropped}

    def detail(self,trace_id):
        with self.db.connection() as db:row=db.execute('SELECT payload FROM mcp_calls WHERE id=?',(trace_id,)).fetchone()
        if not row:raise CatalogError('RECORD_NOT_FOUND','调用记录不存在')
        value=json.loads(row[0])
        job_id=value.get('job_id')
        if job_id:
            try:
                job=self.store.get('job',job_id)
                value['linked_job']={k:job.get(k) for k in ('id','workspace_id','status','phase','started_at','finished_at','error','diagnostics','events','completed','total')}
            except CatalogError:value['linked_job_missing']=True
        return value

    def statistics(self,**filters):
        where,args=self.filters(**filters)
        with self.db.connection() as db:
            if self.db.url:db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            totals=db.execute('SELECT status,COUNT(*),AVG(duration_ms),MAX(duration_ms) FROM mcp_calls'+where+' GROUP BY status',args).fetchall()
            tools=db.execute('SELECT tool,COUNT(*),SUM(CASE WHEN status IN (\'failed\',\'rejected\',\'interrupted\') THEN 1 ELSE 0 END),AVG(duration_ms) FROM mcp_calls'+where+' GROUP BY tool ORDER BY COUNT(*) DESC,tool LIMIT 20',args).fetchall()
            errors=db.execute('SELECT error_code,COUNT(*) FROM mcp_calls'+where+(' AND ' if where else ' WHERE ')+"error_code!='' GROUP BY error_code ORDER BY COUNT(*) DESC,error_code LIMIT 20",args).fetchall()
            clients=db.execute('SELECT client,actor,COUNT(*) FROM mcp_calls'+where+' GROUP BY client,actor ORDER BY COUNT(*) DESC,client,actor LIMIT 20',args).fetchall()
        counts={r[0]:r[1] for r in totals};total=sum(counts.values());failed=sum(counts.get(s,0) for s in ('failed','rejected','interrupted'))
        terminal=[r for r in totals if r[0]!='running'];n=sum(r[1] for r in terminal)
        return {'total':total,'ended_count':n,'counts':counts,'failed':failed,'success_rate':counts.get('succeeded',0)/max(1,n),
                'avg_ms':sum(float(r[2] or 0)*r[1] for r in terminal)/max(1,n),'max_ms':max((float(r[3] or 0) for r in terminal),default=0),
                'tools':[{'tool':r[0],'count':r[1],'failed':r[2],'avg_ms':r[3]} for r in tools],
                'errors':[{'code':r[0],'count':r[1]} for r in errors],
                'clients':[{'client':r[0],'actor':r[1],'count':r[2]} for r in clients],'dropped_records':self.dropped}


def observe_mcp_call(function):
    """统一异步调用切面；不改变 MCP tool 参数 schema 或业务返回值。"""
    from functools import wraps
    import asyncio
    import anyio
    @wraps(function)
    async def observed(self,name,arguments):
        started=time.monotonic();traces=self.platform.call_traces
        caller=self.caller_metadata()
        record=await anyio.to_thread.run_sync(lambda:traces.begin(name,arguments or {},caller))
        token=current_trace.set(record);result=None;status='succeeded';code=''
        try:
            result=await function(self,name,arguments)
            if getattr(result,'isError',False):
                status,code='failed','TOOL_RESULT_ERROR'
            return result
        except BaseException as exc:
            code='CALL_CANCELLED' if isinstance(exc,asyncio.CancelledError) else error_code(exc)
            status='cancelled' if isinstance(exc,asyncio.CancelledError) else 'rejected' if code in {'FORBIDDEN','UNAUTHORIZED'} else 'failed'
            raise
        finally:
            current_trace.reset(token)
            with anyio.CancelScope(shield=True):
                await anyio.to_thread.run_sync(lambda:traces.finish(record,status,time.monotonic()-started,code,result))
    return observed


def observe_transport(function):
    """传输边界切面只记录 HTTP 拒绝；正常工具请求由调用切面记录，避免重复。"""
    from functools import wraps
    import anyio
    @wraps(function)
    async def observed(self,scope,receive,send):
        started=time.monotonic()
        async def observed_send(message):
            if scope['type']=='http' and message['type']=='http.response.start' and message['status']>=400:
                caller={'actor':'unverified','client':'unknown','identity_assurance':'unverified',
                        'client_identity':'unavailable','auth_mode':self.mcp.service_config.auth_mode,
                        'peer':bounded((scope.get('client') or [''])[0],100)}
                traces=self.mcp.platform.call_traces
                record=await anyio.to_thread.run_sync(lambda:traces.begin('mcp.transport',{},caller,'transport'))
                record['http_status']=message['status'];record['started_at']=datetime.fromtimestamp(time.time()-(time.monotonic()-started),timezone.utc).isoformat()
                code={401:'UNAUTHORIZED',403:'REQUEST_REJECTED',429:'RATE_OR_SESSION_LIMIT'}.get(message['status'],'MCP_HTTP_ERROR')
                await anyio.to_thread.run_sync(lambda:traces.finish(record,'rejected',time.monotonic()-started,code))
            await send(message)
        return await function(self,scope,receive,observed_send)
    return observed
