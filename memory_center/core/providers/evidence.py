"""外部 Provider 结果的统一临时证据契约。"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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
    }
