"""5.0 控制面 SQLite 目录；不读取 4.x registry，不承载索引事实。"""
from __future__ import annotations

import json
import os
import sqlite3
import stat
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4, uuid5

from memory_center.core.foundation.catalog import CatalogError

_SCHEMA = """
CREATE TABLE workspaces (
    workspace_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    name_key TEXT NOT NULL,
    root TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('active','paused','removed')),
    revision INTEGER NOT NULL,
    config_version INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX active_name ON workspaces(name_key) WHERE status != 'removed';
CREATE UNIQUE INDEX active_root ON workspaces(root) WHERE status != 'removed';
CREATE TABLE services (
    service_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(workspace_id),
    name TEXT NOT NULL,
    path TEXT NOT NULL,
    kind TEXT NOT NULL,
    exclude_paths TEXT NOT NULL,
    UNIQUE(workspace_id,path)
);
PRAGMA user_version=1;
"""
_MAX_WORKSPACES = 1000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CatalogStore:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.path = data_dir / "catalog.db"

    @contextmanager
    def _connection(self, *, write=False):
        connection = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            if write:
                connection.execute("BEGIN IMMEDIATE")
            else:
                connection.execute("BEGIN")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            descriptor = None
        if descriptor is not None:
            os.close(descriptor)
        metadata = self.path.lstat()
        if not stat.S_ISREG(metadata.st_mode):
            raise CatalogError("CATALOG_FILE_INVALID", "目录数据库必须为普通文件，不能是软链接")
        self.path.chmod(0o600)
        connection = sqlite3.connect(self.path, timeout=5)
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version == 0:
                if connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone():
                    raise CatalogError("CATALOG_SCHEMA_UNSUPPORTED", "目录数据库结构无法识别，未自动覆盖")
                connection.executescript("BEGIN IMMEDIATE;" + _SCHEMA + "COMMIT;")
            elif version != 1:
                raise CatalogError("CATALOG_SCHEMA_UNSUPPORTED", "目录数据库版本不受当前服务支持")
            connection.execute("SELECT workspace_id FROM workspaces LIMIT 1")
            connection.execute("SELECT service_id FROM services LIMIT 1")
        finally:
            connection.close()

    def _conflicts(self, connection, name_key: str | None, root: str, exclude_id: str | None = None):
        rows = connection.execute("SELECT workspace_id,name_key,root FROM workspaces WHERE status!='removed'").fetchall()
        for row in rows:
            if row["workspace_id"] == exclude_id:
                continue
            if name_key is not None and name_key == row["name_key"]:
                raise CatalogError("NAME_CONFLICT", "项目名称已被使用")
            existing = Path(row["root"])
            candidate = Path(root)
            if candidate == existing:
                raise CatalogError("ROOT_DUPLICATE", "该源码目录已登记（包含软链接别名）")
            if candidate.is_relative_to(existing) or existing.is_relative_to(candidate):
                raise CatalogError("ROOT_OVERLAP", "源码目录与已登记项目存在父子重叠")

    def check_root(self, root: str, exclude_id: str | None = None):
        with self._connection() as connection:
            self._conflicts(connection, None, root, exclude_id)

    def _services(self, connection, workspace_id: str, services: list[dict]):
        connection.execute("DELETE FROM services WHERE workspace_id=?", (workspace_id,))
        connection.executemany("INSERT INTO services VALUES(?,?,?,?,?,?)", [
            ("svc_" + uuid5(UUID(workspace_id[3:]), service["path"]).hex, workspace_id,
             service["name"], service["path"], service["type"], json.dumps(service["exclude_paths"]))
            for service in services
        ])

    def _project(self, connection, workspace_id: str) -> dict:
        row = connection.execute("SELECT * FROM workspaces WHERE workspace_id=? AND status!='removed'",
                                 (workspace_id,)).fetchone()
        if not row:
            raise CatalogError("WORKSPACE_NOT_FOUND", "项目不存在或已移除接入")
        result = dict(row)
        result.pop("name_key")
        result["index_status"] = "not_indexed"
        result["services"] = [{"service_id": service["service_id"], "name": service["name"],
                               "path": service["path"], "type": service["kind"],
                               "exclude_paths": json.loads(service["exclude_paths"])}
                              for service in connection.execute(
                                  "SELECT * FROM services WHERE workspace_id=? ORDER BY path", (workspace_id,))]
        return result

    def register(self, name: str, name_key: str, root: str, services: list[dict]) -> dict:
        with self._connection(write=True) as connection:
            self._conflicts(connection, name_key, root)
            if connection.execute("SELECT count(*) FROM workspaces WHERE status!='removed'").fetchone()[0] >= _MAX_WORKSPACES:
                raise CatalogError("CATALOG_LIMIT", "项目登记已达到当前服务上限")
            workspace_id = "ws_" + uuid4().hex
            now = _now()
            connection.execute("INSERT INTO workspaces VALUES(?,?,?,?,?,1,1,?,?)",
                               (workspace_id, name, name_key, root, "active", now, now))
            self._services(connection, workspace_id, services)
            return self._project(connection, workspace_id)

    def list(self, limit: int, after: str = "") -> dict:
        with self._connection() as connection:
            rows = connection.execute("SELECT workspace_id FROM workspaces WHERE status!='removed' AND workspace_id>? ORDER BY workspace_id LIMIT ?",
                                      (after, limit + 1)).fetchall()
            items = [self._project(connection, row[0]) for row in rows[:limit]]
            return {"items": items, "next_cursor": items[-1]["workspace_id"] if len(rows) > limit else None}

    def get(self, workspace_id: str) -> dict:
        with self._connection() as connection:
            return self._project(connection, workspace_id)

    def update(self, workspace_id: str, revision: int, *, name: str | None = None,
               name_key: str | None = None, root: str | None = None, services: list[dict] | None = None,
               status: str | None = None) -> dict:
        with self._connection(write=True) as connection:
            current = self._project(connection, workspace_id)
            if current["revision"] != revision:
                raise CatalogError("REVISION_CONFLICT", "项目已被其他操作更新，请刷新后重试")
            changed_root = root or current["root"]
            changed_key = name_key or connection.execute("SELECT name_key FROM workspaces WHERE workspace_id=?", (workspace_id,)).fetchone()[0]
            self._conflicts(connection, changed_key, changed_root, workspace_id)
            connection.execute("UPDATE workspaces SET name=?,name_key=?,root=?,status=?,revision=revision+1,config_version=config_version+?,updated_at=? WHERE workspace_id=?",
                               (name or current["name"], changed_key, changed_root, status or current["status"],
                                int(name is not None or root is not None), _now(), workspace_id))
            if services is not None:
                self._services(connection, workspace_id, services)
            if status == "removed":
                return {"workspace_id": workspace_id, "status": "removed", "revision": revision + 1,
                        "data_retained": True}
            return self._project(connection, workspace_id)
