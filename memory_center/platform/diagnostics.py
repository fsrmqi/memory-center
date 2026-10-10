"""可诊断的失败回执；不持久化异常正文、模型响应或连接凭据。"""
import sqlite3
from uuid import uuid4

from memory_center.core.foundation.catalog import CatalogError


def failure_receipt(exc, *, phase='', subject=''):
    code = exc.code if isinstance(exc, CatalogError) else 'INDEX_FAILED'
    message = exc.message if isinstance(exc, CatalogError) else '处理失败，请查看任务诊断'
    actions = ['manual_retry']
    if isinstance(exc, sqlite3.Error):
        if 'Expression tree is too large' in str(exc):
            code, message = 'SQLITE_EXPRESSION_LIMIT', '图查询表达式超出 SQLite 限制，请更新范围清理实现'
        elif 'too many SQL variables' in str(exc):
            code, message = 'SQLITE_VARIABLE_LIMIT', '图查询绑定参数过多，需要分批或使用范围表'
        else:
            code, message = 'SQLITE_STORAGE_ERROR', '图数据库操作失败，请检查存储空间及数据库状态'
        actions = ['inspect_storage', 'manual_retry']
    elif code.startswith(('MODEL_', 'CHAT_', 'EMBEDDING_', 'RERANK_')):
        actions = ['check_model', 'manual_retry']
    elif isinstance(exc, (OSError, MemoryError)):
        code, message = 'INDEX_RESOURCE_ERROR', '文件访问或内存分配失败，请检查目录权限与可用资源'
        actions = ['inspect_resources', 'manual_retry']
    return {'error': code, 'message': message, 'diagnostics': {
        'trace_id': uuid4().hex, 'code': code, 'subject': subject, 'phase': phase,
        'exception_type': type(exc).__name__, 'supported_fixes': actions,
        'automatic_retry': False}}
