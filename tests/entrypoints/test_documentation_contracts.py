from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_document_constitution_defines_truth_and_safety_boundaries() -> None:
    content = _read("docs/DOCUMENT_CONSTITUTION.md")
    for required in ("规范", "操作", "事实", "决策", "historical", "VERIFIED", "全图", "SQLite"):
        assert required in content


def test_evidence_subgraph_is_discoverable_from_all_public_document_layers() -> None:
    for relative_path in ("docs/USER_GUIDE.md", "docs/REFERENCE.md", "docs/MCP_GUIDE.md"):
        assert "evidence-subgraph" in _read(relative_path) or "evidence_subgraph_export" in _read(relative_path)


def test_architecture_communities_is_discoverable_from_all_public_document_layers() -> None:
    for relative_path in ("docs/REFERENCE.md", "docs/MCP_GUIDE.md", "README.md"):
        assert "architecture-communities" in _read(relative_path) or "architecture_communities" in _read(relative_path)


def test_active_plan_has_no_stale_completed_execution_sequence() -> None:
    content = _read("docs/NEXT_PHASE_MASTER_PLAN.md")
    assert "建议实施顺序" not in content
    assert "P1：Java Parser / Call Resolver 真实精度深化" in content


def test_ontology_evolution_plan_is_discoverable_and_actionable() -> None:
    content = _read("docs/ONTOLOGY_EVOLUTION_PLAN.md")
    for required in ("Assertion", "provenance_kind", "assertion_status", "开放世界假设", "双时间模型", "Action", "可信结论卡", "Phase A", "性能预算", "发布阻断条件"):
        assert required in content
    assert "ONTOLOGY_EVOLUTION_PLAN.md" in _read("docs/README.md")
