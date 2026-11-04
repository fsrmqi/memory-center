"""resume/handoff/write-policy/auto-sync/eval 规则加载与同步模式阈值。

从 shared.py 按独立职责拆出(ADR-0002)。
"""
from __future__ import annotations

import re
from typing import Any

from memory_center.core.governance.rules import (
    DEFAULT_AUTO_SYNC_RULES,
    DEFAULT_EVAL_RULES,
    DEFAULT_HANDOFF_RULES,
    DEFAULT_RESUME_RULES,
    DEFAULT_WRITE_POLICY_RULES,
    load_yaml_rule_config,
)
from memory_center.core.storage.workspace import WorkspaceStore


def _load_resume_rules(store: WorkspaceStore, text: str) -> dict[str, Any]:
    data = load_yaml_rule_config(store, "resume-rules.yaml", DEFAULT_RESUME_RULES)
    default = dict(DEFAULT_RESUME_RULES.get("default", {}))
    default.update(data.get("default", {}))
    normalized = (text or "").lower()
    for profile_name, profile in (data.get("profiles", {}) or {}).items():
        triggers = [str(item).lower() for item in profile.get("trigger_keywords", [])]
        if triggers and any(re.search(rf'\b{re.escape(token)}\b', normalized) for token in triggers):
            merged = dict(default)
            merged.update(profile)
            merged["profile_name"] = profile_name
            return merged
    default["profile_name"] = "default"
    return default


def _load_handoff_rules(store: WorkspaceStore, normalized_model: str) -> dict[str, Any]:
    data = load_yaml_rule_config(store, "handoff-rules.yaml", DEFAULT_HANDOFF_RULES)
    default = dict(DEFAULT_HANDOFF_RULES.get("default", {}))
    default.update(data.get("default", {}))
    for profile_name, profile in (data.get("profiles", {}) or {}).items():
        trigger_models = [str(item).lower() for item in profile.get("trigger_models", [])]
        if trigger_models and normalized_model in trigger_models:
            merged = dict(default)
            merged.update(profile)
            merged["profile_name"] = profile_name
            return merged
    default["profile_name"] = "default"
    return default


def _load_write_policy_rules(store: WorkspaceStore) -> dict[str, Any]:
    return load_yaml_rule_config(store, "write-policy-rules.yaml", DEFAULT_WRITE_POLICY_RULES).get("default", {})


def _load_auto_sync_rules(store: WorkspaceStore) -> dict[str, Any]:
    return load_yaml_rule_config(store, "auto-sync-rules.yaml", DEFAULT_AUTO_SYNC_RULES).get("default", {})


def _load_eval_rules(store: WorkspaceStore) -> dict[str, Any]:
    return load_yaml_rule_config(store, "eval-rules.yaml", DEFAULT_EVAL_RULES)


def _score_threshold_for_sync_mode(auto_sync_mode: str) -> int:
    mode = (auto_sync_mode or "balanced").strip().lower()
    if mode == "safe":
        mode = "strict"
    if mode == "strict":
        return 4
    if mode == "aggressive":
        return 1
    return 3


def _choose_l3_artifact_name(text: str) -> str:
    normalized = (text or "").lower()
    if any(k in normalized for k in ["团队", "协作", "code review", "评审", "规范", "rules", "约定"]):
        return "team_rules"
    if any(k in normalized for k in ["架构", "invariant", "分层", "模块边界", "边界", "design principle"]):
        return "architecture_invariants"
    if any(k in normalized for k in ["迁移", "migration", "cutover", "灰度", "兼容期"]):
        return "active_migration_policy"
    return "workspace_profile"
