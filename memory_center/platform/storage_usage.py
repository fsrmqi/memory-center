"""项目存储的只读统计：文件逻辑大小与数据库载荷，不分摊共享物理页。"""
import json
import os
import re
import stat
from datetime import datetime, timezone

from memory_center.core.foundation.catalog import CatalogError


def workspace_storage(store, workspace_id):
    if not re.fullmatch(r'ws_[a-f0-9]{32}', workspace_id):
        raise CatalogError('WORKSPACE_ID_INVALID', '项目 ID 无效')
    db = store.db
    length = (lambda column: f'octet_length({column})') if db.url else (lambda column: f'length(CAST({column} AS BLOB))')

    def text_size(columns):
        return '+'.join(f'COALESCE({length(column)},0)' for column in columns.split())

    with db.connection() as connection:
        if db.url:
            connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        index = connection.execute("SELECT payload FROM records WHERE kind='index' AND id=?", (workspace_id,)).fetchone()
        generation = json.loads(index[0]).get('generation', '') if index else ''
        native = 'COALESCE(pg_column_size(vector_value),0)' if db.url else '0'
        chunks = connection.execute(f'''SELECT count(*) AS count,
            COALESCE(SUM({text_size('id workspace_id generation source_id content metadata profile embedding')}),0) AS text_bytes,
            COALESCE(SUM({native}),0) AS native_vector_bytes,
            COALESCE(SUM(CASE WHEN profile!='' AND embedding!='[]' THEN 1 ELSE 0 END),0) AS vector_count,
            COALESCE(SUM(CASE WHEN profile!='' AND embedding!='[]' THEN {length('embedding')} ELSE 0 END),0) AS vector_json_bytes
            FROM chunks WHERE workspace_id=?''', (workspace_id,)).fetchone()
        terms = connection.execute(f'''SELECT count(*) AS count,
            COALESCE(SUM({text_size('chunk_id workspace_id generation term')}),0) AS text_bytes
            FROM chunk_terms WHERE workspace_id=?''', (workspace_id,)).fetchone()
        records = connection.execute(f'''SELECT kind,count(*) AS count,
            COALESCE(SUM({text_size('id kind workspace_id owner payload updated_at')}),0) AS text_bytes
            FROM records WHERE workspace_id=? GROUP BY kind ORDER BY kind''', (workspace_id,)).fetchall()
    database = {'chunks': {key: int(chunks[key]) for key in chunks.keys()},
                'terms': {key: int(terms[key]) for key in terms.keys()},
                'records': [{'kind': row['kind'], 'count': int(row['count']), 'text_bytes': int(row['text_bytes'])} for row in records]}
    database['payload_bytes'] = int(chunks['text_bytes'] + chunks['native_vector_bytes'] + terms['text_bytes'] + sum(row['text_bytes'] for row in records))
    files = {key: 0 for key in ('current_generation_bytes', 'other_generations_bytes', 'parse_cache_bytes', 'embedding_cache_bytes', 'other_bytes', 'file_count', 'skipped_symlinks', 'read_errors')}
    base = db.data_dir / 'workspaces'
    root = base / workspace_id
    # 不跟随来源目录或项目存储目录中的符号链接。
    if base.is_symlink() or root.is_symlink():
        files['skipped_symlinks'] += 1
    else:
        pending = [(root, ())]
        while pending:
            directory, relative = pending.pop()
            try:
                with os.scandir(directory) as entries:
                    for entry in entries:
                        parts = (*relative, entry.name)
                        try:
                            info = entry.stat(follow_symlinks=False)
                            if stat.S_ISLNK(info.st_mode):
                                files['skipped_symlinks'] += 1
                            elif stat.S_ISDIR(info.st_mode):
                                pending.append((directory / entry.name, parts))
                            elif stat.S_ISREG(info.st_mode):
                                if parts[0] == 'generations':
                                    key = 'current_generation_bytes' if len(parts) > 1 and parts[1] == generation else 'other_generations_bytes'
                                else:
                                    key = {'parse-cache': 'parse_cache_bytes', 'embedding-cache': 'embedding_cache_bytes'}.get(parts[0], 'other_bytes')
                                files[key] += info.st_size
                                files['file_count'] += 1
                        except OSError:
                            files['read_errors'] += 1
            except FileNotFoundError:
                if relative:
                    files['read_errors'] += 1
            except OSError:
                files['read_errors'] += 1
    files['total_bytes'] = sum(files[key] for key in ('current_generation_bytes', 'other_generations_bytes', 'parse_cache_bytes', 'embedding_cache_bytes', 'other_bytes'))
    shared = {'backend': 'postgres' if db.url else 'sqlite', 'physical_bytes': None}
    if not db.url:
        shared['physical_bytes'] = 0
        shared['read_errors'] = 0
        for name in ('platform.db', 'catalog.db'):
            for suffix in ('', '-wal', '-shm'):
                try:
                    info = (db.data_dir / (name + suffix)).lstat()
                    if stat.S_ISREG(info.st_mode):
                        shared['physical_bytes'] += info.st_size
                except FileNotFoundError:
                    pass
                except OSError:
                    shared['read_errors'] += 1
    return {'workspace_id': workspace_id, 'observed_at': datetime.now(timezone.utc).isoformat(),
            'generation': generation, 'partial': bool(files['read_errors'] or files['skipped_symlinks']),
            'files': files, 'database': database, 'shared_database': shared,
            'accounted_bytes': files['total_bytes'] + database['payload_bytes']}
