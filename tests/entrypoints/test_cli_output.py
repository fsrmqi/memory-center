"""CLI 输出必须机器可读 / CLI output must stay machine-readable.

回归：``rich.print`` 会按终端宽度折行，长字符串（如 ``next_action`` 里的命令模板）
被从中断开，stdout 既不是合法 JSON 也不是合法 Python 字面量，脚本、测试与宿主
集成都无法解析。所有 CLI 命令改走 ``memory_center.cli.output.print_data``。

Regression: ``rich.print`` word-wraps to the terminal width and splits long strings
(such as the command template in ``next_action``) across lines, so stdout is neither
valid JSON nor a valid Python literal. Every CLI command now emits through
``memory_center.cli.output.print_data``.
"""
from __future__ import annotations

import ast
from pathlib import Path

from typer.testing import CliRunner

from memory_center.cli.main import app
from memory_center.cli.output import print_data


def test_cli_dict_output_is_not_word_wrapped(demo_workspace: Path) -> None:
    result = CliRunner().invoke(app, ["backend-consistency", "--workspace", str(demo_workspace)])

    assert result.exit_code == 0, result.output
    parsed = ast.literal_eval(result.output.strip())
    assert isinstance(parsed, dict)
    # 该命令模板长于默认终端宽度：修复前会被折成两行
    assert "\n" not in parsed["jsonl_projection"]["next_action"]


def test_print_data_round_trips_long_strings(capsys) -> None:
    payload = {
        "next_action": "artifact jsonl-export-sync --workspace <workspace.yaml> --collection <name> --apply",
        "url": "https://example.com/" + "y" * 80,
    }

    print_data(payload)

    assert ast.literal_eval(capsys.readouterr().out.strip()) == payload
