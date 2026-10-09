"""SQLite/PG 连接适配；PG 控制面串行写锁保持目录冲突合同。"""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from memory_center.core.foundation.catalog import CatalogError
from memory_center.core.storage.catalog import _SCHEMA, CatalogStore


class Row(dict):
    def __getitem__(self, key):
        return list(self.values())[key] if isinstance(key, int) else super().__getitem__(key)


class PGConnection:
    def __init__(self, connection):
        self.raw = connection

    def execute(self, sql, args=()):
        return self.raw.execute(sql.replace('?', '%s'), args or None)

    def executemany(self, sql, args):
        with self.raw.cursor() as cursor:
            cursor.executemany(sql.replace('?', '%s'), args)


def pg_connect(url):
    import psycopg

    def row_factory(cursor):
        names = [column.name for column in cursor.description] if cursor.description else []
        return lambda values: Row(zip(names, values, strict=False))
    return psycopg.connect(url, row_factory=row_factory, connect_timeout=5)


class ManagedCatalog(CatalogStore):
    index_store = None

    def _project(self, connection, workspace_id):
        result = super()._project(connection, workspace_id)
        if self.index_store:
            try:
                index = self.index_store.get('index', workspace_id)
                result['index_status'] = 'ready' if index['config_version'] == result['config_version'] else 'stale'
                result['generation'] = index['generation']
            except CatalogError:
                pass
        return result


class PostgresCatalog(ManagedCatalog):
    def __init__(self, data_dir: Path, url: str):
        super().__init__(data_dir)
        self.url = url

    @contextmanager
    def _connection(self, *, write=False):
        with pg_connect(self.url) as raw:
            if write:
                raw.execute('SELECT pg_advisory_xact_lock(53001)')
            else:
                raw.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            yield PGConnection(raw)

    def initialize(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        with pg_connect(self.url) as raw:
            raw.execute('SELECT pg_advisory_xact_lock(53001)')
            raw.execute('CREATE TABLE IF NOT EXISTS mc_schema(name TEXT PRIMARY KEY, version INTEGER NOT NULL)')
            version = raw.execute("SELECT version FROM mc_schema WHERE name='catalog'").fetchone()
            if version and version['version'] != 1:
                raise CatalogError('CATALOG_SCHEMA_UNSUPPORTED', 'PG 目录结构版本不受支持')
            if not version:
                for statement in _SCHEMA.split(';'):
                    if statement.strip() and not statement.strip().startswith('PRAGMA'):
                        raw.execute(statement)
                raw.execute("INSERT INTO mc_schema VALUES('catalog',1)")
            raw.execute('CREATE EXTENSION IF NOT EXISTS vector')


class Database:
    def __init__(self, data_dir: Path, url: str = ''):
        self.data_dir, self.url = data_dir, url
        self.path = data_dir / 'platform.db'

    @contextmanager
    def connection(self, write=False):
        if self.url:
            with pg_connect(self.url) as raw:
                if write:
                    raw.execute('SELECT pg_advisory_xact_lock(53002)')
                yield PGConnection(raw)
        else:
            raw = sqlite3.connect(self.path, timeout=10, isolation_level=None)
            raw.row_factory = sqlite3.Row
            try:
                raw.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
                yield raw
                raw.commit()
            except BaseException:
                raw.rollback()
                raise
            finally:
                raw.close()

    def initialize(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if not self.url:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.close(fd)
            except FileExistsError:
                if self.path.is_symlink() or not self.path.is_file():
                    raise RuntimeError('服务数据库必须为普通文件') from None
            self.path.chmod(0o600)
            with sqlite3.connect(self.path) as connection:
                connection.execute('PRAGMA journal_mode=WAL')
        with self.connection(True) as connection:
            connection.execute('CREATE TABLE IF NOT EXISTS platform_schema(version INTEGER NOT NULL)')
            row = connection.execute('SELECT version FROM platform_schema').fetchone()
            if row and row[0] != 1:
                raise RuntimeError('知识数据库结构版本不受支持')
            if not row:
                connection.execute('INSERT INTO platform_schema VALUES(1)')
            connection.execute('''CREATE TABLE IF NOT EXISTS records(
                id TEXT PRIMARY KEY, kind TEXT NOT NULL, workspace_id TEXT NOT NULL,
                owner TEXT NOT NULL, payload TEXT NOT NULL, updated_at TEXT NOT NULL)''')
            connection.execute('CREATE INDEX IF NOT EXISTS records_scope ON records(kind,workspace_id,owner)')
            connection.execute('''CREATE TABLE IF NOT EXISTS chunks(
                id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, generation TEXT NOT NULL,
                source_id TEXT NOT NULL, content TEXT NOT NULL, metadata TEXT NOT NULL,
                profile TEXT NOT NULL, embedding TEXT NOT NULL)''')
            connection.execute('CREATE INDEX IF NOT EXISTS chunks_scope ON chunks(workspace_id,generation,source_id)')
            if self.url:
                connection.execute('CREATE EXTENSION IF NOT EXISTS vector')
                connection.execute('ALTER TABLE chunks ADD COLUMN IF NOT EXISTS vector_value vector')
