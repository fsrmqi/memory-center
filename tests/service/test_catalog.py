import hashlib
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from memory_center.application.workspaces import WorkspaceCatalog
from memory_center.core.foundation.catalog import CatalogError
from memory_center.core.storage.catalog import CatalogStore
from memory_center.service.app import create_service_app
from memory_center.service.config import ServiceConfig


def source(root: Path, marker="pyproject.toml", content="[project]\nname='sample'\n") -> Path:
    root.mkdir(parents=True)
    (root / marker).write_text(content)
    old = root / ".memory-center"
    old.mkdir()
    (old / "workspace.yaml").write_text("[invalid legacy YAML")
    (root / "AGENTS.md").write_text("original instructions")
    return root


def snapshot(root):
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob("*") if path.is_file()}


@pytest.fixture
def admin(tmp_path):
    data = tmp_path / "data"
    with TestClient(create_service_app(ServiceConfig(data)), base_url="http://localhost") as client:
        client.headers["Authorization"] = "Bearer " + (data / "admin-token").read_text()
        yield client, data


def register(client, name, root):
    result = client.post("/api/v1/workspaces", json={"name": name, "root": str(root)})
    assert result.status_code == 201, result.text
    return result.json()


def test_two_projects_preview_and_restart(tmp_path, admin):
    client, data = admin
    first = source(tmp_path / "python")
    frontend = first / "frontend"
    frontend.mkdir()
    (frontend / "package.json").write_text('{}')
    second = source(tmp_path / "spring", "pom.xml", "<dependency>spring-boot-starter</dependency>")
    before = {str(root): snapshot(root) for root in (first, second)}
    preview = client.post("/api/v1/workspaces/preview", json={"root": str(first)})
    assert preview.status_code == 200
    assert preview.json()["scan"]["complete"]
    assert [item["path"] for item in preview.json()["services"]] == [".", "frontend"]
    assert preview.json()["services"][0]["exclude_paths"] == ["frontend"]
    assert client.get("/api/v1/workspaces").json()["items"] == []
    a = register(client, "Python", first)
    b = register(client, "Spring", second)
    assert a["workspace_id"] != b["workspace_id"]
    assert b["services"][0]["type"] == "spring-boot-service"
    assert a["index_status"] == b["index_status"] == "not_indexed"
    token = (data / "admin-token").read_text()
    for root in (first, second):
        assert snapshot(root) == before[str(root)]
    # A distinct app/lifespan reads only the persisted 5.0 directory.
    with TestClient(create_service_app(ServiceConfig(data)), base_url="http://localhost") as restarted:
        restarted.headers["Authorization"] = "Bearer " + token
        assert restarted.get(f"/api/v1/workspaces/{a['workspace_id']}").json() == a
        assert restarted.get(f"/api/v1/workspaces/{b['workspace_id']}").json() == b
        assert (data / "admin-token").read_text() == token
    assert not (data / "workspaces").exists()  # No index/worker initialization in S1.


def test_identity_rename_pause_move_resume_remove(tmp_path, admin):
    client, data = admin
    root = source(tmp_path / "old")
    item = register(client, "项目", root)
    url = "/api/v1/workspaces/" + item["workspace_id"]
    service_id = item["services"][0]["service_id"]
    renamed = client.patch(url, json={"revision": 1, "name": "新名称"}).json()
    assert renamed["workspace_id"] == item["workspace_id"]
    assert renamed["revision"] == 2
    assert renamed["config_version"] == 2
    assert renamed["services"][0]["service_id"] == service_id
    assert client.patch(url, json={"revision": 1, "name": "过期操作"}).json()["error"]["code"] == "REVISION_CONFLICT"
    assert client.patch(url, json={"revision": 2, "root": str(root)}).status_code == 409
    paused = client.post(url + "/pause", json={"revision": 2}).json()
    assert paused["status"] == "paused"
    assert paused["config_version"] == 2
    moved_root = tmp_path / "new"
    root.rename(moved_root)
    assert client.post(url + "/resume", json={"revision": 3}).json()["error"]["code"] == "ROOT_NOT_FOUND"
    moved = client.patch(url, json={"revision": 3, "root": str(moved_root)}).json()
    assert moved["root"] == str(moved_root)
    assert moved["workspace_id"] == item["workspace_id"]
    assert moved["services"][0]["service_id"] == service_id
    resumed = client.post(url + "/resume", json={"revision": 4}).json()
    assert resumed["status"] == "active"
    assert resumed["revision"] == 5
    # Data retention, without populating private workspace outputs.
    retained = data / "workspaces" / item["workspace_id"]
    retained.mkdir(parents=True)
    (retained / "sentinel").write_text("retained")
    assert client.delete(url, params={"revision": 5}).json()["data_retained"]
    assert client.get(url).status_code == 404
    assert client.get("/api/v1/workspaces").json()["items"] == []
    assert (retained / "sentinel").read_text() == "retained"
    replacement = register(client, "新名称", moved_root)
    assert replacement["workspace_id"] != item["workspace_id"]
    assert (moved_root / "AGENTS.md").read_text() == "original instructions"


def test_path_name_conflicts_and_pagination(tmp_path, admin):
    client, _ = admin
    root = source(tmp_path / "parent")
    child = source(root / "child")
    a = register(client, "Ａ", root)
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)
    for path, expected in ((root, "ROOT_DUPLICATE"), (alias, "ROOT_DUPLICATE"), (child, "ROOT_OVERLAP")):
        response = client.post("/api/v1/workspaces", json={"name": "different", "root": str(path)})
        assert response.status_code == 409
        assert response.json()["error"]["code"] == expected
    second = source(tmp_path / "second")
    b = register(client, "Beta", second)
    assert client.post("/api/v1/workspaces", json={"name": "beta", "root": str(tmp_path / "third")}).status_code != 201
    # Name collision is checked even when source roots differ.
    third = source(tmp_path / "third")
    response = client.post("/api/v1/workspaces", json={"name": "beta", "root": str(third)})
    assert response.json()["error"]["code"] == "NAME_CONFLICT"
    page = client.get("/api/v1/workspaces", params={"limit": 1}).json()
    following = client.get("/api/v1/workspaces", params={"limit": 1, "after": page["next_cursor"]}).json()
    assert {page["items"][0]["workspace_id"], following["items"][0]["workspace_id"]} == {a["workspace_id"], b["workspace_id"]}
    assert following["next_cursor"] is None
    assert client.get("/api/v1/workspaces", params={"limit": 101}).status_code == 422


@pytest.mark.parametrize("kind,code", [("missing", "ROOT_NOT_FOUND"), ("relative", "ROOT_NOT_ABSOLUTE"),
                                      ("file", "ROOT_NOT_DIRECTORY"), ("data", "ROOT_DATA_OVERLAP"),
                                      ("parent", "ROOT_DATA_OVERLAP")])
def test_invalid_source_roots(tmp_path, admin, kind, code):
    client, data = admin
    file = tmp_path / "file"
    file.write_text("source")
    roots = {"missing": tmp_path / "absent", "relative": "relative", "file": file, "data": data, "parent": tmp_path}
    response = client.post("/api/v1/workspaces/preview", json={"root": str(roots[kind])})
    assert response.json()["error"]["code"] == code


def test_management_boundary_no_token_bad_origin_and_invalid_payload(tmp_path, admin):
    client, data = admin
    root = source(tmp_path / "project")
    token = client.headers.pop("authorization")
    calls = [("GET", "/api/v1/workspaces", None),
             ("POST", "/api/v1/workspaces/preview", {"root": str(root)}),
             ("POST", "/api/v1/workspaces", {"name": "name", "root": str(root)})]
    for method, url, payload in calls:
        assert client.request(method, url, json=payload).status_code == 401
    client.headers["Authorization"] = token
    assert client.get("/api/v1/workspaces", headers={"Host": "untrusted.invalid"}).status_code == 421
    assert client.post("/api/v1/workspaces", headers={"Origin": "http://untrusted.invalid"},
                       json={"name": "name", "root": str(root)}).status_code == 403
    assert client.post("/api/v1/workspaces", headers={"Origin": "http://localhost:9000"},
                       json={"name": "name", "root": str(root)}).status_code == 403
    assert client.post("/api/v1/workspaces", content="name=test", headers={"Content-Type": "text/plain"}).status_code == 400
    assert client.post("/api/v1/workspaces", json={"name": "name", "root": str(root), "legacy": True}).status_code == 422
    assert client.get("/api/v1/workspaces/../admin-token").status_code != 200
    status = client.get("/api/v1/service/status").text
    assert str(root) not in status and (data / "admin-token").read_text() not in status
    assert (data / "admin-token").stat().st_mode & 0o777 == 0o600


def test_atomic_registration_rollback_and_concurrency(tmp_path, monkeypatch):
    store = CatalogStore(tmp_path / "data")
    store.initialize()
    app = WorkspaceCatalog(store)
    root = source(tmp_path / "project")
    original = store._services

    def fail(*args):
        raise RuntimeError("injected failure")

    monkeypatch.setattr(store, "_services", fail)
    with pytest.raises(RuntimeError, match="injected failure"):
        app.register("incomplete", str(root))
    assert store.list(20)["items"] == []
    monkeypatch.setattr(store, "_services", original)

    def attempt(index):
        try:
            return app.register("name" + str(index), str(root))["workspace_id"]
        except CatalogError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(attempt, range(6)))
    assert sum(result.startswith("ws_") for result in results) == 1
    assert results.count("ROOT_DUPLICATE") == 5
    assert len(store.list(20)["items"]) == 1


def test_preview_limits_symlinks_and_no_registration(tmp_path, admin, monkeypatch):
    import memory_center.core.workspace.discovery as discovery

    client, _ = admin
    root = source(tmp_path / "project")
    outside = source(tmp_path / "outside")
    (root / "external").symlink_to(outside, target_is_directory=True)
    preview = client.post("/api/v1/workspaces/preview", json={"root": str(root)}).json()
    assert "symlinks_skipped" in preview["scan"]["warnings"]
    assert len(preview["services"]) == 1
    monkeypatch.setattr(discovery, "_MAX_ENTRIES", 1)
    limited = client.post("/api/v1/workspaces/preview", json={"root": str(root)}).json()
    assert not limited["scan"]["complete"]
    response = client.post("/api/v1/workspaces", json={"name": "limited", "root": str(root)})
    assert response.json()["error"]["code"] == "PREVIEW_INCOMPLETE"
    assert client.get("/api/v1/workspaces").json()["items"] == []


def test_unsupported_catalog_and_invalid_token_fail_startup(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    with sqlite3.connect(data / "catalog.db") as connection:
        connection.execute("PRAGMA user_version=99")
    with pytest.raises(CatalogError, match="版本不受"):
        with TestClient(create_service_app(ServiceConfig(data))):
            pass
    with sqlite3.connect(data / "catalog.db") as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 99
    other = tmp_path / "other"
    other.mkdir()
    token = other / "admin-token"
    token.write_text("invalid")
    token.chmod(0o600)
    with pytest.raises(RuntimeError, match="格式无效"):
        with TestClient(create_service_app(ServiceConfig(other))):
            pass
    assert token.read_text() == "invalid"


def test_unauthorized_mutations_cannot_change_registered_project(tmp_path, admin):
    client, _ = admin
    root = source(tmp_path / "project")
    item = register(client, "protected", root)
    url = "/api/v1/workspaces/" + item["workspace_id"]
    token = client.headers.pop("authorization")
    calls = [("GET", url, None), ("PATCH", url, {"revision": 1, "name": "injected"}),
             ("POST", url + "/pause", {"revision": 1}),
             ("POST", url + "/resume", {"revision": 1}), ("DELETE", url + "?revision=1", None)]
    for method, target, body in calls:
        assert client.request(method, target, json=body).status_code == 401
    client.headers["Authorization"] = token
    assert client.get(url).json() == item


def test_concurrent_revision_updates_and_parent_child_registration(tmp_path):
    store = CatalogStore(tmp_path / "data")
    store.initialize()
    app = WorkspaceCatalog(store)
    parent = source(tmp_path / "parent")
    child = source(parent / "child")

    def register_root(path):
        try:
            return app.register(path.name, str(path))["workspace_id"]
        except CatalogError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(register_root, (parent, child)))
    assert results.count("ROOT_OVERLAP") == 1
    workspace_id = next(result for result in results if result.startswith("ws_"))

    def rename(name):
        try:
            return app.update(workspace_id, 1, name=name)["name"]
        except CatalogError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        updated = list(pool.map(rename, ("one", "two")))
    assert updated.count("REVISION_CONFLICT") == 1
    assert store.get(workspace_id)["revision"] == 2


def test_invalid_source_text_and_unprotected_token(tmp_path, admin):
    client, _ = admin
    response = client.post("/api/v1/workspaces/preview", json={"root": "/invalid\u0000path"})
    assert response.json()["error"]["code"] == "ROOT_INVALID"
    data = tmp_path / "bad-token"
    data.mkdir()
    token = data / "admin-token"
    token.write_text("a" * 64)
    token.chmod(0o644)
    with pytest.raises(RuntimeError, match="0600"):
        with TestClient(create_service_app(ServiceConfig(data))):
            pass


def test_catalog_file_symlink_is_rejected(tmp_path):
    outside = tmp_path / "outside"
    outside.write_text("untouched")
    data = tmp_path / "data"
    data.mkdir()
    (data / "catalog.db").symlink_to(outside)
    with pytest.raises(CatalogError, match="软链接"):
        CatalogStore(data).initialize()
    assert outside.read_text() == "untouched"


def test_catalog_documentation_contracts_are_discoverable():
    root = Path(__file__).resolve().parents[2]
    for name in ("README.md", "docs/ARCHITECTURE.md", "docs/USER_GUIDE.md", "docs/REFERENCE.md", "docs/MCP_GUIDE.md"):
        assert "V5_CATALOG_GUIDE.md" in (root / name).read_text()
    guide = (root / "docs/V5_CATALOG_GUIDE.md").read_text()
    for concept in ("workspace_id", "service_id", "revision", "config_version", "admin-token", "PREVIEW_INCOMPLETE",
                    "/api/v1/workspaces/preview", "ROOT_OVERLAP", "2048", "0600"):
        assert concept in guide


def test_special_admin_token_file_fails_without_blocking(tmp_path):
    import os

    if not hasattr(os, "mkfifo"):
        pytest.skip("平台不支持 FIFO")
    data = tmp_path / "data"
    data.mkdir()
    os.mkfifo(data / "admin-token")
    with pytest.raises(RuntimeError, match="普通文件"):
        with TestClient(create_service_app(ServiceConfig(data))):
            pass
