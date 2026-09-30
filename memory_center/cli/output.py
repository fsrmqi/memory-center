"""CLI 输出助手 / CLI output helpers.

Rich 的 ``print`` 会按终端宽度折行：长字符串（URL、命令模板、JSON 值）会被从中
断开，于是 stdout 既不是合法 JSON 也不是合法 Python 字面量，脚本与测试都无法
解析。CLI 命令的结果是机器可读数据，因此统一用 ``soft_wrap=True`` 输出——保留
rich 的着色能力，但禁止插入换行、禁止截断。

Rich's ``print`` word-wraps to the terminal width, splitting long strings (URLs,
command templates, JSON values) across lines so that stdout is neither valid JSON
nor a valid Python literal and cannot be parsed by scripts or tests. CLI command
results are machine-readable, so they are emitted with ``soft_wrap=True``: rich's
colouring is preserved while wrapping and cropping are disabled.
"""
from __future__ import annotations

from typing import Any

from rich.console import Console

# 与 rich.print 同构的模块级 Console：file=None 时在输出时动态解析 sys.stdout，
# 因此 CliRunner / capsys 这类重定向仍能捕获输出。
_console = Console()


def print_data(*objects: Any, **kwargs: Any) -> None:
    """Print machine-readable CLI output without word wrapping or cropping.

    注意不能用 ``rich.print``：它的签名固定为 ``(sep, end, file, flush)``，不接受
    ``soft_wrap``，会抛 ``TypeError``。
    """
    kwargs.setdefault("soft_wrap", True)
    _console.print(*objects, **kwargs)
