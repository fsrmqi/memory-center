"""外部 Provider 结果的统一临时证据契约。"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_MAX_EVIDENCE_REFS = 20
_MAX_CLAIM_VALUE = 256


def build_external_evidence_ref(
    provider: str,
    root: str | Path,
    result: dict[str, Any],
    *,
    provenance_kind: str = "EXTRACTED",
) -> dict[str, Any]:
    """将外部结果压缩为不含正文的会话级 EvidenceRef。"""
    scope = result.get("scope_checked", {})
    operation = str(result.get("operation", "lookup") or "lookup")
    fingerprint = hashlib.sha256(
        json.dumps(
            {
                "provider": provider,
                "root": str(Path(root).expanduser().resolve()),
                "operation": operation,
                "scope": scope,
                "output": str(result.get("output", "") or ""),
            },
            ensure_ascii=True,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()[:20]
    return {
        "schema_version": 1,
        "ref_id": f"evidence:external:{provider}:{fingerprint}",
        "provider": provider,
        "provenance_kind": provenance_kind,
        "relation_mode": "external_read_only",
        "scope_checked": scope if isinstance(scope, dict) else {},
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "duration_ms": float(result.get("duration_ms", 0.0) or 0.0),
        "content_sha256": hashlib.sha256(str(result.get("output", "") or "").encode("utf-8")).hexdigest(),
        "persistence": "session_ephemeral",
        "verification_status": "UNVERIFIED",
        "claim": _normalized_claim(result.get("claim")),
    }


def fuse_external_evidence_refs(evidence_refs: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> dict[str, Any]:
    """融合脱敏外部 EvidenceRef；只有显式结构化 Claim 才能形成一致或冲突结论。"""
    accepted = [item for item in evidence_refs[:_MAX_EVIDENCE_REFS] if _valid_evidence_ref(item)]
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    unclassified: list[str] = []
    for evidence in accepted:
        claim = _normalized_claim(evidence.get("claim"))
        if claim is None:
            unclassified.append(str(evidence.get("ref_id", "")))
            continue
        groups.setdefault((claim["subject"], claim["predicate"]), []).append({"evidence": evidence, "claim": claim})

    claims: list[dict[str, Any]] = []
    conflict_cards: list[dict[str, Any]] = []
    for (subject, predicate), rows in sorted(groups.items()):
        providers = sorted({str(row["evidence"].get("provider", "")) for row in rows if row["evidence"].get("provider")})
        values = sorted({row["claim"]["value"] for row in rows})
        ref_ids = sorted({str(row["evidence"].get("ref_id", "")) for row in rows if row["evidence"].get("ref_id")})
        status = "INSUFFICIENT_EVIDENCE" if len(providers) < 2 else "CONSISTENT" if len(values) == 1 else "CONFLICT"
        claim_row = {
            "subject": subject,
            "predicate": predicate,
            "values": values,
            "providers": providers,
            "evidence_refs": ref_ids,
            "status": status,
        }
        claims.append(claim_row)
        if status == "CONFLICT":
            fingerprint = hashlib.sha256(f"{subject}|{predicate}".encode()).hexdigest()[:12]
            conflict_cards.append({
                "action_id": f"verify-provider-conflict-{fingerprint}",
                "action": "verify_conflict",
                "mode": "read_only",
                "requires_confirmation": False,
                "subject": subject,
                "predicate": predicate,
                "evidence_refs": ref_ids,
                "reason": "多个 Provider 对同一结构化 Claim 返回不同值；不得自动选择其中一方。",
                "stop_condition": "补充人工、测试或运行时验证证据后，Claim 仅剩一个可验证值。",
            })

    statuses = {item["status"] for item in claims}
    overall = "CONFLICT" if "CONFLICT" in statuses else "CONSISTENT" if "CONSISTENT" in statuses and not unclassified else "INSUFFICIENT_EVIDENCE"
    return {
        "schema_version": 1,
        "overall_status": overall,
        "claims": claims,
        "unclassified_evidence_refs": unclassified,
        "action_cards": conflict_cards,
        "scope": {"evidence_count": len(accepted), "claim_count": len(claims), "max_evidence_count": _MAX_EVIDENCE_REFS},
        "next_action": _fusion_next_action(overall, bool(unclassified)),
    }


def _normalized_claim(value: Any) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    normalized = {key: str(value.get(key, "") or "").strip()[:_MAX_CLAIM_VALUE] for key in ("subject", "predicate", "value")}
    return normalized if all(normalized.values()) else None


def _valid_evidence_ref(value: Any) -> bool:
    if not isinstance(value, dict) or not str(value.get("ref_id", "") or "").startswith("evidence:"):
        return False
    return not any(key in value for key in ("output", "content", "text", "payload", "body"))


def _fusion_next_action(overall: str, has_unclassified: bool) -> str:
    if overall == "CONFLICT":
        return "存在 Provider 冲突；先执行返回的 verify_conflict Action，不能将任一结果提升为 VERIFIED。"
    if overall == "CONSISTENT":
        return "多个 Provider 的结构化 Claim 一致；仍需独立验证证据后才能提升为 VERIFIED。"
    if has_unclassified:
        return "部分 EvidenceRef 缺少结构化 Claim；保留为来源线索，不要将不同正文哈希误判为冲突。"
    return "证据数量或独立 Provider 不足；补充另一来源、测试、运行时或人工验证。"
