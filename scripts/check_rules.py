#!/usr/bin/env python
"""按规则文件执行 gate 判据；违规即非零退出。

用法 / Usage:
    python scripts/check_rules.py --rules .github/gate-rules.yaml --source-root .
    python scripts/check_rules.py --rules <dir-or-file> --format json --rule ARCH-001

退出码 / Exit codes:
    0  通过（无违规、无配置错误）
    1  有违规
    2  规则文件或参数错误

逻辑全部在 memory_center.core.governance，此脚本只做参数解析与输出。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="check_rules",
        description="执行 Memory Center 规则的可机检判据（gate）",
    )
    parser.add_argument(
        "--rules",
        action="append",
        required=True,
        help="规则 YAML 文件或目录（可重复）；目录会展开其中的 *.yaml",
    )
    parser.add_argument("--source-root", default=".", help="被检查的源码根目录，默认当前目录")
    parser.add_argument("--rule", action="append", default=[], help="只运行指定规则 id（可重复）")
    parser.add_argument("--max-findings", type=int, default=50, help="每条规则最多输出的违规数")
    parser.add_argument("--format", choices=("text", "json"), default="text", help="输出格式")
    args = parser.parse_args(argv)

    sys.path.insert(0, str(REPO_ROOT))
    from memory_center.core.governance.rule_gate import format_text, run_gate

    try:
        summary = run_gate(
            args.rules,
            args.source_root,
            max_findings=args.max_findings,
            rule_ids=args.rule,
        )
    except (ValueError, OSError) as exc:
        if args.format == "json":
            print(json.dumps({"ok": False, "config_error": str(exc)}, ensure_ascii=False, indent=2))
        else:
            print(f"规则门禁无法执行：{exc}", file=sys.stderr)
        return 2

    if args.format == "json":
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(format_text(summary))

    if summary.get("errors"):
        return 2
    return 0 if summary.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
