from pathlib import Path


def test_writable_demo_workspace_is_copied_to_tmp_path(tmp_path: Path) -> None:
    """写入型测试必须操作临时副本，不能触碰受保护的示例工作区。"""
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)

    assert workspace.exists()
    assert workspace.is_relative_to(tmp_path)
    assert workspace.parent.parent == tmp_path / "demo"
