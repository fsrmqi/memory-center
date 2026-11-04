"""Contract-index enrichment isolated from hybrid retrieval orchestration."""
from __future__ import annotations

from typing import Any, Callable

from memory_center.core.knowledge.ontology import EntityValidator


def attach_contract_context(
    result: dict[str, Any], *, workspace_file: str, query: str, intent: dict[str, Any],
    effective_project: str, contract_loader: Callable[..., dict[str, Any]],
    filter_contracts: Callable[[list[dict[str, Any]], str, str], list[dict[str, Any]]],
    project_matches: Callable[[str, str], bool],
) -> dict[str, Any]:
    """Attach the legacy Feign/MQ/API/config contract payload without changing its shape."""
    primary = str(intent.get("primary_intent", "general") or "general")
    if primary not in {"feign", "mq", "endpoint", "config"}:
        return result
    contracts = contract_loader(workspace_file, project=effective_project)
    feign = filter_contracts(contracts.get("feign_contracts", []), query, primary)
    mq = filter_contracts(contracts.get("mq_contracts", []), query, primary)
    api = filter_contracts(contracts.get("api_contracts", []), query, primary)
    config = filter_contracts(contracts.get("config_contracts", []), query, primary)
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for contract in feign:
        key = (str(contract.get("interface", "")), str(contract.get("project", "")))
        if key not in seen:
            seen.add(key)
            deduped.append(contract)
    feign = deduped
    if primary == "feign" and feign:
        by_path = {str(item.get("path", "")): item for item in contracts.get("api_contracts", [])
                   if EntityValidator.validate_endpoint_path(item.get("path", ""))["is_specific"]}
        linked: list[dict[str, Any]] = []
        lowered = query.lower()
        for contract in feign:
            for method in contract.get("methods", []):
                name, path = str(method.get("method_name", "")).lower(), str(method.get("path", ""))
                if (lowered in name or name in lowered) and path in by_path:
                    candidate = {**by_path[path], "_association": "feign_method_path", "_association_confidence": 0.85}
                    if candidate not in linked:
                        linked.append(candidate)
        api = linked
    if effective_project:
        filter_project = lambda rows: [row for row in rows if project_matches(effective_project, row.get("project", ""))]
        feign, mq, api, config = map(filter_project, (feign, mq, api, config))
    result["contracts"] = {
        "feign_contracts": feign if primary not in {"mq", "config"} else [],
        "mq_contracts": mq if primary != "config" else [],
        "api_contracts": api if primary not in {"mq", "config"} else [],
        "config_contracts": config if primary != "mq" else [],
    }
    if primary in {"mq", "config"}:
        result["contract_routing"] = {"mode": "index_first", "intent": primary,
                                      "evidence_count": len(mq if primary == "mq" else config)}
    result.setdefault("retrieval_sources", []).append("contracts_index")
    return result


__all__ = ["attach_contract_context"]
