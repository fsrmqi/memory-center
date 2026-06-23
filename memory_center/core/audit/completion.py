"""Completion audit — documentation alignment and governance.

This module implements Phase E of NEXT_PHASE_MASTER_PLAN:
- Regular completion audits per work package
- Sync docs after each capability enhancement
- Separate design choices from real bugs
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..quality import build_quality_summary
from ..store import WorkspaceStore

AUDIT_LOG_FILE = "completion-audit.jsonl"
DESIGN_DECISIONS_FILE = "design-decisions.jsonl"



def detect_workspace_type(project_root: Path) -> str:
    """Auto-detect workspace type from project structure (Phase E enhanced).

    Returns: 'java-maven', 'java-gradle', 'java-spring-maven', 'java-spring-gradle',
             'node', 'python', 'rust', 'go', 'scala', 'kotlin-gradle',
             'monorepo', 'mixed', 'unknown'
    """
    has_pom = (project_root / "pom.xml").exists()
    has_gradle = (project_root / "build.gradle").exists() or (project_root / "build.gradle.kts").exists()
    has_package = (project_root / "package.json").exists()
    has_pyproject = (project_root / "pyproject.toml").exists() or (project_root / "setup.py").exists()
    has_cargo = (project_root / "Cargo.toml").exists()
    has_go_mod = (project_root / "go.mod").exists()
    has_build_sbt = (project_root / "build.sbt").exists()
    has_workspaces = (project_root / "pnpm-workspace.yaml").exists() or (project_root / "lerna.json").exists()

    # Check for Spring Cloud indicators
    is_spring = False
    if has_pom or has_gradle:
        for pom_path in project_root.rglob("pom.xml"):
            try:
                text = pom_path.read_text(errors="ignore")
                if "spring" in text.lower() or "feign" in text.lower():
                    is_spring = True
                    break
            except Exception:
                pass

    if has_pom and is_spring:
        return "java-spring-maven"
    if has_gradle and is_spring:
        return "java-spring-gradle"
    if has_pom:
        return "java-maven"
    if has_gradle:
        return "java-gradle"
    if has_package:
        return "node"
    if has_pyproject:
        return "python"
    if has_cargo:
        return "rust"
    if has_go_mod:
        return "go"
    if has_build_sbt:
        return "scala"
    if has_workspaces:
        return "monorepo"
    types = sum([has_pom, has_gradle, has_package, has_pyproject, has_cargo, has_go_mod])
    return "mixed" if types > 1 else "unknown"


def _get_project_root(workspace_file: str | Path) -> Path:
    """Get project root directory from workspace file path.

    workspace.yaml 通常在 .memory-center/ 目录下，需要向上遍历到项目根目录。
    例如: /path/to/project/.memory-center/workspace.yaml -> /path/to/project
    """
    workspace_path = Path(workspace_file).parent
    if workspace_path.name == ".memory-center":
        return workspace_path.parent
    return workspace_path


def run_completion_audit(
    workspace_file: str | Path,
    work_package: str = "",
    check_docs: bool = True,
    check_tests: bool = True,
    check_implementation: bool = True,
) -> dict[str, Any]:
    """Run completion audit for a work package or overall project.

    Checks:
    1. Documentation alignment
    2. Test coverage
    3. Implementation completeness
    4. Design decision consistency
    """
    store = WorkspaceStore(workspace_file)
    findings: list[dict[str, Any]] = []
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

    result = {
        "score": score,
        "quality": _score_to_quality(score),
        "findings": findings,
        "summary": _build_audit_summary(findings),
        "recommendations": _generate_audit_recommendations(findings),
        "recorded": True,
    }
    result["_quality"] = build_quality_summary(
        [{"evidence_type": "fact", "confidence": score / 100.0}],
        freshness_status="unknown",
    )
    return result


def _check_documentation_alignment(
    workspace_file: str | Path,
    work_package: str,
) -> list[dict[str, Any]]:
    """Check if documentation aligns with implementation."""
    findings = []
    project_root = _get_project_root(workspace_file)

    # Universal: README.md always expected
    readme_path = project_root / "README.md"
    if not readme_path.exists():
        findings.append({
            "category": "documentation",
            "severity": "medium",
            "code": "missing_doc",
            "message": "缺少文档: README.md",
            "file": "README.md",
        })

    # Adaptive: check for docs/ directory and at least one doc file
    docs_dir = project_root / "docs"
    known_docs = [
        "ARCHITECTURE.md", "USER_GUIDE.md", "MCP_GUIDE.md",
        "CONTRIBUTING.md", "CHANGELOG.md", "GUIDE.md", "SPECIAL_NOTES.md",
    ]
    if docs_dir.exists():
        has_any_doc = any((docs_dir / d).exists() for d in known_docs)
        if not has_any_doc:
            # Also check for any .md file in docs/
            has_any_doc = any(docs_dir.glob("*.md"))
        if not has_any_doc:
            findings.append({
                "category": "documentation",
                "severity": "medium",
                "code": "missing_doc",
                "message": "docs/ 目录下缺少文档文件",
                "file": "docs/",
            })
    else:
        findings.append({
            "category": "documentation",
            "severity": "low",
            "code": "missing_doc",
            "message": "缺少 docs/ 目录",
            "file": "docs/",
        })

    # Check if SPECIAL_NOTES covers known design decisions (if it exists)
    special_notes_path = project_root / "docs" / "SPECIAL_NOTES.md"
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
) -> list[dict[str, Any]]:
    """Check test coverage for the work package."""
    findings = []
    project_root = _get_project_root(workspace_file)

    # Check for test files — multi-language support
    test_dirs = [
        "tests",
        "test",
        "src/test",
        "src/tests",
    ]

    test_patterns = [
        "**/*.py",
        "**/*Test.java",
        "**/*Tests.java",
        "**/*.test.js",
        "**/*.test.ts",
        "**/*.spec.js",
        "**/*.spec.ts",
        "**/*_test.go",
        "**/*_test.rs",
    ]

    has_tests = False
    for test_dir in test_dirs:
        test_path = project_root / test_dir
        if test_path.exists():
            for pattern in test_patterns:
                if any(test_path.glob(pattern)):
                    has_tests = True
                    break
            if has_tests:
                break

    if not has_tests:
        findings.append({
            "category": "testing",
            "severity": "high",
            "code": "no_tests",
            "message": "未找到测试文件",
        })

    # Check for test framework configuration — multi-framework support
    has_test_config = False

    # Python: pytest config
    for pytest_file in ("pytest.ini", "pyproject.toml", "setup.cfg", "tox.ini"):
        pytest_path = project_root / pytest_file
        if pytest_path.exists():
            content = pytest_path.read_text()
            if "[tool.pytest" in content or "[pytest]" in content:
                has_test_config = True
                break

    # Java: Maven Surefire or Gradle test
    if not has_test_config:
        pom_path = project_root / "pom.xml"
        if pom_path.exists() and "maven-surefire-plugin" in pom_path.read_text():
            has_test_config = True
    if not has_test_config:
        for gradle_file in ("build.gradle", "build.gradle.kts"):
            gradle_path = project_root / gradle_file
            if gradle_path.exists() and "useJUnitPlatform" in gradle_path.read_text():
                has_test_config = True
                break

    # JS/TS: package.json "test" script
    if not has_test_config:
        pkg_path = project_root / "package.json"
        if pkg_path.exists():
            try:
                import json as _json
                pkg = _json.loads(pkg_path.read_text())
                if "test" in pkg.get("scripts", {}):
                    has_test_config = True
            except Exception:
                pass

    # Rust: [dev-dependencies] in Cargo.toml
    if not has_test_config:
        cargo_path = project_root / "Cargo.toml"
        if cargo_path.exists() and "[dev-dependencies]" in cargo_path.read_text():
            has_test_config = True

    # Go: no config needed if test files exist
    if not has_test_config:
        for test_dir in test_dirs:
            test_path = project_root / test_dir
            if test_path.exists() and any(test_path.glob("**/*_test.go")):
                has_test_config = True
                break

    if not has_test_config:
        findings.append({
            "category": "testing",
            "severity": "low",
            "code": "no_test_config",
            "message": "未找到测试框架配置",
        })

    return findings


def _check_implementation_completeness(
    workspace_file: str | Path,
    work_package: str,
) -> list[dict[str, Any]]:
    """Check if implementation matches the work package requirements.

    通用实现检查：
    - 检查是否有源代码目录
    - 检查是否有配置文件
    - 检查项目结构是否完整
    """
    findings = []
    project_root = _get_project_root(workspace_file)

    # 检查是否有源代码目录（通用检查，不硬编码特定模块）
    source_dirs = [
        "src",
        "lib",
        "app",
        "main",
    ]

    has_source = False
    for src_dir in source_dirs:
        src_path = project_root / src_dir
        if src_path.exists() and src_path.is_dir():
            has_source = True
            break

    # 如果没有标准源代码目录，检查是否有 Python/Java/JS 文件
    if not has_source:
        has_code_files = any(project_root.glob("**/*.py")) or \
                        any(project_root.glob("**/*.java")) or \
                        any(project_root.glob("**/*.js")) or \
                        any(project_root.glob("**/*.ts"))
        if not has_code_files:
            findings.append({
                "category": "implementation",
                "severity": "medium",
                "code": "no_source_found",
                "message": "未找到源代码文件或目录",
            })

    # 检查是否有配置文件
    config_files = [
        "pom.xml",
        "build.gradle",
        "build.gradle.kts",
        "package.json",
        "pyproject.toml",
        "setup.py",
        "requirements.txt",
        "Cargo.toml",
        "go.mod",
    ]

    has_config = False
    for config_file in config_files:
        if (project_root / config_file).exists():
            has_config = True
            break

    if not has_config:
        findings.append({
            "category": "implementation",
            "severity": "low",
            "code": "no_build_config",
            "message": "未找到构建配置文件（如 pom.xml, package.json, pyproject.toml）",
        })

    return findings


def _check_design_decisions(
    workspace_file: str | Path,
    work_package: str,
) -> list[dict[str, Any]]:
    """Check consistency of design decisions."""
    findings = []
    store = WorkspaceStore(workspace_file)

    # Load recorded design decisions
    decisions = store.read_jsonl_prefer_backend(DESIGN_DECISIONS_FILE, limit=100)

    # Check for conflicting decisions
    decision_by_topic: dict[str, list[dict[str, Any]]] = {}
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


def _categorize_findings(findings: list[dict[str, Any]]) -> dict[str, int]:
    """Categorize findings by category."""
    categories: dict[str, int] = {}
    for finding in findings:
        category = finding.get("category", "unknown")
        categories[category] = categories.get(category, 0) + 1
    return categories


def _build_audit_summary(findings: list[dict[str, Any]]) -> dict[str, Any]:
    """Build summary of audit findings."""
    severity_counts = {"high": 0, "medium": 0, "low": 0}
    category_counts: dict[str, int] = {}

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


def _generate_audit_recommendations(findings: list[dict[str, Any]]) -> list[str]:
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
    alternatives: list[str] | None = None,
    impact: str = "medium",
) -> dict[str, Any]:
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
) -> dict[str, Any]:
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
) -> dict[str, Any]:
    """Generate comprehensive audit report."""
    audit = run_completion_audit(workspace_file, work_package=work_package)
    decisions = get_design_decisions(workspace_file)

    return {
        "audit": audit,
        "design_decisions": decisions,
        "overall_health": _calculate_overall_health(audit, decisions),
    }


def _calculate_overall_health(
    audit: dict[str, Any],
    decisions: dict[str, Any],
) -> dict[str, Any]:
    """Calculate overall project health."""
    decision_count = decisions.get("total_decisions", 0)

    # Health factors — unified weights matching audit scoring (5/8/10)
    doc_count = len([f for f in audit.get("findings", []) if f.get("category") == "documentation"])
    test_count = len([f for f in audit.get("findings", []) if f.get("category") == "testing"])
    impl_count = len([f for f in audit.get("findings", []) if f.get("category") == "implementation"])
    factors = {
        "documentation": 100 - doc_count * 5,
        "testing": 100 - test_count * 8,
        "implementation": 100 - impl_count * 10,
        "design_consistency": 100 if decision_count > 0 else 80,
    }

    overall = sum(min(100, max(0, v)) for v in factors.values()) / len(factors)

    return {
        "overall_score": round(overall),
        "quality": _score_to_quality(int(overall)),
        "factors": factors,
        "recommendation": "项目健康" if overall >= 80 else "需要关注" if overall >= 60 else "需要改进",
    }
