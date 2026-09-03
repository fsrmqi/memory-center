"""Deterministic behavior-contract replay for the public hybrid lookup envelope."""
from __future__ import annotations

import hashlib
import json
import ast
from pathlib import Path
from typing import Any, Callable

import yaml

SCHEMA_VERSION = 1


def load_lookup_contract_cases(path: str | Path) -> list[dict[str, Any]]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict) or raw.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("lookup contract cases require schema_version=1")
    cases = raw.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("lookup contract cases require non-empty cases")
    normalized: list[dict[str, Any]] = []
    ids: set[str] = set()
    for item in cases:
        if not isinstance(item, dict):
            raise ValueError("lookup contract case must be an object")
        case_id, query = str(item.get("case_id", "")).strip(), str(item.get("query", "")).strip()
        if not case_id or not query or case_id in ids:
            raise ValueError("lookup contract case_id/query must be unique and non-empty")
        ids.add(case_id)
        normalized.append({"case_id": case_id, "query": query, "project": str(item.get("project", "")).strip(), "limit": int(item.get("limit", 10) or 10), "session_steps": max(1, int(item.get("session_steps", 1) or 1))})
    return normalized


def summarize_lookup_contract_coverage(cases_file: str | Path) -> dict[str, Any]:
    """Return only logical coverage counts; never return query text or paths."""
    cases = load_lookup_contract_cases(cases_file)
    categories = {"general": 0, "project": 0, "session": 0, "contract_like": 0}
    for case in cases:
        text = case["query"].lower()
        categories["general"] += 1
        categories["project"] += int(bool(case["project"]))
        categories["session"] += int(case["session_steps"] > 1)
        categories["contract_like"] += int(any(token in text for token in ("feign", "mq", "config", "endpoint")))
    return {"case_count": len(cases), "categories": categories}


def normalize_lookup_contract(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep stable, non-path-bearing response semantics for regression comparison."""
    results = []
    for item in (payload.get("results", []) or [])[:10]:
        node = item.get("node", {}) if isinstance(item, dict) else {}
        results.append({"id": str(node.get("id", "")), "type": str(node.get("type", "")), "project": str(node.get("project", ""))})
    contracts = payload.get("contracts", {}) if isinstance(payload.get("contracts"), dict) else {}
    steps = payload.get("agent_next_steps", []) or []
    return {
        "result_ids": results,
        "project_scope": {key: str((payload.get("project_scope", {}) or {}).get(key, "")) for key in ("requested", "effective", "source")},
        "intent": str((payload.get("intent_analysis", {}) or {}).get("primary_intent", "")),
        "contract_counts": {key: len(value) for key, value in contracts.items() if isinstance(value, list)},
        "contract_routing": {key: str(value) for key, value in (payload.get("contract_routing", {}) or {}).items() if key in {"mode", "intent", "evidence_count"}},
        "knowledge_state": str((payload.get("knowledge_state", {}) or {}).get("state", "")),
        "guidance_actions": [str(step.get("action", "")) for step in steps if isinstance(step, dict)][:8],
        "served_dedup": bool((payload.get("served_dedup", {}) or {}).get("applied", False)),
    }


def normalize_facade_lookup_contract(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize CLI/HTTP/MCP wrapper shapes to the common lookup contract."""
    candidate = payload.get("result") if isinstance(payload.get("result"), dict) else payload
    return normalize_lookup_contract(candidate if isinstance(candidate, dict) else {})


def evaluate_lookup_facade_contract(
    cases: list[dict[str, Any]], runners: dict[str, Callable[[dict[str, Any]], dict[str, Any]]],
) -> dict[str, Any]:
    """Compare the semantic contract returned by injected CLI/HTTP/MCP facade runners.

    Transport bootstrapping stays outside this pure evaluator so tests can use
    real route adapters without opening ports or requiring a live MCP process.
    """
    snapshots = {}
    session_failures = []
    for case in cases:
        values = {}
        for name, run in runners.items():
            scoped = {**case, "session_id": f"lookup-contract:{case['case_id']}:{name}"}
            replies = [normalize_facade_lookup_contract(run(scoped)) for _ in range(case.get("session_steps", 1))]
            values[name] = replies[-1] if len(replies) == 1 else {"first": replies[0], "repeat": replies[-1]}
            if len(replies) > 1 and not replies[-1]["served_dedup"]:
                session_failures.append(case["case_id"])
        snapshots[case["case_id"]] = values
    mismatches = []
    for case_id, values in snapshots.items():
        canonical = next(iter(values.values()), None)
        if any(value != canonical for value in values.values()):
            mismatches.append(case_id)
    return {"case_count": len(cases), "facades": sorted(runners), "snapshots": snapshots,
            "mismatched_case_ids": mismatches, "session_failure_case_ids": sorted(set(session_failures)), "status": "block" if mismatches or session_failures else "pass"}


def evaluate_live_lookup_facades(workspace_file: str | Path, cases_file: str | Path, *, baseline_file: str | Path | None = None) -> dict[str, Any]:
    """Run the in-process CLI, HTTP and MCP query adapters without opening ports."""
    from typer.testing import CliRunner
    from memory_center.cli.main import app
    from memory_center.http.server import _route_request
    from memory_center.mcp.server import create_server

    workspace = str(workspace_file)
    server = create_server(workspace)
    mcp_lookup = server._tool_manager._tools["mc_lookup"].fn

    def cli(case: dict[str, Any]) -> dict[str, Any]:
        args = ["query", "--workspace", workspace, "--text", case["query"], "--limit", str(case["limit"])]
        if case["project"]:
            args += ["--project", case["project"]]
        if case.get("session_id"):
            args += ["--session-id", case["session_id"]]
        output = CliRunner().invoke(app, args)
        if output.exit_code != 0:
            raise RuntimeError(output.output)
        return ast.literal_eval(output.output.strip())

    def http(case: dict[str, Any]) -> dict[str, Any]:
        params = {"workspace": [workspace], "text": [case["query"]], "limit": [str(case["limit"])]}
        if case["project"]:
            params["project"] = [case["project"]]
        if case.get("session_id"):
            params["session_id"] = [case["session_id"]]
        return _route_request("/workspace/query", params, None)

    def mcp(case: dict[str, Any]) -> dict[str, Any]:
        return mcp_lookup(query=case["query"], mode="query", limit=case["limit"], project=case["project"], session_id=case.get("session_id", ""))

    result = evaluate_lookup_facade_contract(load_lookup_contract_cases(cases_file), {"cli": cli, "http": http, "mcp": mcp})
    baseline = _load_facade_baseline(baseline_file) if baseline_file else None
    changed = [case_id for case_id, value in result["snapshots"].items() if baseline and baseline.get("snapshots", {}).get(case_id) != value]
    result.update({"baseline_status": "compared" if baseline else "no_baseline", "changed_case_ids": changed})
    if changed:
        result["status"] = "block"
    return result


def save_lookup_facade_baseline(result: dict[str, Any], path: str | Path, *, label: str = "current") -> dict[str, Any]:
    payload = {"schema_version": SCHEMA_VERSION, "label": label, "snapshots": result.get("snapshots", {})}
    target = Path(path); target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"saved": True, "baseline_file": str(target)}


def evaluate_lookup_contract(
    workspace_file: str | Path, cases_file: str | Path, *, baseline_file: str | Path | None = None,
    runner: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    cases = load_lookup_contract_cases(cases_file)
    if runner is None:
        from memory_center.core.orchestrator.query import memory_query_hybrid

        runner = lambda case: memory_query_hybrid(workspace_file, case["query"], limit=case["limit"], project=case["project"])
    current = {case["case_id"]: normalize_lookup_contract(runner(case)) for case in cases}
    baseline = _load_baseline(baseline_file) if baseline_file else None
    changed = []
    if baseline:
        expected = baseline.get("contracts", {})
        changed = [case_id for case_id, contract in current.items() if expected.get(case_id) != contract]
    return {
        "schema_version": SCHEMA_VERSION, "case_count": len(cases), "contracts": current,
        "baseline_status": "compared" if baseline else "no_baseline", "changed_case_ids": changed,
        "status": "block" if changed else "pass", "next_action": "save an approved baseline explicitly" if not baseline else "review changed_case_ids",
    }


def save_lookup_contract_baseline(result: dict[str, Any], path: str | Path, *, label: str = "current") -> dict[str, Any]:
    payload = {"schema_version": SCHEMA_VERSION, "label": label, "contracts": result.get("contracts", {})}
    payload["sha256"] = hashlib.sha256(json.dumps(payload["contracts"], ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"saved": True, "baseline_file": str(target), "sha256": payload["sha256"]}


def _load_baseline(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION or not isinstance(value.get("contracts"), dict):
        raise ValueError("lookup contract baseline must be schema_version=1")
    return value


def _load_facade_baseline(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION or not isinstance(value.get("snapshots"), dict):
        raise ValueError("lookup facade baseline must be schema_version=1")
    return value


__all__ = ["evaluate_live_lookup_facades", "evaluate_lookup_contract", "evaluate_lookup_facade_contract", "load_lookup_contract_cases", "normalize_lookup_contract", "normalize_facade_lookup_contract", "save_lookup_contract_baseline", "save_lookup_facade_baseline", "summarize_lookup_contract_coverage"]
