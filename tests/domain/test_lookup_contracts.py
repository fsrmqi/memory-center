"""Contract enrichment remains independently testable after lookup split."""
from __future__ import annotations

from memory_center.core.orchestrator.lookup_contracts import attach_contract_context


def _filter(rows, query, _intent):
    return [row for row in rows if query.lower() in str(row).lower()]


def test_feign_contract_enrichment_dedupes_and_links_specific_api() -> None:
    contracts = {
        "feign_contracts": [
            {"interface": "OrderFeign", "project": "a", "methods": [{"method_name": "findOrder", "path": "/api/orders"}]},
            {"interface": "OrderFeign", "project": "a", "methods": [{"method_name": "findOrder", "path": "/api/orders"}]},
        ],
        "mq_contracts": [],
        "api_contracts": [{"project": "a", "path": "/api/orders", "name": "OrderApi"}],
        "config_contracts": [],
    }
    result = attach_contract_context(
        {}, workspace_file="workspace.yaml", query="findOrder", intent={"primary_intent": "feign"},
        effective_project="a", contract_loader=lambda *_args, **_kwargs: contracts,
        filter_contracts=_filter, project_matches=lambda expected, actual: expected == actual,
    )
    assert len(result["contracts"]["feign_contracts"]) == 1
    assert result["contracts"]["api_contracts"][0]["_association"] == "feign_method_path"
    assert "contracts_index" in result["retrieval_sources"]


def test_mq_contract_enrichment_uses_index_first_routing() -> None:
    contracts = {"feign_contracts": [], "mq_contracts": [{"project": "a", "topic": "orders"}], "api_contracts": [], "config_contracts": []}
    result = attach_contract_context(
        {}, workspace_file="workspace.yaml", query="orders", intent={"primary_intent": "mq"},
        effective_project="", contract_loader=lambda *_args, **_kwargs: contracts,
        filter_contracts=_filter, project_matches=lambda expected, actual: expected == actual,
    )
    assert result["contract_routing"] == {"mode": "index_first", "intent": "mq", "evidence_count": 1}
    assert result["contracts"]["feign_contracts"] == []
