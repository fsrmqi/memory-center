"""5.0 项目目录用例：预览与登记共用边界，不读取旧 workspace。"""
import unicodedata
from pathlib import Path

from memory_center.core.foundation.catalog import CatalogError
from memory_center.core.storage.catalog import CatalogStore
from memory_center.core.workspace.discovery import canonical_root, preview_sources


class WorkspaceCatalog:
    def __init__(self, store: CatalogStore):
        self.store = store

    def _name(self, name: str) -> tuple[str, str]:
        name = unicodedata.normalize("NFC", name.strip())
        if not name or len(name) > 120 or any(unicodedata.category(char).startswith("C") for char in name):
            raise CatalogError("NAME_INVALID", "名称需为 1–120 个可显示字符")
        return name, name.casefold()

    def preview(self, root: str, workspace_id: str | None = None) -> dict:
        path = canonical_root(root, self.store.data_dir)
        if workspace_id:
            self.store.get(workspace_id)
        self.store.check_root(str(path), workspace_id)
        return preview_sources(path)

    def _detected(self, root: str) -> dict:
        result = preview_sources(canonical_root(root, self.store.data_dir))
        if not result["scan"]["complete"]:
            raise CatalogError("PREVIEW_INCOMPLETE", "预览达到扫描上限或无法读取，请缩小源码范围后重试")
        return result

    def register(self, name: str, root: str) -> dict:
        name, name_key = self._name(name)
        result = self._detected(root)
        return self.store.register(name, name_key, result["root"], result["services"])

    def update(self, workspace_id: str, revision: int, *, name: str | None = None, root: str | None = None) -> dict:
        if name is None and root is None:
            raise CatalogError("UPDATE_EMPTY", "请提供新名称或源码目录")
        if root is not None and self.store.get(workspace_id)["status"] != "paused":
            raise CatalogError("ROOT_CHANGE_REQUIRES_PAUSE", "修改源码目录前请先暂停项目")
        new_name, name_key = self._name(name) if name is not None else (None, None)
        preview = self._detected(root) if root is not None else None
        return self.store.update(workspace_id, revision, name=new_name, name_key=name_key,
                                 root=preview["root"] if preview else None,
                                 services=preview["services"] if preview else None)

    def set_status(self, workspace_id: str, revision: int, status: str) -> dict:
        current = self.store.get(workspace_id)
        if status == "active":
            root = canonical_root(current["root"], self.store.data_dir)
            if str(root) != current["root"]:
                raise CatalogError("ROOT_CHANGED", "源码目录的实际位置已改变，请暂停后更新路径")
        return self.store.update(workspace_id, revision, status=status)

    def data_path(self, workspace_id: str) -> Path:
        self.store.get(workspace_id)
        return self.store.data_dir / "workspaces" / workspace_id
