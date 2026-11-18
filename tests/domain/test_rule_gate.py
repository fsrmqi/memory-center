"""规则门禁的编排与 CLI 契约测试。

覆盖：
- ``run_gate`` 的 ok / 违规 / 配置错误三态；
- 目录形式的规则路径会展开为其中的 YAML；
- ``scripts/check_rules.py`` 的退出码约定（0 通过、1 违规、2 配置错误）与 json 输出。
"""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

from memory_center.core.governance.rule_gate import expand_rule_paths, format_text, run_gate

REPO_ROOT = Path(__file__).resolve().parents[2]


def _write(path: Path, body: str) -> Path:
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


def _rules(path: Path) -> Path:
    return _write(
        path,
        """
        rules:
          - id: GATE-001
            title: 核心不得依赖上层
            scope: [architecture]
            severity: must
            rule: pkg/core 不得导入 pkg/app。
            enforcement: gate
            check:
              kind: forbidden_import
              config:
                path_prefix: pkg/core
                forbidden_prefixes: [pkg.app]
            repair_steps:
              - Step 1: 定位导入点。
              - Step 2: 下沉能力。

          - id: NOTE-001
            title: 仅提示
            scope: [architecture]
            severity: must
            rule: 这条只是提示。
            enforcement: advisory
        """,
    )


def _tree(root: Path, *, violating: bool) -> Path:
    (root / "pkg" / "core").mkdir(parents=True)
    (root / "pkg" / "app").mkdir(parents=True)
    for name in ("pkg", "pkg/core", "pkg/app"):
        (root / name / "__init__.py").write_text("", encoding="utf-8")
    body = "from pkg.app import runner\n" if violating else "VALUE = 1\n"
    (root / "pkg" / "core" / "mod.py").write_text(body, encoding="utf-8")
    return root


def test_run_gate_passes_when_no_violation(tmp_path: Path) -> None:
    rules = _rules(tmp_path / "rules.yaml")
    source = _tree(tmp_path / "repo", violating=False)
    summary = run_gate([rules], source)
    assert summary["ok"] is True
    assert summary["violation_count"] == 0
    assert summary["gate_rule_count"] == 1
    assert summary["skipped_rule_count"] == 1  # advisory 不参与判定，但会被计数


def test_run_gate_reports_violation_with_repair_steps(tmp_path: Path) -> None:
    rules = _rules(tmp_path / "rules.yaml")
    source = _tree(tmp_path / "repo", violating=True)
    summary = run_gate([rules], source)
    assert summary["ok"] is False
    assert summary["violation_count"] == 1
    finding = summary["results"][0]["findings"][0]
    assert finding["path"] == "pkg/core/mod.py"
    assert finding["repair_steps"][0] == "Step 1: 定位导入点。"
    text = format_text(summary)
    assert "GATE-001" in text and "Step 2: 下沉能力。" in text and "未通过" in text


def test_run_gate_rejects_missing_rules_file(tmp_path: Path) -> None:
    source = _tree(tmp_path / "repo", violating=False)
    try:
        run_gate([tmp_path / "absent.yaml"], source)
    except ValueError as exc:
        assert "不存在" in str(exc)
    else:  # pragma: no cover - 缺文件必须报错
        raise AssertionError("缺少规则文件时应抛 ValueError")


def test_rule_paths_expand_directories(tmp_path: Path) -> None:
    directory = tmp_path / "rules"
    directory.mkdir()
    first = _write(directory / "a.yaml", "rules: []\n")
    second = _write(directory / "b.yaml", "rules: []\n")
    assert expand_rule_paths([directory, first]) == [first, second, first]


def test_cli_exit_codes(tmp_path: Path) -> None:
    rules = _rules(tmp_path / "rules.yaml")
    clean = _tree(tmp_path / "clean", violating=False)
    dirty = _tree(tmp_path / "dirty", violating=True)

    def _run(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "scripts/check_rules.py", *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )

    passed = _run("--rules", str(rules), "--source-root", str(clean))
    assert passed.returncode == 0, passed.stderr
    assert "Gate" not in passed.stdout or "通过" in passed.stdout

    failed = _run("--rules", str(rules), "--source-root", str(dirty))
    assert failed.returncode == 1
    assert "Step 1: 定位导入点。" in failed.stdout

    broken = _run("--rules", str(tmp_path / "absent.yaml"), "--source-root", str(clean))
    assert broken.returncode == 2

    as_json = _run("--rules", str(rules), "--source-root", str(dirty), "--format", "json")
    payload = json.loads(as_json.stdout)
    assert payload["ok"] is False
    assert payload["violation_count"] == 1
