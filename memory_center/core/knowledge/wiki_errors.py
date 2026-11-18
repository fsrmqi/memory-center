"""Wiki 操作业务异常 —— 跨层共用的异常契约。

``WikiError`` 会被 core（晋升流程）、application（确认编排）与 platform
（MCP 工具）共同抛出，并由入口层原样透传给客户端。类型定义放在
``core.knowledge``，平台侧 ``platform.assistant.core`` 保留同名再导出，
以维持既有 ``core.WikiError`` 引用。

边界：本模块只定义异常类型，不引入 I/O 或工具层依赖。
"""
from __future__ import annotations


class WikiError(Exception):
    """wiki 操作业务异常（会原样透传给 MCP 客户端）。"""


__all__ = ["WikiError"]
