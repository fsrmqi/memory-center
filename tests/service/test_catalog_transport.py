"""真实 TCP 目录闭环；可切换到仓库外安装的服务可执行文件。"""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

from memory_center import __version__


def test_live_catalog_restart_and_source_readonly(tmp_path):
    data = tmp_path / "service"
    roots = [tmp_path / name for name in ("project-a", "project-b")]
    for root in roots:
        root.mkdir()
        (root / "pyproject.toml").write_text("[project]\nname='sample'\n")
        (root / ".memory-center").mkdir()
        (root / ".memory-center" / "workspace.yaml").write_text("invalid legacy YAML")
    before = {str(root): {str(path.relative_to(root)): path.read_bytes()
                          for path in root.rglob("*") if path.is_file()} for root in roots}
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    executable = os.environ.get("MEMORY_CENTER_TEST_SERVICE_BIN")
    command = [executable] if executable else [sys.executable, "-m", "memory_center.service.main"]
    command += ["--port", str(port), "--data-dir", str(data)]
    command += ["--auth-mode", "token"]
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    if not executable:
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])
    process = None
    with (tmp_path / "server.log").open("w+") as log:
        def start():
            nonlocal process
            process = subprocess.Popen(command, cwd=tmp_path, env=env, stdout=log, stderr=log)
            for _ in range(100):
                try:
                    if httpx.get(f"http://127.0.0.1:{port}/health/ready", timeout=.2).status_code == 200:
                        return
                except httpx.HTTPError:
                    pass
                if process.poll() is not None:
                    log.seek(0)
                    raise AssertionError(log.read())
                time.sleep(.05)
            raise AssertionError("服务未就绪")

        try:
            start()
            token = (data / "admin-token").read_text()
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=5) as client:
                assert client.get("/api/v1/service/status").json()["version"] == __version__
                assert client.get("/api/v1/workspaces").status_code == 401
                client.headers["Authorization"] = "Bearer " + token
                items = []
                for index, root in enumerate(roots):
                    preview = client.post("/api/v1/workspaces/preview", json={"root": str(root)})
                    assert preview.status_code == 200
                    response = client.post("/api/v1/workspaces", json={"name": f"project-{index}", "root": str(root)})
                    assert response.status_code == 201
                    items.append(response.json())
                url = "/api/v1/workspaces/" + items[0]["workspace_id"]
                renamed = client.patch(url, json={"revision": 1, "name": "renamed"}).json()
                assert renamed["workspace_id"] == items[0]["workspace_id"]
                assert client.post(url + "/pause", json={"revision": 2}).json()["status"] == "paused"
                assert client.post(url + "/resume", json={"revision": 3}).json()["status"] == "active"
                process.terminate()
                process.wait(timeout=15)
                start()
                assert (data / "admin-token").read_text() == token
                assert client.get(url).json()["name"] == "renamed"
                assert len(client.get("/api/v1/workspaces").json()["items"]) == 2
                assert client.delete(url, params={"revision": 4}).json()["data_retained"]
                assert client.get(url).status_code == 404
                assert len(client.get("/api/v1/workspaces").json()["items"]) == 1
        finally:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                    raise AssertionError("服务关闭超时") from None
    for root in roots:
        assert before[str(root)] == {str(path.relative_to(root)): path.read_bytes()
                                    for path in root.rglob("*") if path.is_file()}
    with socket.socket() as released:
        released.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        released.bind(("127.0.0.1", port))
