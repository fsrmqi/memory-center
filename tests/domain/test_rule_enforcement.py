"""Rule 的 enforcement 契约与可执行判据（``Rule.check``）测试。

覆盖：
- 历史规则缺省为 advisory，新增字段向后兼容；
- gate 规则必须同时具备可机检判据与修复步骤，否则拒绝加载；
- 三类判据（forbidden_import / max_lines / max_params）能真正检出违规；
- 违规结果自带 repair_steps，调用方无需回读规则。
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from memory_center.core.foundation.models import Rule
from memory_center.core.governance.rule_checks import (
    evaluate_gate_rules,
    run_check,
    supported_check_kinds,
    validate_check,
)
from memory_center.core.governance.rules import load_rules, validate_rule_item
from memory_center.core.storage.workspace import WorkspaceStore
from tests.fixtures import copy_demo_workspace


def _store(tmp_path: Path) -> WorkspaceStore:
    return WorkspaceStore(str(copy_demo_workspace(tmp_path)))


def _rule(tmp_path: Path, name: str, body: str) -> None:
    (tmp_path / name).write_text(textwrap.dedent(body), encoding="utf-8")


def _sample_tree(root: Path) -> Path:
    (root / "pkg" / "core").mkdir(parents=True)
    (root / "pkg" / "app").mkdir(parents=True)
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "core" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "app" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "app" / "impl.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "pkg" / "core" / "absolute.py").write_text(
        "from pkg.app.impl import VALUE\n", encoding="utf-8"
    )
    (root / "pkg" / "core" / "relative.py").write_text(
        "from ..app.impl import VALUE\n", encoding="utf-8"
    )
    (root / "pkg" / "core" / "clean.py").write_text("VALUE = 2\n", encoding="utf-8")
    return root


# ---------- 模型与校验 ----------


def test_rule_defaults_keep_existing_rules_advisory() -> None:
    rule = Rule(id="R-1", title="示例", scope=["x"], severity="must", rule="正文")
    assert rule.enforcement == "advisory"
    assert rule.check == {}
    assert rule.repair_steps == []


@pytest.mark.parametrize(
    "item, keyword",
    [
        ({"enforcement": "blocking"}, "非法"),
        ({"enforcement": "gate"}, "check"),
        (
            {"enforcement": "gate", "check": {"kind": "forbidden_import", "config": {}}},
            "forbidden_prefixes",
        ),
        (
            {"enforcement": "gate", "check": {"kind": "unknown_kind"}, "repair_steps": ["a"]},
            "不受支持",
        ),
        (
            {
                "enforcement": "gate",
                "check": {"kind": "max_lines", "config": {"max": 10}},
                "repair_steps": [],
                "checklist": [],
            },
            "repair_steps",
        ),
    ],
)
def test_invalid_enforcement_definitions_are_rejected(item: dict, keyword: str) -> None:
    problems = validate_rule_item(item)
    assert any(keyword in problem for problem in problems), problems


def test_gate_rule_with_check_and_steps_is_accepted(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _rule(
        store.rules_dir,
        "gate-rules.yaml",
        """
        rules:
          - id: ARCH-001
            title: core 不得依赖 application
            scope: [architecture]
            severity: must
            rule: core 子包不得导入 application。
            enforcement: gate
            check:
              kind: forbidden_import
              config:
                path_prefix: pkg/core
                forbidden_prefixes: [pkg.app]
            repair_steps:
              - Step 1: 找到 core 里对 application 的导入点。
              - Step 2: 把该能力下沉到 core 内合适的子包。
        """,
    )
    rules = load_rules(store)
    gate = [rule for rule in rules if rule.id == "ARCH-001"]
    assert gate and gate[0].enforcement == "gate"
    assert gate[0].check["kind"] == "forbidden_import"
    assert gate[0].repair_steps[0].startswith("Step 1")


def test_load_rules_rejects_gate_without_check(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _rule(
        store.rules_dir,
        "bad-gate.yaml",
        """
        rules:
          - id: ARCH-002
            title: 缺判据
            scope: [architecture]
            severity: must
            rule: 这条规则没有 check。
            enforcement: gate
            repair_steps: ["Step 1: 补 check。"]
        """,
    )
    with pytest.raises(ValueError) as excinfo:
        load_rules(store)
    message = str(excinfo.value)
    assert "ARCH-002" in message
    assert "Step 1" in message  # 报错自带下一步


# ---------- 可执行判据 ----------


def test_supported_check_kinds_are_declared() -> None:
    assert supported_check_kinds() == ("forbidden_import", "max_lines", "max_params")
    assert validate_check({"kind": "max_params", "config": {"max": 5}}) == []


def test_forbidden_import_detects_absolute_and_relative(tmp_path: Path) -> None:
    root = _sample_tree(tmp_path / "repo")
    rule = Rule(
        id="ARCH-001",
        title="core 不得依赖 app",
        scope=["architecture"],
        severity="must",
        rule="core 子包不得导入 pkg.app。",
        enforcement="gate",
        check={
            "kind": "forbidden_import",
            "config": {"path_prefix": "pkg/core", "forbidden_prefixes": ["pkg.app"]},
        },
        repair_steps=["Step 1: 定位导入点。", "Step 2: 下沉能力。"],
    )
    result = run_check(rule, root)
    paths = sorted(item["path"] for item in result["findings"])
    assert paths == ["pkg/core/absolute.py", "pkg/core/relative.py"]
    assert result["checked_files"] == 4
    assert result["findings"][0]["repair_steps"] == rule.repair_steps
    assert not result.get("error")


def test_max_lines_and_max_params(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "big.py").write_text("\n".join(["x = 1"] * 10), encoding="utf-8")
    (root / "wide.py").write_text(
        "def f(a, b, c):\n    return a\n\n\nclass K:\n    def m(self, a, b):\n        return a\n",
        encoding="utf-8",
    )
    lines_rule = Rule(
        id="SIZE-001",
        title="文件行数",
        scope=["size"],
        severity="warning",
        rule="单文件不超过 8 行。",
        enforcement="gate",
        check={"kind": "max_lines", "config": {"max": 8}},
        repair_steps=["Step 1: 拆分类或提取方法。"],
    )
    params_rule = Rule(
        id="SIZE-002",
        title="参数个数",
        scope=["size"],
        severity="warning",
        rule="函数参数不超过 2 个。",
        enforcement="gate",
        check={"kind": "max_params", "config": {"max": 2}},
        repair_steps=["Step 1: 收敛为 Request 对象。"],
    )
    line_findings = run_check(lines_rule, root)["findings"]
    assert [item["path"] for item in line_findings] == ["big.py"]

    param_findings = run_check(params_rule, root)["findings"]
    # f(a, b, c) 超限；K.m(self, a, b) 去掉 self 后是 2 个参数，不超限。
    assert [item["line"] for item in param_findings] == [1]


def test_advisory_rules_are_not_evaluated_by_gate(tmp_path: Path) -> None:
    root = _sample_tree(tmp_path / "repo")
    advisory = Rule(
        id="ADV-001",
        title="仅提示",
        scope=["architecture"],
        severity="must",
        rule="core 不建议依赖 app。",
        enforcement="advisory",
        check={
            "kind": "forbidden_import",
            "config": {"path_prefix": "pkg/core", "forbidden_prefixes": ["pkg.app"]},
        },
    )
    assert evaluate_gate_rules([advisory], root) == []


def test_invalid_check_reports_error_instead_of_raising(tmp_path: Path) -> None:
    root = _sample_tree(tmp_path / "repo")
    rule = Rule(
        id="BAD-001",
        title="坏判据",
        scope=["x"],
        severity="must",
        rule="判据缺 config。",
        enforcement="gate",
        check={"kind": "max_lines", "config": {}},
    )
    result = run_check(rule, root)
    assert result["findings"] == []
    assert "config.max" in result["error"]
