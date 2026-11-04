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


def test_evidence_bounded_reasoning_prompts_are_discoverable() -> None:
    prompts = (
        "clarify_change_request",
        "audit_project_claim",
        "design_minimal_validation",
        "compare_change_options",
    )
    for relative_path in ("README.md", "docs/USER_GUIDE.md", "docs/REFERENCE.md", "docs/MCP_GUIDE.md"):
        content = _read(relative_path)
        for prompt in prompts:
            assert prompt in content, f"{prompt} missing from {relative_path}"


def test_reasoning_prompt_evaluation_is_discoverable() -> None:
    for relative_path in ("README.md", "docs/USER_GUIDE.md", "docs/REFERENCE.md", "docs/MCP_GUIDE.md"):
        assert "eval-reasoning-prompts" in _read(relative_path)


def test_acceptance_validation_design_is_discoverable() -> None:
    fields = ("critical_hypothesis", "continue_if", "stop_if", "rollback", "evidence_required")
    for relative_path in ("README.md", "docs/USER_GUIDE.md", "docs/REFERENCE.md", "docs/MCP_GUIDE.md"):
        content = _read(relative_path)
        for field in fields:
            assert field in content, f"{field} missing from {relative_path}"
    assert "enforce_validation_design_contract" in _read("docs/ARCHITECTURE.md")
    reference = _read("docs/REFERENCE.md")
    for field in ("evidence_types", "evidence_observed", "evidence_missing", "evidence_complete"):
        assert field in reference
    assert "enforce_evidence_contract" in _read("docs/ARCHITECTURE.md")


def test_ontology_evolution_plan_is_discoverable_and_actionable() -> None:
    content = _read("docs/ONTOLOGY.md")
    for required in ("Assertion", "开放世界假设", "NOT_FOUND", "UNKNOWN", "STALE", "REJECTED", "generation", "实体稳定", "断言可变", "O1", "O5"):
        assert required in content
    assert "ONTOLOGY.md" in _read("README.md")
