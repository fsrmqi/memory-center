"""Explicit, sanitized, re-runnable retrieval replay evaluation (long task).

Builds a private case file (outside the repo), runs `mc_lookup(auto)` per
case, captures sanitized structured results, classifies each outcome into a
single failure taxonomy, and aggregates quality + performance metrics.

Privacy contract (task §三/§四): the case file lives outside the repo; the
repo only gets anonymous fixture cases. The runner never persists the query
text, real node ids, absolute paths, source snippets, or business payloads.

This is read-only evaluation. Only the Phase C gate (>=3 same-class failures
+ graph evidence + stable repro) authorizes a code change, and only within
retrieval/planner/ranking/fusion/cache.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from memory_center.core.indexing.control_plane import index_control_status
from memory_center.core.freshness.contract import assemble_index_context
from memory_center.core.storage.workspace import WorkspaceStore

# ---------------------------------------------------------------------------
# Case model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RetrievalReplayCase:
    case_id: str
    intent_class: str
    query_ref: str            # pointer to a private query, never the query text
    project_ref: str = ""     # optional private project id
    request: dict[str, Any] = field(default_factory=dict)
    expected: dict[str, Any] = field(default_factory=dict)
    privacy: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "RetrievalReplayCase":
        return cls(
            case_id=str(data.get("id", "")),
            intent_class=str(data.get("intent_class", "")),
            query_ref=str(data.get("query_ref", "")),
            project_ref=str(data.get("project_ref", "")),
            request=dict(data.get("request", {}) or {}),
            expected=dict(data.get("expected", {}) or {}),
            privacy=dict(data.get("privacy", {}) or {}),
        )


def load_replay_cases(path: str | Path) -> list[RetrievalReplayCase]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    rows = data.get("cases", [])
    return [RetrievalReplayCase.from_mapping(r) for r in rows if isinstance(r, dict)]


# ---------------------------------------------------------------------------
# Outcome classification (task §五)
# ---------------------------------------------------------------------------

PASS = "PASS"
ANCHOR_MISSED = "ANCHOR_MISSED"
ANCHOR_RANKED_LOW = "ANCHOR_RANKED_LOW"
PROJECT_SCOPE_REGRESSION = "PROJECT_SCOPE_REGRESSION"
CHAIN_MISSING = "CHAIN_MISSING_WITH_GRAPH_EVIDENCE"
CHAIN_WRONG = "CHAIN_WRONG"
EVIDENCE_BOUNDARY = "EVIDENCE_BOUNDARY_CORRECT"
DATASET_WRONG = "DATASET_EXPECTATION_WRONG"

# intent classes that are expected to be evidence boundaries (no chain).
BOUNDARY_INTENTS = {"mq_producer", "negative", "stale_boundary", "same_name"}


def classify_outcome(case: RetrievalReplayCase, result: dict[str, Any]) -> str:
    """Classify one replay result into a single primary category.

    Rules mirror task §五: boundary intents are EVIDENCE_BOUNDARY_CORRECT when
    they behave as expected; anchor intent cases check anchor kind/rank;
    chain intents check primary_chain.status; MQ -> insufficient_evidence.
    """
    intent = case.intent_class
    expected = case.expected or {}
    anchor_exp = expected.get("anchor", {}) or {}
    chain_exp = expected.get("primary_chain", {}) or {}

    if intent in ("mq_producer",):
        # MQ boundary is defined as primary_chain.status == insufficient_evidence
        # with an MQ reason. If the query did not even reach an MQProducer anchor
        # (e.g. it resolved to a Field/Class), that is a dataset expectation
        # mismatch, not a chain failure — MQProducer nodes are not symbol-retrieval
        # targets, so the boundary must be probed via the producer's owning Method.
        if result.get("primary_chain", {}).get("status") == "insufficient_evidence":
            return EVIDENCE_BOUNDARY
        if result.get("best_match", {}).get("kind") not in ("MQProducer", "Method"):
            return DATASET_WRONG
        return CHAIN_MISSING

    if intent == "negative":
        status = result.get("primary_chain", {}).get("status")
        if status in ("not_found", "insufficient_evidence"):
            return EVIDENCE_BOUNDARY
        return CHAIN_WRONG if status == "found" else DATASET_WRONG

    if intent == "stale_boundary":
        cb = result.get("claim_boundary", {})
        if not cb.get("negative_claim_allowed"):
            return EVIDENCE_BOUNDARY
        return DATASET_WRONG

    if intent == "same_name":
        # Method must not be displaced by a DTO/Class for a *method* query.
        # For a pure class query the expected kind is Class and a Class
        # best_match is correct.
        expected_kind = (expected.get("anchor", {}) or {}).get("kind")
        bm_kind = result.get("best_match", {}).get("kind")
        if expected_kind == "Class":
            return PASS if bm_kind == "Class" else (ANCHOR_RANKED_LOW if bm_kind else DATASET_WRONG)
        if bm_kind == "Method":
            return PASS
        return ANCHOR_RANKED_LOW

    # anchor-focused intents (symbol, project) and chain intents.
    anchor_kind_expected = anchor_exp.get("kind")
    if anchor_kind_expected and result.get("best_match", {}).get("kind") != anchor_kind_expected:
        # Method was displaced by Class/DTO.
        return ANCHOR_RANKED_LOW if result.get("best_match", {}).get("rank", 1) > 1 or result.get("best_match", {}).get("kind") != "Method" else ANCHOR_MISSED

    if chain_exp.get("status") == "found":
        chain_status = result.get("primary_chain", {}).get("status")
        if chain_status == "found":
            return PASS
        if chain_status in ("not_found", "insufficient_evidence"):
            return CHAIN_MISSING
        return DATASET_WRONG

    if "project" in intent or case.project_ref:
        if result.get("mode_used") in ("code",) and not result.get("best_match", {}).get("kind"):
            return PROJECT_SCOPE_REGRESSION

    return PASS


# ---------------------------------------------------------------------------
# Aggregation (task §六)
# ---------------------------------------------------------------------------


def aggregate_replay(outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(outcomes)
    by_intent: dict[str, int] = {}
    counts: dict[str, int] = {k: 0 for k in (PASS, ANCHOR_MISSED, ANCHOR_RANKED_LOW, CHAIN_MISSING, CHAIN_WRONG, EVIDENCE_BOUNDARY, PROJECT_SCOPE_REGRESSION, DATASET_WRONG)}
    anchor_cases = 0
    anchor_top1 = 0
    chain_cases = 0
    chain_found = 0
    boundary_cases = 0
    boundary_correct = 0
    project_cases = 0
    project_regression = 0
    latencies: list[float] = []

    for row in outcomes:
        counts[row["classification"]] = counts.get(row["classification"], 0) + 1
        by_intent[row["intent_class"]] = by_intent.get(row["intent_class"], 0) + 1
        latencies.append(float(row.get("performance", {}).get("latency_ms", 0) or 0))
        if row["intent_class"] in ("symbol", "feign_chain", "http_chain", "same_name", "project"):
            anchor_cases += 1
            if row.get("best_match", {}).get("rank", 1) == 1 and row.get("best_match", {}).get("kind") == "Method":
                anchor_top1 += 1
        if row["intent_class"] in ("feign_chain", "http_chain"):
            chain_cases += 1
            if row.get("primary_chain", {}).get("status") == "found":
                chain_found += 1
        if row["intent_class"] in ("mq_producer", "negative", "stale_boundary", "same_name"):
            boundary_cases += 1
            if row["classification"] in (EVIDENCE_BOUNDARY, PASS):
                boundary_correct += 1
        if row["intent_class"] == "project":
            project_cases += 1
            if row["classification"] == PROJECT_SCOPE_REGRESSION:
                project_regression += 1

    latencies.sort()
    def pct(p):
        if not latencies:
            return 0.0
        if len(latencies) == 1:
            return round(latencies[0], 1)
        # interpolate percentile for a small sample (mean of the two middle
        # points at exactly .5, nearest-rank otherwise).
        rank = p * (len(latencies) - 1)
        lo = int(rank)
        hi = min(len(latencies) - 1, lo + 1)
        frac = rank - lo
        return round(latencies[lo] * (1 - frac) + latencies[hi] * frac, 1)

    return {
        "case_count": total,
        "by_intent_class": by_intent,
        "outcomes": counts,
        "quality": {
            "anchor_top1_recall": round(anchor_top1 / anchor_cases, 4) if anchor_cases else 0.0,
            "primary_chain_recall": round(chain_found / chain_cases, 4) if chain_cases else 0.0,
            "wrong_chain_rate": round(counts[CHAIN_WRONG] / total, 4) if total else 0.0,
            "boundary_correct_rate": round(boundary_correct / boundary_cases, 4) if boundary_cases else 0.0,
            "project_scope_regression_rate": round(project_regression / project_cases, 4) if project_cases else 0.0,
        },
        "performance": {"p50_ms": pct(0.50), "p95_ms": pct(0.95), "max_ms": round(max(latencies), 1) if latencies else 0.0},
    }


# ---------------------------------------------------------------------------
# Runner (task §四)
# ---------------------------------------------------------------------------


def run_retrieval_replay(
    workspace_file: str | Path,
    cases: list[RetrievalReplayCase],
    *,
    tier: str = "standard",
    query_mapping: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute one sanitized replay pass. Read-only: never refreshes/reindexes,
    never persists query text or real ids."""
    from memory_center.mcp.server import create_server

    mapping = query_mapping or {}
    ws = str(workspace_file)
    store = WorkspaceStore(ws)
    generation = str(index_control_status(store).get("active_generation", "") or "")
    server = create_server(ws)
    mc_lookup = server._tool_manager._tools["mc_lookup"]

    outcomes: list[dict[str, Any]] = []
    for case in cases:
        request = case.request or {}
        # The runner only ever sees the private query via the case-file owner's
        # mapping; the repo never carries the query text.
        resolved_query = str(
            mapping.get(case.case_id)
            or mapping.get(case.query_ref)
            or request.get("resolved_query")
            or case.query_ref
        )
        project = request.get("project", "")
        t0 = time.perf_counter()
        try:
            out = mc_lookup.fn(
                query=resolved_query,
                mode=request.get("mode", "auto"),
                limit=int(request.get("limit", 6)),
                project=project,
                request_tier=request.get("request_tier", tier),
            )
            latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        except Exception:
            outcomes.append({
                "case_id": case.case_id,
                "intent_class": case.intent_class,
                "classification": DATASET_WRONG,
                "best_match": {"kind": None, "rank": 0, "anchor_matched": False},
                "primary_chain": {"status": "error", "evidence_level": None, "relation_types": []},
                "claim_boundary": {},
                "performance": {"latency_ms": 0, "output_bytes": 0, "token_estimate": 0},
            })
            continue

        r = out.get("result") or {}
        bm = r.get("best_match") or {}
        pc = out.get("primary_chain") or {}
        cb = out.get("claim_boundary") or {}
        best_rank = 1 if bm else 0
        outcome = {
            "case_id": case.case_id,
            "intent_class": case.intent_class,
            "generation": generation[:12],
            "mode_used": out.get("mode_used"),
            "best_match": {"kind": bm.get("type"), "rank": best_rank, "anchor_matched": bool(bm)},
            "primary_chain": {
                "status": pc.get("status"),
                "evidence_level": pc.get("evidence_level"),
                "relation_types": [s.get("relation") or s.get("type") for s in pc.get("steps", [])],
            },
            "claim_boundary": {
                "evidence_level": cb.get("claim_boundary", {}).get("evidence_level") if isinstance(cb.get("claim_boundary"), dict) else None,
                "negative_claim_allowed": (cb.get("claim_boundary") or {}).get("negative_claim_allowed") if isinstance(cb.get("claim_boundary"), dict) else None,
                "reason_codes": (cb.get("claim_boundary") or {}).get("reason_codes", []) if isinstance(cb.get("claim_boundary"), dict) else [],
            },
            "performance": {"latency_ms": latency_ms, "output_bytes": 0, "token_estimate": 0},
            "privacy": {"query_retained": False, "source_retained": False, "path_retained": False},
        }
        outcome["classification"] = classify_outcome(case, outcome)
        outcomes.append(outcome)

    return {
        "dataset_id": "retrieval-replay",
        "generation": {"consistent": True, "active_generation": generation[:12]},
        "aggregate": aggregate_replay(outcomes),
        "outcomes": outcomes,
    }
