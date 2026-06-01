"""Completion audit — documentation alignment and governance.

This module implements Phase E of NEXT_PHASE_MASTER_PLAN:
- Regular completion audits per work package
- Sync docs after each capability enhancement
- Separate design choices from real bugs
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from ..store import WorkspaceStore

AUDIT_LOG_FILE = "completion-audit.jsonl"
DESIGN_DECISIONS_FILE = "design-decisions.jsonl"


def run_completion_audit(
    workspace_file: str | Path,
    work_package: str = "",
    check_docs: bool = True,
    check_tests: bool = True,
    check_implementation: bool = True,
) -> Dict[str, Any]:
    """Run completion audit for a work package or overall project.

    Checks:
    1. Documentation alignment
    2. Test coverage
    3. Implementation completeness
    4. Design decision consistency
    """
    store = WorkspaceStore(workspace_file)
    findings: List[Dict[str, Any]] = []
    score = 100

    # Check documentation
    if check_docs:
        doc_findings = _check_documentation_alignment(workspace_file, work_package)
        findings.extend(doc_findings)
        score -= len(doc_findings) * 5

    # Check test coverage
    if check_tests:
        test_findings = _check_test_coverage(workspace_file, work_package)
        findings.extend(test_findings)
        score -= len(test_findings) * 8

    # Check implementation completeness
    if check_implementation:
        impl_findings = _check_implementation_completeness(workspace_file, work_package)
        findings.extend(impl_findings)
        score -= len(impl_findings) * 10

    # Check design decisions
    design_findings = _check_design_decisions(workspace_file, work_package)
    findings.extend(design_findings)
    score -= len(design_findings) * 3

    score = max(0, min(100, score))

    # Record audit
    audit_record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "work_package": work_package,
        "score": score,
        "quality": _score_to_quality(score),
        "finding_count": len(findings),
        "categories": _categorize_findings(findings),
    }
    store.append_jsonl(AUDIT_LOG_FILE, audit_record)

    return {
        "score": score,
        "quality": _score_to_quality(score),
        "findings": findings,
        "summary": _build_audit_summary(findings),
        "recommendations": _generate_audit_recommendations(findings),
        "recorded": True,
    }


def _check_documentation_alignment(
    workspace_file: str | Path,
    work_package: str,
) -> List[Dict[str, Any]]:
    """Check if documentation aligns with implementation."""
    findings = []
    workspace_path = Path(workspace_file).parent

    # Check for key documentation files
    key_docs = [
        "README.md",
        "docs/MCP_GUIDE.md",
        "docs/USER_GUIDE.md",
        "docs/ARCHITECTURE.md",
        "docs/SPECIAL_NOTES.md",
    ]

    for doc in key_docs:
        doc_path = workspace_path / doc
        if not doc_path.exists():
            findings.append({
                "category": "documentation",
                "severity": "medium",
                "code": "missing_doc",
                "message": f"缺少文档: {doc}",
                "file": doc,
            })

    # Check if SPECIAL_NOTES covers known design decisions
    special_notes_path = workspace_path / "docs" / "SPECIAL_NOTES.md"
    if special_notes_path.exists():
        content = special_notes_path.read_text()
        required_topics = [
            "user_prompt_submit",
            "mode 与 enabled 的关系",
            "facade 与原子能力",
        ]
        for topic in required_topics:
            if topic not in content:
                findings.append({
                    "category": "documentation",
                    "severity": "low",
                    "code": "incomplete_special_notes",
                    "message": f"SPECIAL_NOTES 缺少主题: {topic}",
                })

    return findings


def _check_test_coverage(
    workspace_file: str | Path,
    work_package: str,
) -> List[Dict[str, Any]]:
    """Check test coverage for the work package."""
    findings = []
    workspace_path = Path(workspace_file).parent

    # Check for test files
    test_dirs = [
        "tests",
        "test",
    ]

    has_tests = False
    for test_dir in test_dirs:
        test_path = workspace_path / test_dir
        if test_path.exists() and any(test_path.glob("**/*.py")):
            has_tests = True
            break

    if not has_tests:
        findings.append({
            "category": "testing",
            "severity": "high",
            "code": "no_tests",
            "message": "未找到测试文件",
        })

    # Check for pytest configuration
    pytest_files = [
        "pytest.ini",
        "pyproject.toml",
        "setup.cfg",
    ]

    has_pytest_config = False
    for pytest_file in pytest_files:
        pytest_path = workspace_path / pytest_file
        if pytest_path.exists():
            content = pytest_path.read_text()
            if "[tool.pytest" in content or "[pytest]" in content:
                has_pytest_config = True
                break

    if not has_pytest_config:
        findings.append({
            "category": "testing",
            "severity": "low",
            "code": "no_pytest_config",
            "message": "未找到 pytest 配置",
        })

    return findings


def _check_implementation_completeness(
    workspace_file: str | Path,
    work_package: str,
) -> List[Dict[str, Any]]:
    """Check if implementation matches the work package requirements."""
    findings = []

    # Check for the new modules we created
    workspace_path = Path(workspace_file).parent.parent  # Go up to memory-center root

    required_modules = [
        "memory_center/core/retrieval/__init__.py",
        "memory_center/core/benchmark/__init__.py",
        "memory_center/core/backend/__init__.py",
        "memory_center/core/navigation/__init__.py",
    ]

    for module in required_modules:
        module_path = workspace_path / module
        if not module_path.exists():
            findings.append({
                "category": "implementation",
                "severity": "high",
                "code": "missing_module",
                "message": f"缺少模块: {module}",
                "file": module,
            })

    return findings


def _check_design_decisions(
    workspace_file: str | Path,
    work_package: str,
) -> List[Dict[str, Any]]:
    """Check consistency of design decisions."""
    findings = []
    store = WorkspaceStore(workspace_file)

    # Load recorded design decisions
    decisions = store.read_jsonl_prefer_backend(DESIGN_DECISIONS_FILE, limit=100)

    # Check for conflicting decisions
    decision_by_topic: Dict[str, List[Dict[str, Any]]] = {}
    for decision in decisions:
        topic = decision.get("topic", "")
        decision_by_topic.setdefault(topic, []).append(decision)

    for topic, topic_decisions in decision_by_topic.items():
        if len(topic_decisions) > 1:
            # Check for conflicting decisions
            recent = topic_decisions[-1]
            older = topic_decisions[:-1]

            for old in older:
                if old.get("decision") != recent.get("decision"):
                    findings.append({
                        "category": "design_consistency",
                        "severity": "medium",
                        "code": "conflicting_decisions",
                        "message": f"主题 '{topic}' 存在冲突的设计决策",
                        "details": {
                            "recent": recent,
                            "older": old,
                        },
                    })

    return findings


def _score_to_quality(score: int) -> str:
    """Convert score to quality label."""
    if score >= 85:
        return "high"
    elif score >= 60:
        return "medium"
    else:
        return "low"


def _categorize_findings(findings: List[Dict[str, Any]]) -> Dict[str, int]:
    """Categorize findings by category."""
    categories: Dict[str, int] = {}
    for finding in findings:
        category = finding.get("category", "unknown")
        categories[category] = categories.get(category, 0) + 1
    return categories


def _build_audit_summary(findings: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build summary of audit findings."""
    severity_counts = {"high": 0, "medium": 0, "low": 0}
    category_counts: Dict[str, int] = {}

    for finding in findings:
        severity = finding.get("severity", "low")
        category = finding.get("category", "unknown")
        severity_counts[severity] = severity_counts.get(severity, 0) + 1
        category_counts[category] = category_counts.get(category, 0) + 1

    return {
        "total_findings": len(findings),
        "by_severity": severity_counts,
        "by_category": category_counts,
        "critical_count": severity_counts["high"],
    }


def _generate_audit_recommendations(findings: List[Dict[str, Any]]) -> List[str]:
    """Generate actionable recommendations from findings."""
    recommendations = []

    high_findings = [f for f in findings if f.get("severity") == "high"]
    if high_findings:
        recommendations.append(f"优先处理 {len(high_findings)} 个高优先级问题")

    doc_findings = [f for f in findings if f.get("category") == "documentation"]
    if doc_findings:
        recommendations.append("更新文档以匹配当前实现")

    test_findings = [f for f in findings if f.get("category") == "testing"]
    if test_findings:
        recommendations.append("补充测试用例")

    if not recommendations:
        recommendations.append("项目健康，继续保持")

    return recommendations


def record_design_decision(
    workspace_file: str | Path,
    topic: str,
    decision: str,
    rationale: str,
    alternatives: Optional[List[str]] = None,
    impact: str = "medium",
) -> Dict[str, Any]:
    """Record a design decision for future reference.

    This helps prevent:
    - Revisiting settled decisions
    - Conflicting decisions
    - Lost context
    """
    store = WorkspaceStore(workspace_file)

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "topic": topic,
        "decision": decision,
        "rationale": rationale,
        "alternatives": alternatives or [],
        "impact": impact,
    }

    store.append_jsonl(DESIGN_DECISIONS_FILE, entry)

    return {
        "recorded": True,
        "topic": topic,
        "decision": decision,
    }


def get_design_decisions(
    workspace_file: str | Path,
    topic: str = "",
    limit: int = 50,
) -> Dict[str, Any]:
    """Retrieve design decisions with optional filtering."""
    store = WorkspaceStore(workspace_file)
    decisions = store.read_jsonl_prefer_backend(DESIGN_DECISIONS_FILE, limit=max(limit, 200))

    if topic:
        decisions = [d for d in decisions if d.get("topic") == topic]

    return {
        "total_decisions": len(decisions),
        "decisions": decisions[-limit:],
    }


def generate_audit_report(
    workspace_file: str | Path,
    work_package: str = "",
) -> Dict[str, Any]:
    """Generate comprehensive audit report."""
    audit = run_completion_audit(workspace_file, work_package=work_package)
    decisions = get_design_decisions(workspace_file)

    return {
        "audit": audit,
        "design_decisions": decisions,
        "overall_health": _calculate_overall_health(audit, decisions),
    }


def _calculate_overall_health(
    audit: Dict[str, Any],
    decisions: Dict[str, Any],
) -> Dict[str, Any]:
    """Calculate overall project health."""
    audit_score = audit.get("score", 0)
    decision_count = decisions.get("total_decisions", 0)

    # Health factors
    factors = {
        "documentation": 100 - len([f for f in audit.get("findings", []) if f.get("category") == "documentation"]) * 10,
        "testing": 100 - len([f for f in audit.get("findings", []) if f.get("category") == "testing"]) * 15,
        "implementation": 100 - len([f for f in audit.get("findings", []) if f.get("category") == "implementation"]) * 20,
        "design_consistency": 100 if decision_count > 0 else 80,
    }

    overall = sum(min(100, max(0, v)) for v in factors.values()) / len(factors)

    return {
        "overall_score": round(overall),
        "quality": _score_to_quality(int(overall)),
        "factors": factors,
        "recommendation": "项目健康" if overall >= 80 else "需要关注" if overall >= 60 else "需要改进",
    }
