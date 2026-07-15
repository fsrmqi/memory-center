"""Learned Heuristics Register — store and recall agent-learned patterns.

Implements ECC-4 from NEXT_PHASE_MASTER_PLAN.md.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import load_workspace_data
from ..store import WorkspaceStore

HEURISTICS_FILE = "learned-heuristics.jsonl"
_DEFAULT_CONFIDENCE = 0.5
_MAX_QUERY_SCAN = 5000
_RETRIEVAL_SOURCE_WEIGHT_MIN = 0.35
_RETRIEVAL_SOURCE_WEIGHT_MAX = 0.75
_RETRIEVAL_SOURCES = {"exact", "graph", "sparse", "bm25", "semantic", "vector"}
HEURISTICS_SCHEMA_VERSION = 2
LEARNING_POLICY_VERSION = 1
DEFAULT_LEARNING_POLICY: dict[str, Any] = {
    "version": LEARNING_POLICY_VERSION,
    "candidate_path_learning": {
        "outcome_deltas": {
            "confirmed": 0.12,
            "demoted": -0.08,
            "rejected": -0.20,
            "rollback": -0.28,
            "needs-more-context": -0.03,
        },
        "provisional_promotion_cap": 0.54,
        "rollback_recommendation_cap": 0.35,
        "stale_decay_steps": [
            {"days": 180, "factor": 0.72, "reason": "stale-180d"},
            {"days": 90, "factor": 0.85, "reason": "stale-90d"},
            {"days": 30, "factor": 0.93, "reason": "stale-30d"},
        ],
        "merge_weights": {
            "rule_weight": 0.4,
            "learned_weight": 0.6,
        },
    },
    "workflow_profile_learning": {
        "merge_weights": {
            "base_weight": 0.5,
            "learned_weight": 0.5,
        },
    },
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clamp_weight(value: float) -> float:
    return max(0.0, min(1.0, round(float(value), 4)))


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _count_evidence(evidence: Any) -> int:
    if isinstance(evidence, list):
        return len([item for item in evidence if item])
    if isinstance(evidence, dict):
        return 1 if evidence else 0
    if isinstance(evidence, str):
        return 1 if evidence.strip() else 0
    return 1 if evidence else 0


def _normalize_evidence(evidence: Any) -> list[Any]:
    if evidence is None:
        return []
    if isinstance(evidence, list):
        return [item for item in evidence if item]
    if isinstance(evidence, str):
        return [evidence] if evidence.strip() else []
    if isinstance(evidence, dict):
        return [evidence] if evidence else []
    return [evidence]


def _deep_merge_dict(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_dict(merged[key], value)
        else:
            merged[key] = value
    return merged


def _normalize_learning_policy(policy: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(policy or {})
    if "candidate_learning" in normalized and "candidate_path_learning" not in normalized:
        normalized["candidate_path_learning"] = normalized.pop("candidate_learning")
    if "workflow_learning" in normalized and "workflow_profile_learning" not in normalized:
        normalized["workflow_profile_learning"] = normalized.pop("workflow_learning")
    merged = _deep_merge_dict(DEFAULT_LEARNING_POLICY, normalized)
    merged["version"] = _safe_int(merged.get("version"), LEARNING_POLICY_VERSION)
    return merged


def load_learning_policy(workspace_file: str | Path) -> dict[str, Any]:
    """Load optional learning policy from workspace.yaml, preserving defaults."""
    try:
        raw = load_workspace_data(workspace_file)
    except Exception:
        return _normalize_learning_policy({})
    override = raw.get("learning_policy", {}) or {}
    if not isinstance(override, dict):
        return _normalize_learning_policy({})
    return _normalize_learning_policy(override)


def _candidate_policy(policy: dict[str, Any]) -> dict[str, Any]:
    value = policy.get("candidate_path_learning", {}) or {}
    return value if isinstance(value, dict) else {}


def _workflow_policy(policy: dict[str, Any]) -> dict[str, Any]:
    value = policy.get("workflow_profile_learning", {}) or {}
    return value if isinstance(value, dict) else {}


def _normalized_decay_steps(policy: dict[str, Any]) -> list[tuple[int, float, str]]:
    steps = (_candidate_policy(policy).get("stale_decay_steps", []) or [])
    normalized: list[tuple[int, float, str]] = []
    for item in steps:
        if not isinstance(item, dict):
            continue
        days = int(item.get("days", 0) or 0)
        factor = float(item.get("factor", 1.0) or 1.0)
        reason = str(item.get("reason", "") or f"stale-{days}d")
        if days > 0:
            normalized.append((days, factor, reason))
    normalized.sort(reverse=True)
    return normalized


def _merge_weight(policy: dict[str, Any], *, kind: str, base_weight: float, learned_weight: float) -> float:
    weights = (_candidate_policy(policy) if kind == "candidate_path" else _workflow_policy(policy)).get("merge_weights", {}) or {}
    if kind == "candidate_path":
        primary = float(weights.get("rule_weight", 0.4) or 0.4)
        secondary = float(weights.get("learned_weight", 0.6) or 0.6)
    else:
        primary = float(weights.get("base_weight", 0.5) or 0.5)
        secondary = float(weights.get("learned_weight", 0.5) or 0.5)
    total = primary + secondary
    if total <= 0:
        return learned_weight
    return _clamp_weight((base_weight * primary + learned_weight * secondary) / total)


def _derive_delta(outcome: str, evidence_count: int, policy: dict[str, Any], explicit_delta: Any = None) -> float:
    if explicit_delta is not None:
        return float(explicit_delta)
    outcome_key = str(outcome or "").strip().lower()
    if outcome_key == "confirmed" and evidence_count <= 0:
        return 0.0
    deltas = _candidate_policy(policy).get("outcome_deltas", {}) or {}
    return float(deltas.get(outcome_key, 0.0))


def _normalize_feedback_payload(payload: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    outcome = str(payload.get("outcome", "") or "").strip()
    evidence = _normalize_evidence(payload.get("evidence"))
    weight_before = payload.get("weight_before", payload.get("confidence", _DEFAULT_CONFIDENCE))
    weight_before_value = _safe_float(weight_before, _DEFAULT_CONFIDENCE)
    explicit_delta = payload.get("weight_delta", payload.get("confidence_delta"))
    explicit_after = payload.get("weight_after")
    if explicit_after is not None:
        weight_after = _clamp_weight(_safe_float(explicit_after, weight_before_value))
    elif explicit_delta is not None:
        weight_after = _clamp_weight(weight_before_value + _safe_float(explicit_delta, 0.0))
    elif payload.get("confidence") is not None:
        weight_after = _clamp_weight(_safe_float(payload.get("confidence"), weight_before_value))
    else:
        delta = _derive_delta(outcome, len(evidence), policy, explicit_delta)
        weight_after = _clamp_weight(weight_before_value + delta)
    delta = round(weight_after - _clamp_weight(weight_before_value), 4)
    payload["evidence"] = evidence
    payload["evidence_count"] = len(evidence)
    payload["weight_before"] = _clamp_weight(weight_before_value)
    payload["weight_delta"] = delta
    payload["weight_after"] = weight_after
    payload["confidence"] = payload["weight_after"]
    return payload


def _normalize_heuristic_row(row: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(row or {})
    if not normalized:
        return {}

    # Historical imports may have an archival timestamp rather than a verified
    # observation time, so they must not be decayed during compatibility reads.
    normalized["_legacy_schema_row"] = "schema_version" not in normalized
    normalized["schema_version"] = _safe_int(normalized.get("schema_version"), 1)
    normalized["policy_version"] = _safe_int(
        normalized.get("policy_version"),
        _safe_int(policy.get("version"), LEARNING_POLICY_VERSION),
    )
    normalized.setdefault("usage_count", 0)
    normalized.setdefault("recorded_at", normalized.get("updated_at", normalized.get("created_at", "")))

    candidate_type = str(normalized.get("candidate_type", "") or "")
    target = str(normalized.get("target", "") or "")
    if candidate_type or target or normalized.get("event_type") == "candidate_feedback":
        if candidate_type or target:
            normalized.setdefault("category", "candidate-path")
            if candidate_type and target:
                normalized.setdefault("pattern", f"{candidate_type}:{target}")
        normalized.setdefault("trigger", normalized.get("source", "") or "candidate-path-feedback")
        normalized["event_type"] = "candidate_feedback"
        normalized = _normalize_feedback_payload(normalized, policy)
    else:
        normalized.setdefault("event_type", "heuristic_record")
        confidence = normalized.get("weight_after", normalized.get("confidence", _DEFAULT_CONFIDENCE))
        normalized["confidence"] = _clamp_weight(_safe_float(confidence, _DEFAULT_CONFIDENCE))
        if "confidence_delta" in normalized and "weight_delta" not in normalized:
            normalized["weight_delta"] = normalized["confidence_delta"]

    return normalized


def _group_key(row: dict[str, Any], heuristic_to_group: dict[str, str]) -> str:
    heuristic_id = str(row.get("heuristic_id", "") or "")
    candidate_type = str(row.get("candidate_type", "") or "")
    target = str(row.get("target", "") or "")
    category = str(row.get("category", "") or "")
    pattern = str(row.get("pattern", "") or "")

    if candidate_type or target:
        key = f"candidate::{candidate_type}::{target}"
    elif category or pattern:
        key = f"pattern::{category}::{pattern}"
    elif heuristic_id and heuristic_id in heuristic_to_group:
        key = heuristic_to_group[heuristic_id]
    elif heuristic_id:
        key = f"heuristic::{heuristic_id}"
    else:
        key = ""

    if heuristic_id and key:
        heuristic_to_group[heuristic_id] = key
    return key


def _row_ts(row: dict[str, Any]) -> str:
    return str(
        row.get("updated_at")
        or row.get("recorded_at")
        or row.get("created_at")
        or ""
    )


def _row_sort_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        _row_ts(row),
        str(row.get("created_at", "") or ""),
        str(row.get("heuristic_id", "") or ""),
    )


def _parse_iso_datetime(value: str) -> datetime | None:
    if not value:
        return None
    normalized = str(value).strip()
    if not normalized:
        return None
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _apply_time_decay(item: dict[str, Any], recommended_weight: float, policy: dict[str, Any]) -> float:
    last_updated_at = _parse_iso_datetime(str(item.get("last_updated_at", "") or ""))
    if last_updated_at is None:
        item["stale_days"] = 0
        item["decay_applied"] = False
        item["decay_factor"] = 1.0
        return recommended_weight

    age_days = max((datetime.now(timezone.utc) - last_updated_at).days, 0)
    item["stale_days"] = age_days
    item["decay_applied"] = False
    item["decay_factor"] = 1.0
    if age_days < 30:
        return recommended_weight

    for threshold_days, factor, reason in _normalized_decay_steps(policy):
        if age_days >= threshold_days:
            item["decay_applied"] = True
            item["decay_factor"] = factor
            if not item.get("guard_reason"):
                item["guard_reason"] = reason
            if item.get("recommendation_state") == "stable":
                item["recommendation_state"] = "stale"
            return recommended_weight * factor
    return recommended_weight


def _apply_recommendation_guard(item: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    """Prevent one-off wins from becoming long-term default recommendations too early."""
    recommended_weight = float(item.get("confidence", _DEFAULT_CONFIDENCE) or _DEFAULT_CONFIDENCE)
    category = str(item.get("category", "") or "")
    positive_count = int(item.get("positive_count", 0) or 0)
    negative_count = int(item.get("negative_count", 0) or 0)
    rollback_count = int(item.get("rollback_count", 0) or 0)
    event_count = int(item.get("event_count", 0) or 0)
    distinct_sessions = int(item.get("distinct_session_count", 0) or 0)
    distinct_tasks = int(item.get("distinct_task_count", 0) or 0)
    evidence_count = int(item.get("evidence_count", 0) or 0)

    item["promotion_ready"] = True
    item["guard_reason"] = ""
    item["recommendation_state"] = "stable"
    item["decay_applied"] = False
    item["decay_factor"] = 1.0
    item["stale_days"] = 0

    if category != "candidate-path":
        item["recommended_weight"] = _clamp_weight(recommended_weight)
        return item

    support_count = max(event_count, distinct_sessions, distinct_tasks)
    provisional_cap = float(_candidate_policy(policy).get("provisional_promotion_cap", 0.54) or 0.54)
    rollback_cap = float(_candidate_policy(policy).get("rollback_recommendation_cap", 0.35) or 0.35)
    if rollback_count > 0 and positive_count <= rollback_count + 1:
        recommended_weight = min(recommended_weight, rollback_cap)
        item["promotion_ready"] = False
        item["guard_reason"] = "rollback-observed"
        item["recommendation_state"] = "rolled-back"
    elif positive_count > 0 and negative_count == 0 and support_count < 2:
        recommended_weight = min(recommended_weight, provisional_cap)
        item["promotion_ready"] = False
        item["guard_reason"] = "single-sample-positive"
        item["recommendation_state"] = "provisional"
    elif positive_count > 0 and negative_count == 0 and evidence_count < 2:
        recommended_weight = min(recommended_weight, 0.58)
        item["promotion_ready"] = False
        item["guard_reason"] = "low-evidence-support"
        item["recommendation_state"] = "provisional"
    elif negative_count > 0 and positive_count <= 1:
        item["recommendation_state"] = "guarded-negative"

    if int(item.get("legacy_schema_count", 0) or 0) == 0:
        recommended_weight = _apply_time_decay(item, recommended_weight, policy)
    item["recommended_weight"] = _clamp_weight(recommended_weight)
    return item


def _candidate_sort_key(item: dict[str, Any]) -> tuple[int, float, str]:
    return (
        0 if item.get("status") == "confirmed" else 1 if item.get("status") == "probable" else 2,
        -float(item.get("weight", 0.0)),
        str(item.get("candidate_type", "") or ""),
    )


def _learning_index_key(candidate_type: str, target: str) -> tuple[str, str]:
    return (str(candidate_type or ""), str(target or ""))


def _merge_candidate_status(status: str, recommendation_state: str) -> str:
    normalized_status = str(status or "possible")
    state = str(recommendation_state or "")
    if state == "rolled-back":
        return "possible"
    if state in {"provisional", "stale", "guarded-negative"} and normalized_status == "confirmed":
        return "probable"
    return normalized_status


def _matching_policy_snapshot(policy: dict[str, Any], category: str, candidate_type: str) -> dict[str, Any]:
    candidate_type_value = str(candidate_type or "")
    if candidate_type_value == "workflow_profile":
        return {
            "version": _safe_int(policy.get("version"), LEARNING_POLICY_VERSION),
            "kind": "workflow_profile_learning",
            "workflow_profile_learning": _workflow_policy(policy),
        }
    if str(category or "") == "candidate-path" or candidate_type_value:
        return {
            "version": _safe_int(policy.get("version"), LEARNING_POLICY_VERSION),
            "kind": "candidate_path_learning",
            "candidate_path_learning": _candidate_policy(policy),
        }
    return {"version": _safe_int(policy.get("version"), LEARNING_POLICY_VERSION), "kind": "generic"}


def _build_learning_reasons(item: dict[str, Any]) -> list[dict[str, Any]]:
    reasons: list[dict[str, Any]] = []
    recommendation_state = str(item.get("recommendation_state", "") or "")
    guard_reason = str(item.get("guard_reason", "") or "")
    if recommendation_state:
        reasons.append(
            {
                "type": "recommendation_state",
                "state": recommendation_state,
                "guard_reason": guard_reason,
                "message": f"当前推荐状态为 {recommendation_state}" + (f"，原因: {guard_reason}" if guard_reason else ""),
            }
        )
    if item.get("decay_applied"):
        reasons.append(
            {
                "type": "time_decay",
                "stale_days": _safe_int(item.get("stale_days"), 0),
                "decay_factor": _safe_float(item.get("decay_factor"), 1.0),
                "message": f"由于长期未更新，推荐权重按 {item.get('decay_factor')} 系数衰减。",
            }
        )
    positive_count = _safe_int(item.get("positive_count"), 0)
    negative_count = _safe_int(item.get("negative_count"), 0)
    rollback_count = _safe_int(item.get("rollback_count"), 0)
    if positive_count or negative_count or rollback_count:
        reasons.append(
            {
                "type": "evidence_balance",
                "positive_count": positive_count,
                "negative_count": negative_count,
                "rollback_count": rollback_count,
                "distinct_session_count": _safe_int(item.get("distinct_session_count"), 0),
                "evidence_count": _safe_int(item.get("evidence_count"), 0),
                "message": "当前推荐由正向/负向验证样本共同决定。",
            }
        )
    confidence = _safe_float(item.get("confidence"), _DEFAULT_CONFIDENCE)
    recommended_weight = _safe_float(item.get("recommended_weight"), confidence)
    if round(recommended_weight, 4) != round(confidence, 4):
        reasons.append(
            {
                "type": "recommended_weight_adjustment",
                "confidence": confidence,
                "recommended_weight": recommended_weight,
                "message": "推荐排序权重与原始学习置信度不同，说明保护或衰减已生效。",
            }
        )
    return reasons


class HeuristicsRegister:
    """Store and query learned heuristics from agent experience."""

    def __init__(self, workspace_file: str | Path):
        self._store = WorkspaceStore(workspace_file)
        self._policy = load_learning_policy(workspace_file)

    def record(
        self,
        category: str | dict[str, Any],
        pattern: str = "",
        trigger: str = "",
        outcome: str = "",
        confidence: float = _DEFAULT_CONFIDENCE,
        **extra: Any,
    ) -> dict[str, Any]:
        """Record a learned heuristic or a structured feedback event.

        Supports both the historical positional signature and dict payloads used by
        CLI/MCP/HTTP facades.
        """
        if isinstance(category, dict):
            entry = dict(category)
        else:
            entry = {
                "category": category,
                "pattern": pattern,
                "trigger": trigger,
                "outcome": outcome,
                "confidence": confidence,
            }
            entry.update(extra)

        entry.setdefault(
            "heuristic_id",
            f"heur-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}",
        )
        entry.setdefault("schema_version", HEURISTICS_SCHEMA_VERSION)
        entry.setdefault("policy_version", _safe_int(self._policy.get("version"), LEARNING_POLICY_VERSION))
        entry.setdefault("usage_count", 0)
        entry.setdefault("recorded_at", _utc_now_iso())
        entry.setdefault("event_type", "heuristic_record")

        candidate_type = str(entry.get("candidate_type", "") or "")
        target = str(entry.get("target", "") or "")
        if candidate_type or target or entry.get("event_type") == "candidate_feedback":
            entry["event_type"] = "candidate_feedback"
            entry = _normalize_feedback_payload(entry, self._policy)
        else:
            entry["confidence"] = _clamp_weight(_safe_float(entry.get("confidence", _DEFAULT_CONFIDENCE), _DEFAULT_CONFIDENCE))

        self._store.append_jsonl(HEURISTICS_FILE, entry)
        return entry

    def query(self, category: str = "", limit: int = 20) -> list[dict[str, Any]]:
        """Query learned heuristics by category.

        Returns an aggregated view so repeated feedback on the same candidate path
        or heuristic pattern converges into one current weight.
        """
        rows = [
            _normalize_heuristic_row(row, self._policy)
            for row in self._store.read_jsonl_prefer_backend(HEURISTICS_FILE, limit=_MAX_QUERY_SCAN)
            if isinstance(row, dict)
        ]
        rows.sort(key=_row_sort_key)
        heuristic_to_group: dict[str, str] = {}
        for row in rows:
            heuristic_id = str(row.get("heuristic_id", "") or "")
            if not heuristic_id:
                continue
            candidate_type = str(row.get("candidate_type", "") or "")
            target = str(row.get("target", "") or "")
            category_name = str(row.get("category", "") or "")
            pattern_name = str(row.get("pattern", "") or "")
            if candidate_type or target:
                heuristic_to_group[heuristic_id] = f"candidate::{candidate_type}::{target}"
            elif category_name or pattern_name:
                heuristic_to_group[heuristic_id] = f"pattern::{category_name}::{pattern_name}"
        grouped: dict[str, dict[str, Any]] = {}

        for row in rows:
            key = _group_key(row, heuristic_to_group)
            if not key:
                continue
            current = grouped.setdefault(
                key,
                {
                    "group_key": key,
                    "heuristic_id": str(row.get("heuristic_id", "") or ""),
                    "category": str(row.get("category", "") or ""),
                    "pattern": str(row.get("pattern", "") or ""),
                    "trigger": str(row.get("trigger", "") or ""),
                    "candidate_type": str(row.get("candidate_type", "") or ""),
                    "target": str(row.get("target", "") or ""),
                    "schema_version": _safe_int(row.get("schema_version"), 1),
                    "policy_version": _safe_int(row.get("policy_version"), _safe_int(self._policy.get("version"), LEARNING_POLICY_VERSION)),
                    "confidence": _DEFAULT_CONFIDENCE,
                    "initial_confidence": _DEFAULT_CONFIDENCE,
                    "usage_count": 0,
                    "event_count": 0,
                    "evidence_count": 0,
                    "latest_outcome": "",
                    "positive_count": 0,
                    "negative_count": 0,
                    "rollback_count": 0,
                    "uncertain_count": 0,
                    "sources": [],
                    "task_ids": [],
                    "session_ids": [],
                    "last_updated_at": "",
                    "legacy_schema_count": 0,
                },
            )

            if row.get("heuristic_id") and not current.get("heuristic_id"):
                current["heuristic_id"] = str(row.get("heuristic_id", "") or "")
            for field in ("category", "pattern", "trigger", "candidate_type", "target"):
                if row.get(field) and not current.get(field):
                    current[field] = row.get(field)
            current["schema_version"] = max(
                _safe_int(current.get("schema_version"), 1),
                _safe_int(row.get("schema_version"), 1),
            )
            current["policy_version"] = max(
                _safe_int(current.get("policy_version"), LEARNING_POLICY_VERSION),
                _safe_int(row.get("policy_version"), LEARNING_POLICY_VERSION),
            )

            current["event_count"] += 1
            if row.get("_legacy_schema_row"):
                current["legacy_schema_count"] += 1
            current["usage_count"] = max(
                _safe_int(current.get("usage_count", 0), 0),
                _safe_int(row.get("usage_count", 0), 0),
            )
            evidence_count = max(
                _count_evidence(row.get("evidence")),
                _safe_int(row.get("evidence_count", 0), 0),
            )
            current["evidence_count"] += evidence_count
            if row.get("source") and row["source"] not in current["sources"]:
                current["sources"].append(row["source"])
            if row.get("task_id") and row["task_id"] not in current["task_ids"]:
                current["task_ids"].append(row["task_id"])
            if row.get("session_id") and row["session_id"] not in current["session_ids"]:
                current["session_ids"].append(row["session_id"])
            outcome = str(row.get("outcome", "") or "").strip().lower()
            if outcome == "confirmed":
                current["positive_count"] += 1
            elif outcome in {"rejected", "demoted"}:
                current["negative_count"] += 1
            elif outcome == "rollback":
                current["negative_count"] += 1
                current["rollback_count"] += 1
            elif outcome:
                current["uncertain_count"] += 1

            last_updated = _row_ts(row)
            if last_updated >= str(current.get("last_updated_at", "")):
                current["last_updated_at"] = last_updated
                if row.get("outcome"):
                    current["latest_outcome"] = row.get("outcome")

            if "confidence_delta" in row or "weight_delta" in row:
                base_weight = row.get("weight_before", current["confidence"])
                base_weight_value = _safe_float(base_weight, float(current["confidence"]))
                delta_value = row.get("weight_delta", row.get("confidence_delta", 0.0))
                delta_float = _safe_float(delta_value, 0.0)
                if current["event_count"] == 1:
                    current["initial_confidence"] = _clamp_weight(base_weight_value)
                current["confidence"] = _clamp_weight(base_weight_value + delta_float)
            elif "weight_after" in row:
                if current["event_count"] == 1 and "weight_before" in row:
                    current["initial_confidence"] = _clamp_weight(_safe_float(row.get("weight_before"), _DEFAULT_CONFIDENCE))
                current["confidence"] = _clamp_weight(_safe_float(row.get("weight_after", current["confidence"]), float(current["confidence"])))
            elif "confidence" in row:
                current["confidence"] = _clamp_weight(_safe_float(row.get("confidence", current["confidence"]), float(current["confidence"])))
                if current["event_count"] == 1:
                    current["initial_confidence"] = current["confidence"]

        aggregated = []
        for item in grouped.values():
            if category and item.get("category") != category:
                continue
            item["confidence"] = _clamp_weight(item["confidence"])
            item["distinct_task_count"] = len(item.get("task_ids", []))
            item["distinct_session_count"] = len(item.get("session_ids", []))
            item = _apply_recommendation_guard(item, self._policy)
            aggregated.append(item)

        aggregated.sort(
            key=lambda row: (
                row.get("recommended_weight", row.get("confidence", 0.0)),
                row.get("confidence", 0.0),
                row.get("evidence_count", 0),
                row.get("last_updated_at", ""),
            ),
            reverse=True,
        )
        return aggregated[:limit]

    def explain(
        self,
        *,
        candidate_type: str = "",
        target: str = "",
        category: str = "candidate-path",
        heuristic_id: str = "",
        pattern: str = "",
        limit: int = 10,
    ) -> dict[str, Any]:
        """Explain how one learned heuristic/candidate reached its current recommendation state."""
        rows = [
            _normalize_heuristic_row(row, self._policy)
            for row in self._store.read_jsonl_prefer_backend(HEURISTICS_FILE, limit=_MAX_QUERY_SCAN)
            if isinstance(row, dict)
        ]
        rows.sort(key=_row_sort_key)

        heuristic_to_group: dict[str, str] = {}
        for row in rows:
            row_heuristic_id = str(row.get("heuristic_id", "") or "")
            if not row_heuristic_id:
                continue
            row_candidate_type = str(row.get("candidate_type", "") or "")
            row_target = str(row.get("target", "") or "")
            row_category = str(row.get("category", "") or "")
            row_pattern = str(row.get("pattern", "") or "")
            if row_candidate_type or row_target:
                heuristic_to_group[row_heuristic_id] = f"candidate::{row_candidate_type}::{row_target}"
            elif row_category or row_pattern:
                heuristic_to_group[row_heuristic_id] = f"pattern::{row_category}::{row_pattern}"

        requested_key = ""
        if candidate_type or target:
            requested_key = f"candidate::{candidate_type}::{target}"
        elif category or pattern:
            requested_key = f"pattern::{category}::{pattern}"
        elif heuristic_id:
            requested_key = heuristic_to_group.get(heuristic_id, f"heuristic::{heuristic_id}")

        current: dict[str, Any] | None = None
        for item in self.query(category=category if category else "", limit=_MAX_QUERY_SCAN):
            if requested_key and item.get("group_key") == requested_key:
                current = item
                break
            if heuristic_id and str(item.get("heuristic_id", "") or "") == heuristic_id:
                current = item
                requested_key = str(item.get("group_key", "") or requested_key)
                break

        matched_rows: list[dict[str, Any]] = []
        for row in rows:
            group_key = _group_key(row, heuristic_to_group)
            if requested_key:
                if group_key == requested_key:
                    matched_rows.append(row)
            elif heuristic_id and str(row.get("heuristic_id", "") or "") == heuristic_id:
                matched_rows.append(row)

        recent_events: list[dict[str, Any]] = []
        for row in reversed(matched_rows[-limit:]):
            recent_events.append(
                {
                    "heuristic_id": str(row.get("heuristic_id", "") or ""),
                    "event_type": str(row.get("event_type", "") or ""),
                    "outcome": str(row.get("outcome", "") or ""),
                    "recorded_at": _row_ts(row),
                    "candidate_type": str(row.get("candidate_type", "") or ""),
                    "target": str(row.get("target", "") or ""),
                    "pattern": str(row.get("pattern", "") or ""),
                    "weight_before": row.get("weight_before"),
                    "weight_delta": row.get("weight_delta", row.get("confidence_delta")),
                    "weight_after": row.get("weight_after", row.get("confidence")),
                    "evidence_count": max(_count_evidence(row.get("evidence")), _safe_int(row.get("evidence_count"), 0)),
                    "source": str(row.get("source", "") or ""),
                    "task_id": str(row.get("task_id", "") or ""),
                    "session_id": str(row.get("session_id", "") or ""),
                    "schema_version": _safe_int(row.get("schema_version"), 1),
                    "policy_version": _safe_int(row.get("policy_version"), LEARNING_POLICY_VERSION),
                }
            )

        policy_snapshot = _matching_policy_snapshot(self._policy, category, candidate_type or (current or {}).get("candidate_type", ""))
        result: dict[str, Any] = {
            "query": {
                "candidate_type": candidate_type,
                "target": target,
                "category": category,
                "heuristic_id": heuristic_id,
                "pattern": pattern,
                "limit": limit,
            },
            "found": current is not None or bool(matched_rows),
            "matched_group_key": requested_key,
            "current": current,
            "recent_events": recent_events,
            "event_count": len(matched_rows),
            "reasons": _build_learning_reasons(current or {}),
            "policy_snapshot": policy_snapshot,
        }
        if current is None:
            result["diagnostics"] = {
                "status": "not_found",
                "reason": "未找到匹配的 learning 目标。",
            }
        return result

    def update_confidence(self, heuristic_id: str, delta: float) -> dict[str, Any]:
        """Update confidence based on observed outcomes."""
        entry = {
            "heuristic_id": heuristic_id,
            "event_type": "confidence_adjustment",
            "confidence_delta": delta,
            "weight_delta": delta,
            "schema_version": HEURISTICS_SCHEMA_VERSION,
            "policy_version": _safe_int(self._policy.get("version"), LEARNING_POLICY_VERSION),
            "updated_at": _utc_now_iso(),
        }
        self._store.append_jsonl(HEURISTICS_FILE, entry)
        return entry

    def record_candidate_path_feedback(
        self,
        *,
        candidate_type: str,
        target: str,
        outcome: str,
        evidence: list[Any] | None = None,
        source: str = "",
        task_id: str = "",
        session_id: str = "",
        weight_before: float | None = None,
        weight_delta: float | None = None,
        recorded_at: str = "",
        updated_at: str = "",
        why: str = "",
        next_action: str = "",
        verification_cost: str = "",
        category: str = "candidate-path",
        pattern: str = "",
        trigger: str = "",
    ) -> dict[str, Any]:
        """Record outcome feedback for a candidate path."""
        effective_pattern = pattern or f"{candidate_type}:{target}"
        effective_weight_before = weight_before
        if effective_weight_before is None:
            effective_weight_before = self._current_candidate_weight(candidate_type, target, default=_DEFAULT_CONFIDENCE)
        payload = {
            "event_type": "candidate_feedback",
            "category": category,
            "pattern": effective_pattern,
            "trigger": trigger or source or "candidate-path-feedback",
            "candidate_type": candidate_type,
            "target": target,
            "outcome": outcome,
            "evidence": evidence or [],
            "source": source,
            "task_id": task_id,
            "session_id": session_id,
            "weight_before": effective_weight_before,
            "weight_delta": weight_delta,
            "recorded_at": recorded_at,
            "updated_at": updated_at,
            "why": why,
            "next_action": next_action,
            "verification_cost": verification_cost,
        }
        if not recorded_at:
            payload.pop("recorded_at")
        if not updated_at:
            payload.pop("updated_at")
        return self.record(payload)

    def _current_candidate_weight(self, candidate_type: str, target: str, default: float = _DEFAULT_CONFIDENCE) -> float:
        for item in self.query(category="candidate-path", limit=_MAX_QUERY_SCAN):
            if item.get("candidate_type") == candidate_type and item.get("target") == target:
                return float(item.get("confidence", default) or default)
        return default


def record_candidate_path_feedback(
    workspace_file: str | Path,
    *,
    candidate_type: str,
    target: str,
    outcome: str,
    evidence: list[Any] | None = None,
    source: str = "",
    task_id: str = "",
    session_id: str = "",
    weight_before: float | None = None,
    weight_delta: float | None = None,
    recorded_at: str = "",
    updated_at: str = "",
    why: str = "",
    next_action: str = "",
    verification_cost: str = "",
    category: str = "candidate-path",
    pattern: str = "",
    trigger: str = "",
) -> dict[str, Any]:
    """Convenience helper for recording candidate-path verification feedback."""
    register = HeuristicsRegister(workspace_file)
    return register.record_candidate_path_feedback(
        candidate_type=candidate_type,
        target=target,
        outcome=outcome,
        evidence=evidence,
        source=source,
        task_id=task_id,
        session_id=session_id,
        weight_before=weight_before,
        weight_delta=weight_delta,
        recorded_at=recorded_at,
        updated_at=updated_at,
        why=why,
        next_action=next_action,
        verification_cost=verification_cost,
        category=category,
        pattern=pattern,
        trigger=trigger,
    )


def candidate_path_learning_index(workspace_file: str | Path) -> dict[tuple[str, str], dict[str, Any]]:
    """Build an index of learned candidate-path recommendations."""
    rows = HeuristicsRegister(workspace_file).query(category="candidate-path", limit=_MAX_QUERY_SCAN)
    return {
        _learning_index_key(
            str(item.get("candidate_type", "") or ""),
            str(item.get("target", "") or ""),
        ): item
        for item in rows
        if item.get("candidate_type") and item.get("target")
    }


def apply_candidate_path_learning(
    workspace_file: str | Path,
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge learned recommendation weights back into orchestrator candidate paths."""
    try:
        learning_index = candidate_path_learning_index(workspace_file)
        policy = load_learning_policy(workspace_file)
    except Exception:
        learning_index = {}
        policy = dict(DEFAULT_LEARNING_POLICY)

    adjusted: list[dict[str, Any]] = []
    for candidate in candidates:
        item = dict(candidate)
        aliases = item.pop("_learning_aliases", []) or []
        learning = learning_index.get(
            _learning_index_key(
                str(item.get("candidate_type", "") or ""),
                str(item.get("target", "") or ""),
            )
        )
        if learning is None:
            for alias in aliases:
                alias_type = str((alias or {}).get("candidate_type", "") or "")
                alias_target = str((alias or {}).get("target", "") or "")
                learning = learning_index.get(_learning_index_key(alias_type, alias_target))
                if learning is not None:
                    break

        item["learning_applied"] = learning is not None
        if learning is not None:
            base_weight = float(item.get("weight", 0.0) or 0.0)
            learned_weight = float(
                learning.get("recommended_weight", learning.get("confidence", base_weight)) or base_weight
            )
            item["learned_confidence"] = float(learning.get("confidence", 0.0) or 0.0)
            item["learned_recommended_weight"] = learned_weight
            item["learning_state"] = str(learning.get("recommendation_state", "") or "")
            item["learning_guard_reason"] = str(learning.get("guard_reason", "") or "")
            item["weight"] = round(_merge_weight(policy, kind="candidate_path", base_weight=base_weight, learned_weight=learned_weight), 2)
            item["status"] = _merge_candidate_status(str(item.get("status", "") or "possible"), item["learning_state"])
        adjusted.append(item)

    adjusted.sort(key=_candidate_sort_key)
    return adjusted


def bounded_retrieval_source_weights(weights: dict[str, Any]) -> dict[str, float]:
    """Clamp learned retrieval preferences without changing rule constraints."""
    bounded: dict[str, float] = {}
    for source, value in dict(weights or {}).items():
        source_name = str(source or "").strip().lower()
        if source_name not in _RETRIEVAL_SOURCES:
            continue
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        bounded[source_name] = round(
            max(_RETRIEVAL_SOURCE_WEIGHT_MIN, min(_RETRIEVAL_SOURCE_WEIGHT_MAX, numeric)),
            4,
        )
    return bounded


def load_retrieval_source_weights(
    workspace_file: str | Path,
    *,
    intent: str,
) -> dict[str, float]:
    """Load bounded source preferences for one retrieval intent."""
    try:
        rows = HeuristicsRegister(workspace_file).query(
            category="retrieval-source",
            limit=_MAX_QUERY_SCAN,
        )
    except Exception:
        return {}

    requested_intent = str(intent or "general").strip().lower()
    wildcard: dict[str, Any] = {}
    exact: dict[str, Any] = {}
    for row in rows:
        if str(row.get("candidate_type", "") or "") != "retrieval-source":
            continue
        target = str(row.get("target", "") or "")
        if ":" not in target:
            continue
        row_intent, source = target.split(":", 1)
        weight = row.get("recommended_weight", row.get("confidence", _DEFAULT_CONFIDENCE))
        if row_intent == "*":
            wildcard[source] = weight
        elif row_intent == requested_intent:
            exact[source] = weight
    return bounded_retrieval_source_weights({**wildcard, **exact})


def record_retrieval_source_feedback(
    workspace_file: str | Path,
    *,
    intent: str,
    source: str,
    outcome: str,
    evidence: list[Any] | None = None,
    weight_before: float | None = None,
    task_id: str = "",
    session_id: str = "",
) -> dict[str, Any]:
    """Record verified source usefulness using bounded, lightweight deltas."""
    source_name = str(source or "").strip().lower()
    if source_name not in _RETRIEVAL_SOURCES:
        raise ValueError(f"unsupported retrieval source: {source_name}")
    intent_name = str(intent or "general").strip().lower()
    current_weights = load_retrieval_source_weights(workspace_file, intent=intent_name)
    current = float(
        weight_before
        if weight_before is not None
        else current_weights.get(source_name, _DEFAULT_CONFIDENCE)
    )
    normalized_outcome = str(outcome or "").strip().lower()
    deltas = {
        "confirmed": 0.05 if evidence else 0.0,
        "demoted": -0.05,
        "rejected": -0.08,
        "rollback": -0.15,
        "needs-more-context": -0.02,
    }
    delta = deltas.get(normalized_outcome, 0.0)
    return HeuristicsRegister(workspace_file).record_candidate_path_feedback(
        candidate_type="retrieval-source",
        target=f"{intent_name}:{source_name}",
        outcome=normalized_outcome,
        evidence=evidence or [],
        source="retrieval-policy",
        task_id=task_id,
        session_id=session_id,
        weight_before=current,
        weight_delta=delta,
        category="retrieval-source",
        pattern=f"{intent_name}:{source_name}",
        trigger="verified-retrieval-outcome",
    )
