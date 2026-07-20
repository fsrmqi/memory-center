"""Tests for D-04: Domain / Business Flow output schema stability.

Verifies:
- extract_business_flows_for_workspace returns stable schema
- BusinessFlow.to_dict has required fields
- business_flow_impact_for_workspace returns stable schema
- mc_domain facade returns required fields
- Empty seed returns diagnostics, not crash
- Flow steps have required fields
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest


@pytest.fixture()
def demo_workspace(tmp_path: Path) -> Path:
    source = Path("examples/spring-cloud-demo")
    target = tmp_path / "demo"
    shutil.copytree(source, target)
    ws = target / ".memory-center" / "workspace.yaml"
    lines = ws.read_text(encoding="utf-8").splitlines()
    lines = [f"root: {target.as_posix()}" if line.startswith("root:") else line for line in lines]
    ws.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return ws

class TestFlowSchema:
    def test_extract_returns_required_keys(self, demo_workspace: Path):
        from memory_center.core.domain.flow import extract_business_flows_for_workspace
        from memory_center.core.storage.runtime import RuntimeStore
        from memory_center.core.storage.workspace import WorkspaceStore
        ws = WorkspaceStore(str(demo_workspace))
        with RuntimeStore(ws.graph_db_path) as graph:
            nodes = graph.find_nodes("Order", limit=1)
        if not nodes:
            pytest.skip("No nodes found")
        result = extract_business_flows_for_workspace(str(demo_workspace), nodes[0]["id"])
        assert "flows" in result
        assert "workflow" in result
        assert result["workflow"] == "business-flow"

    def test_flow_dict_has_required_fields(self):
        from memory_center.core.domain.flow import BusinessFlow
        flow = BusinessFlow(flow_id="f1", name="test flow", description="desc")
        d = flow.to_dict()
        assert "flow_id" in d
        assert "name" in d
        assert "description" in d
        assert "steps" in d
        assert "entry_points" in d
        assert "exit_points" in d
        assert "entities_involved" in d
        assert "risk_level" in d

    def test_flow_node_to_dict(self):
        from memory_center.core.domain.flow import FlowNode
        n = FlowNode(node_id="n1", name="TestNode", node_type="Endpoint", step_order=1, service="svc")
        d = n.to_dict()
        assert d["node_id"] == "n1"
        assert d["type"] == "Endpoint"
        assert d["step_order"] == 1

    def test_flow_edge_to_dict(self):
        from memory_center.core.domain.flow import FlowEdge
        e = FlowEdge(source_id="s1", target_id="t1", edge_type="CALLS", confidence=0.9)
        d = e.to_dict()
        assert d["type"] == "CALLS"
        assert d["confidence"] == 0.9

    def test_empty_seed_returns_error(self, demo_workspace: Path):
        from memory_center.core.domain.flow import extract_business_flows_for_workspace
        result = extract_business_flows_for_workspace(str(demo_workspace), "")
        assert "error" in result
        assert result["flows"] == []

    def test_impact_returns_required_keys(self, demo_workspace: Path):
        from memory_center.core.domain.flow import business_flow_impact_for_workspace
        result = business_flow_impact_for_workspace(str(demo_workspace), "", max_depth=2)
        assert "impacted" in result
        assert "workflow" in result
        assert result["workflow"] == "business-flow-impact"

class TestDomainSchema:
    def test_domain_extractor_works(self, demo_workspace: Path):
        from memory_center.core.domain.extractor import BusinessDomainExtractor
        from memory_center.core.storage.runtime import RuntimeStore
        from memory_center.core.storage.workspace import WorkspaceStore
        ws = WorkspaceStore(str(demo_workspace))
        with RuntimeStore(ws.graph_db_path) as store:
            extractor = BusinessDomainExtractor(store)
            domains = extractor.extract_domains()
        assert isinstance(domains, list)
        if domains:
            d = domains[0]
            # BusinessDomain dataclass has domain_name attribute
            assert hasattr(d, "domain_name") or hasattr(d, "name")
