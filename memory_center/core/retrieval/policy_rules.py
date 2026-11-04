"""工作区检索预算规则加载；解析失败时返回内置默认，绝不影响查询。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from memory_center.core.retrieval.policy import PURPOSE_DELTAS
from memory_center.core.storage.workspace import WorkspaceStore

RETRIEVAL_POLICY_RULES_FILE = "retrieval-policy.yaml"
_ALLOWED_DELTA_FIELDS = frozenset({"candidate_limit", "evidence_budget", "graph_depth"})


def load_purpose_deltas(workspace_file: str | Path) -> dict[str, dict[str, int]]:
    """读取可选 rules/retrieval-policy.yaml；仅接受已知 purpose/数值字段。"""
    defaults = {name: dict(values) for name, values in PURPOSE_DELTAS.items()}
    try:
        path = WorkspaceStore(workspace_file).rules_dir / RETRIEVAL_POLICY_RULES_FILE
        if not path.exists():
            return defaults
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        entries = raw.get("purpose_deltas", {}) if isinstance(raw, dict) else {}
        if not isinstance(entries, dict):
            return defaults
        for purpose, values in entries.items():
            if purpose not in defaults or not isinstance(values, dict):
                continue
            for field, value in values.items():
                if field not in _ALLOWED_DELTA_FIELDS:
                    continue
                try:
                    defaults[purpose][field] = int(value)
                except (TypeError, ValueError):
                    continue
    except (OSError, yaml.YAMLError, TypeError, ValueError):
        pass
    return defaults


__all__ = ["RETRIEVAL_POLICY_RULES_FILE", "load_purpose_deltas"]
