"""凭据授权、主体与空间上下文；哈希凭据，不接受 cwd 作为授权。"""
import hashlib
import hmac
import secrets
from dataclasses import dataclass

from memory_center.core.foundation.catalog import CatalogError
from memory_center.platform.store import identity, now

READ_TOOLS = {'mc_service_status', 'mc_workspaces', 'mc_lookup', 'mc_analyze', 'mc_ref', 'mc_resume', 'mc_job_status'}
WRITE_TOOLS = READ_TOOLS | {'mc_start', 'mc_close', 'mc_memory_write', 'mc_wiki_write', 'mc_index', 'mc_job_cancel'}


@dataclass(frozen=True)
class Principal:
    id: str
    workspaces: tuple[str, ...]
    tools: frozenset[str]
    writable: bool = False


ANONYMOUS = Principal('anonymous', (), frozenset({'mc_service_status'}))


class Access:
    def __init__(self, store, catalog):
        self.store, self.catalog = store, catalog

    def issue(self, name, workspace_ids, writable=False, tools=None, rate=60):
        if not workspace_ids or len(workspace_ids) > 100:
            raise CatalogError('SCOPE_INVALID', '请选择 1–100 个项目')
        for workspace_id in workspace_ids:
            self.catalog.get(workspace_id)
        allowed = WRITE_TOOLS if writable else READ_TOOLS
        selected = set(tools) if tools is not None else allowed
        if not selected <= allowed or not 1 <= rate <= 600:
            raise CatalogError('POLICY_INVALID', '工具或速率超出权限范围')
        token = secrets.token_urlsafe(32)
        item = self.store.create('credential', {'name': name, 'workspace_ids': sorted(set(workspace_ids)),
                                                'tools': sorted(selected), 'writable': writable,
                                                'rate': rate, 'revoked': False,
                                                'digest': hashlib.sha256(token.encode()).hexdigest()})
        self.store.audit('admin', 'credential.issue', record_id=item['id'])
        return dict(self.public(item), token=token)

    def public(self, item):
        return {key: value for key, value in item.items() if key != 'digest'}

    def authenticate(self, token):
        if not token:
            return ANONYMOUS
        digest = hashlib.sha256(token.encode()).hexdigest()
        for item in self.store.list('credential', limit=1000):
            if not item['revoked'] and hmac.compare_digest(digest, item['digest']):
                return Principal(item['id'], tuple(item['workspace_ids']), frozenset(item['tools']), item['writable'])
        raise CatalogError('UNAUTHORIZED', '凭据无效或已撤销')

    def scope(self, actor, workspace_id, write=False):
        if workspace_id not in actor.workspaces or (write and not actor.writable):
            raise CatalogError('FORBIDDEN', '无权访问此项目或执行写入')
        workspace = self.catalog.get(workspace_id)
        if workspace['status'] != 'active':
            raise CatalogError('WORKSPACE_PAUSED', '项目已暂停')
        return workspace

    def owned(self, actor, kind, record_id, workspace_id=None):
        record = self.store.get(kind, record_id)
        self.scope(actor, record['workspace_id'])
        if record.get('owner') != actor.id or (workspace_id and record['workspace_id'] != workspace_id):
            raise CatalogError('FORBIDDEN', '会话或引用不属于当前主体与项目')
        return record

    def start(self, actor, workspace_id, intent):
        self.scope(actor, workspace_id, True)
        return self.store.create('session', {'workspace_id': workspace_id, 'owner': actor.id,
                                             'intent': intent[:2000], 'status': 'active', 'events': []})

    def close(self, actor, session_id, outcome):
        session = self.owned(actor, 'session', session_id)
        self.scope(actor, session['workspace_id'], True)
        if session['status'] != 'active':
            raise CatalogError('SESSION_CLOSED', '会话已结束')
        return self.store.update('session', session_id, {'status': 'closed', 'outcome': outcome[:4000], 'closed_at': now()},
                                 session['revision'])

    def reference(self, actor, workspace_id, result):
        return self.store.create('ref', {'id': identity('ref'), 'workspace_id': workspace_id,
                                        'owner': actor.id, 'evidence': result})['id']
