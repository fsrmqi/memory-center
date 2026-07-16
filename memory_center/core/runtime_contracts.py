"""Privacy-preserving runtime contract samples and compatibility verification."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .contracts import CONTRACT_DIFF_FILE, CONTRACT_SNAPSHOT_FILE
from .store import WorkspaceStore

RUNTIME_SAMPLES_FILE = "runtime-contract-samples.jsonl"
MIGRATIONS_FILE = "contract-migrations.json"
_FIELD_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")


def ingest_runtime_contract_samples(workspace_file: str | Path, samples: list[dict[str, Any]], source: str = "manual") -> dict[str, Any]:
    store = WorkspaceStore(workspace_file)
    accepted, rejected = [], []
    for sample in samples[:500]:
        normalized = _sanitize_sample(sample, source)
        if normalized is None:
            rejected.append({"kind": str(sample.get("kind", ""))[:30], "reason": "invalid_or_contains_payload"})
            continue
        store.append_jsonl(RUNTIME_SAMPLES_FILE, normalized)
        accepted.append(normalized)
    return {"accepted": len(accepted), "rejected": rejected, "sample_schema": "metadata_only_v1"}


def set_contract_migration(workspace_file: str | Path, migration: dict[str, Any]) -> dict[str, Any]:
    store = WorkspaceStore(workspace_file)
    key = str(migration.get("contract_key", "") or "").strip()
    if not key:
        raise ValueError("contract_key is required")
    state = str(migration.get("state", "") or "")
    if state not in {"planned", "dual_read", "dual_write", "consumer_migrated", "completed"}:
        raise ValueError("invalid migration state")
    rows = store.read_json_prefer_backend(MIGRATIONS_FILE, []) or []
    item = {"contract_key": key, "state": state, "expires_at": str(migration.get("expires_at", "") or ""), "approved_by": str(migration.get("approved_by", "") or ""), "updated_at": datetime.now(timezone.utc).isoformat()}
    rows = [row for row in rows if row.get("contract_key") != key] + [item]
    store.write_json(MIGRATIONS_FILE, rows[-200:])
    return item


def runtime_contract_compatibility(workspace_file: str | Path, contract_file: str = "", limit: int = 1000) -> dict[str, Any]:
    store = WorkspaceStore(workspace_file)
    snapshot = store.read_json_prefer_backend(CONTRACT_SNAPSHOT_FILE, {}) or {}
    diff = store.read_json_prefer_backend(CONTRACT_DIFF_FILE, {}) or {}
    samples = store.read_jsonl_prefer_backend(RUNTIME_SAMPLES_FILE, limit=limit)
    migrations = {str(row.get("contract_key", "")): row for row in store.read_json_prefer_backend(MIGRATIONS_FILE, []) or []}
    target = Path(contract_file).stem.lower() if contract_file else ""
    findings: list[dict[str, Any]] = []
    for change in diff.get("changes", []) or []:
        if change.get("severity") != "high":
            continue
        if target and target not in str(change).lower():
            continue
        key = _change_key(change)
        relevant = [sample for sample in samples if _sample_matches_change(sample, change)]
        migration = migrations.get(key, {})
        mitigated = migration.get("state") in {"dual_read", "dual_write", "consumer_migrated", "completed"}
        if relevant:
            findings.append({"contract_key": key, "status": "attention" if mitigated else "block", "change": change, "runtime_samples": len(relevant), "traffic": _traffic(relevant), "migration": migration, "reason": "active_runtime_usage_of_breaking_contract"})
        else:
            findings.append({"contract_key": key, "status": "attention", "change": change, "runtime_samples": 0, "traffic": _traffic([]), "migration": migration, "reason": "no_runtime_evidence_observed"})
    api_checks = _api_checks(snapshot, samples, target)
    mq_checks = _mq_checks(snapshot, samples, target)
    all_statuses = [item["status"] for item in findings + api_checks + mq_checks]
    status = "block" if "block" in all_statuses else "attention" if "attention" in all_statuses else "pass"
    return {"status": status, "sample_count": len(samples), "privacy": {"payload_stored": False, "allowed_fields": ["service", "path", "topic", "field_names", "success_count", "failure_count", "timestamp"]}, "breaking_runtime_findings": findings[:100], "api_checks": api_checks[:100], "mq_checks": mq_checks[:100], "migration_states": list(migrations.values())[:100], "required_actions": _actions(status, len(samples))}


def _sanitize_sample(sample: dict[str, Any], source: str) -> dict[str, Any] | None:
    kind = str(sample.get("kind", "") or "")
    if kind not in {"api", "mq"} or any(key in sample for key in {"payload", "body", "headers", "message", "content"}):
        return None
    fields = sample.get("field_names", []) or []
    if not isinstance(fields, list) or any(not isinstance(field, str) or not _FIELD_RE.fullmatch(field) for field in fields[:200]):
        return None
    result = {"kind": kind, "service": str(sample.get("service", "") or "")[:120], "path": str(sample.get("path", "") or "")[:240], "http_method": str(sample.get("http_method", "") or "")[:16], "topic": str(sample.get("topic", "") or "")[:240], "direction": str(sample.get("direction", "") or "")[:20], "dto": str(sample.get("dto", "") or "")[:120], "field_names": sorted(set(fields))[:200], "success_count": max(0, int(sample.get("success_count", 0) or 0)), "failure_count": max(0, int(sample.get("failure_count", 0) or 0)), "source": source, "observed_at": str(sample.get("observed_at", "") or datetime.now(timezone.utc).isoformat())}
    if kind == "api" and not (result["service"] and result["path"] and result["http_method"]):
        return None
    if kind == "mq" and not (result["service"] and result["topic"] and result["direction"] in {"producer", "consumer"}):
        return None
    return result


def _sample_matches_change(sample: dict[str, Any], change: dict[str, Any]) -> bool:
    subject = change.get("subject", {}) or {}
    kind = change.get("kind")
    if kind == "dto":
        return str(sample.get("dto", "")) == str(subject.get("name", "")) and (not subject.get("field") or subject.get("field") in set(sample.get("field_names", [])))
    if kind == "apis":
        return sample.get("kind") == "api" and sample.get("service") == subject.get("project") and sample.get("path") == subject.get("path") and sample.get("http_method") == subject.get("http_method")
    if kind == "mq":
        return sample.get("kind") == "mq" and sample.get("service") == subject.get("project") and sample.get("topic") == subject.get("topic")
    return False


def _api_checks(snapshot: dict[str, Any], samples: list[dict[str, Any]], target: str) -> list[dict[str, Any]]:
    endpoints = list((snapshot.get("apis", {}) or {}).values())
    checks = []
    for sample in samples:
        if sample.get("kind") != "api":
            continue
        if target and target not in str(sample).lower():
            continue
        found = any(endpoint.get("project") == sample.get("service") and endpoint.get("path") == sample.get("path") and endpoint.get("http_method") == sample.get("http_method") for endpoint in endpoints)
        failures = int(sample.get("failure_count", 0) or 0)
        successes = int(sample.get("success_count", 0) or 0)
        checks.append({"service": sample.get("service"), "path": sample.get("path"), "http_method": sample.get("http_method"), "status": "block" if not found and successes + failures > 0 else "attention" if failures > successes else "pass", "observed_calls": successes + failures, "failure_count": failures, "reason": "endpoint_removed_with_traffic" if not found else "runtime_failure_rate_high" if failures > successes else "endpoint_observed"})
    return checks


def _mq_checks(snapshot: dict[str, Any], samples: list[dict[str, Any]], target: str) -> list[dict[str, Any]]:
    topics = {str(item.get("topic", "")) for item in (snapshot.get("mq", {}) or {}).values()}
    checks = []
    for sample in samples:
        if sample.get("kind") != "mq":
            continue
        if target and target not in str(sample).lower():
            continue
        found = sample.get("topic") in topics
        checks.append({"service": sample.get("service"), "topic": sample.get("topic"), "direction": sample.get("direction"), "status": "block" if not found else "pass", "observed_calls": int(sample.get("success_count", 0) or 0) + int(sample.get("failure_count", 0) or 0), "reason": "topic_removed_with_traffic" if not found else "topic_observed"})
    return checks


def _change_key(change: dict[str, Any]) -> str:
    subject = change.get("subject", {}) or {}
    return "|".join(str(value) for value in (change.get("kind", ""), change.get("change_type", ""), subject.get("project", ""), subject.get("name", ""), subject.get("path", ""), subject.get("field", ""), subject.get("topic", "")))


def _traffic(samples: list[dict[str, Any]]) -> dict[str, int]:
    return {"success_count": sum(int(item.get("success_count", 0) or 0) for item in samples), "failure_count": sum(int(item.get("failure_count", 0) or 0) for item in samples)}


def _actions(status: str, samples: int) -> list[str]:
    if samples == 0:
        return ["尚未导入脱敏运行时样本；静态结论不能代表真实流量安全。"]
    if status == "block":
        return ["活跃运行时样本命中破坏性契约，阻断发布或启用已批准的双读/双写迁移。"]
    if status == "attention":
        return ["补充消费者样本或确认灰度迁移状态，再决定是否发布。"]
    return ["运行时样本与当前契约一致，继续执行集成与灰度验证。"]
