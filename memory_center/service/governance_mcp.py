"""同一 MCP 服务上的知识治理入口；管理员全局知识空间。"""
import inspect
from functools import wraps

from memory_center.platform.assistant.tools import create_server
from memory_center.platform.governance import ASSISTANT_TOOLS


def register_governance(mcp):
    templates = create_server(".", profile="full")

    def wrapper(tool, fn):
        @wraps(fn)
        def invoke(*args, **kwargs):
            manager = mcp.platform.governance
            bound = inspect.signature(fn).bind(*args, **kwargs)
            return manager.call(tool, dict(bound.arguments), administrator=mcp.actor().id == 'admin')
        return invoke

    for tool in sorted(ASSISTANT_TOOLS):
        original = templates._tool_manager.get_tool(tool).fn
        mcp.add_tool(wrapper(tool, original), name=tool)
