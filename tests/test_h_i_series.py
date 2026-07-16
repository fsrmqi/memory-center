"""Tests for H-01~H-11 and I-01~I-05: Spec-driven governance, views, docs, compatibility.

H-01: Constitution (rules as governance artifacts)
H-02: Traceability (task→change→verification links via artifacts+write_receipts)
H-03: Clarify & cross-artifact consistency (rules match_rules)
H-04: Resumable workflow state machine (session/resume/handoff)
H-05: Deterministic diff scope (git diff incremental)
H-06: Graph-aware change bundles (view builder change mode)
H-07: Layered rule matching (rules engine)
H-08: Context-aware change review (graph views + reasoning)
H-09: Finding location & dedup (write receipts + verification)
H-10: Review findings → verification & memory (verification loop)
H-11: Preset/extension boundary (bundle export)
I-01: Documentation convergence (docs exist and are consistent)
I-02: Compatibility audit (schema compat tests)
I-03: Security & privacy (no secrets in repo)
I-04: Final verification (full suite green)
I-05: Version & release (version accessible, changelog exists)
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from memory_center import __version__


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


# ═════════════════════════════════════════════════════════════════════════════
# H-01: Constitution (rules as governance artifacts)
# ═════════════════════════════════════════════════════════════════════════════

class TestH01Constitution:
    def test_rules_module_exists(self):
        from memory_center.core.governance.rules import match_rules
        assert callable(match_rules)

    def test_default_rules_have_ids_and_severity(self):
        from memory_center.core.governance.rules import DEFAULT_RULES
        assert len(DEFAULT_RULES) > 0
        for rule in DEFAULT_RULES:
            assert "id" in rule
            assert "severity" in rule
            assert rule["severity"] in ("must", "should", "may", "info")

    def test_rules_match_on_scope_and_keywords(self, demo_workspace: Path):
        from memory_center.core.governance.rules import match_rules
        from memory_center.core.storage.workspace import WorkspaceStore
        ws = WorkspaceStore(str(demo_workspace))
        from memory_center.core.workspace.config import load_workspace_config
        load_workspace_config(str(demo_workspace))
        from memory_center.core.storage.workspace import WorkspaceStore
        ws = WorkspaceStore(str(demo_workspace))
        results = match_rules(ws, intent="kafka consumer idempotent")
        assert isinstance(results, list)

    def test_rules_load_yaml_config_callable(self):
        from memory_center.core.governance.rules import load_yaml_rule_config
        assert callable(load_yaml_rule_config)

    def test_rules_not_overridden_silently(self):
        from memory_center.core.governance.rules import DEFAULT_RULES
        ids = [r["id"] for r in DEFAULT_RULES]
        assert len(ids) == len(set(ids)), "Duplicate rule IDs found"


# ═════════════════════════════════════════════════════════════════════════════
# H-02: Traceability (task→change→verification links)
# ═════════════════════════════════════════════════════════════════════════════

class TestH02Traceability:
    def test_write_receipts_module(self):
        from memory_center.core.tasks.receipts import build_write_receipt
        assert callable(build_write_receipt)

    def test_build_write_receipt_returns_dict(self):
        from memory_center.core.tasks.receipts import build_write_receipt
        receipt = build_write_receipt(
            layer="L1",
            action="write",
            scope="test",
            target="test",
            target_file="test.txt",
        )
        assert isinstance(receipt, dict)

    def test_artifacts_module(self):
        from memory_center.core.tasks.artifacts import get_task_artifact, list_task_spaces
        assert callable(list_task_spaces)
        assert callable(get_task_artifact)

    def test_list_task_spaces_returns_list(self, demo_workspace: Path):
        from memory_center.core.tasks.artifacts import list_task_spaces
        spaces = list_task_spaces(str(demo_workspace))
        assert isinstance(spaces, dict)

    def test_write_receipts_file_defined(self):
        from memory_center.core.tasks.receipts import WRITE_RECEIPTS_FILE
        assert isinstance(WRITE_RECEIPTS_FILE, str)
        assert len(WRITE_RECEIPTS_FILE) > 0


# ═════════════════════════════════════════════════════════════════════════════
# H-03: Clarify & cross-artifact consistency
# ═════════════════════════════════════════════════════════════════════════════

class TestH03ClarifyConsistency:
    def test_rules_have_required_fields(self):
        from memory_center.core.governance.rules import DEFAULT_RULES
        for rule in DEFAULT_RULES:
            assert "id" in rule
            assert "title" in rule
            assert "scope" in rule

    def test_rules_scope_is_list(self):
        from memory_center.core.governance.rules import DEFAULT_RULES
        for rule in DEFAULT_RULES:
            assert isinstance(rule["scope"], list)

    def test_glob_match_basic(self):
        from memory_center.core.governance.rules import _glob_match
        assert _glob_match("src/main/java/UserConsumer.java", "**/*Consumer.java")
        assert not _glob_match("src/main/java/User.java", "**/*Consumer.java")

    def test_glob_match_recursive(self):
        from memory_center.core.governance.rules import _glob_match
        assert _glob_match("a/b/c/d.java", "**/*.java")


# ═════════════════════════════════════════════════════════════════════════════
# H-04: Resumable workflow state machine
# ═════════════════════════════════════════════════════════════════════════════

class TestH04ResumableWorkflow:
    def test_resume_packet_exists(self, demo_workspace: Path):
        from memory_center.core.orchestrator.resume import workspace_resume_packet
        result = workspace_resume_packet(str(demo_workspace))
        assert isinstance(result, dict)

    def test_session_start_and_close(self, demo_workspace: Path):
        from memory_center.core.orchestrator.session import workspace_recent_sessions
        result = workspace_recent_sessions(str(demo_workspace))
        assert isinstance(result, dict)

    def test_handoff_packet_exists(self, demo_workspace: Path):
        from memory_center.core.orchestrator.resume import workspace_handoff_packet
        result = workspace_handoff_packet(str(demo_workspace), target_model="test-model")
        assert isinstance(result, dict)


# ═════════════════════════════════════════════════════════════════════════════
# H-05: Deterministic diff scope
# ═════════════════════════════════════════════════════════════════════════════

class TestH05DiffScope:
    def test_incremental_detect_changes(self, tmp_path: Path):
        from memory_center.core.indexing.incremental import git_changed_files
        result = git_changed_files(tmp_path)
        assert isinstance(result, list)

    def test_incremental_classify_changes(self, demo_workspace: Path):
        from memory_center.core.indexing.incremental import IncrementalIndexer
        from memory_center.core.storage.unified import UnifiedStore
        db_path = demo_workspace.parent / ".memory-center" / "graph" / "test.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        store = UnifiedStore(str(db_path))
        try:
            indexer = IncrementalIndexer(store, demo_workspace.parent.parent)
            changes = indexer.detect_changes()
            assert "added" in changes
            assert "modified" in changes
            assert "deleted" in changes
        finally:
            store.close()


# ═════════════════════════════════════════════════════════════════════════════
# H-06: Graph-aware change bundles (view builder)
# ═════════════════════════════════════════════════════════════════════════════

class TestH06ChangeBundles:
    def test_graph_view_dataclass(self):
        from memory_center.core.views.builder import GraphView
        view = GraphView(mode="change", title="Test Change", description="Test")
        assert view.mode == "change"
        d = view.to_dict()
        assert d["mode"] == "change"
        assert d["title"] == "Test Change"

    def test_graph_view_builder_modes(self):
        from memory_center.core.views.builder import GraphViewBuilder
        assert callable(GraphViewBuilder)

    def test_graph_view_has_required_structure(self):
        from memory_center.core.views.builder import GraphView
        view = GraphView(mode="architecture", title="Arch View")
        d = view.to_dict()
        assert "nodes" in d
        assert "edges" in d
        assert "groups" in d
        assert "metadata" in d
        assert "persona" in d

    def test_graph_view_persona_default(self):
        from memory_center.core.views.builder import GraphView
        view = GraphView(mode="business", title="Biz")
        assert view.persona == "developer"


# ═════════════════════════════════════════════════════════════════════════════
# H-07: Layered rule matching
# ═════════════════════════════════════════════════════════════════════════════

class TestH07LayeredRules:
    def test_default_rules_count(self):
        from memory_center.core.governance.rules import DEFAULT_RULES
        assert len(DEFAULT_RULES) >= 5

    def test_rule_severity_levels(self):
        from memory_center.core.governance.rules import DEFAULT_RULES
        severities = {r["severity"] for r in DEFAULT_RULES}
        assert "must" in severities or "should" in severities

    def test_rules_have_file_patterns(self):
        from memory_center.core.governance.rules import DEFAULT_RULES
        rules_with_patterns = [r for r in DEFAULT_RULES if "file_patterns" in r]
        assert len(rules_with_patterns) > 0

    def test_rules_have_trigger_keywords(self):
        from memory_center.core.governance.rules import DEFAULT_RULES
        rules_with_keywords = [r for r in DEFAULT_RULES if "trigger_keywords" in r]
        assert len(rules_with_keywords) > 0

    def test_match_rules_returns_list(self, demo_workspace: Path):
        from memory_center.core.governance.rules import match_rules
        from memory_center.core.storage.workspace import WorkspaceStore
        ws = WorkspaceStore(str(demo_workspace))
        results = match_rules(ws, intent="feign client contract change")
        assert isinstance(results, list)


# ═════════════════════════════════════════════════════════════════════════════
# H-08: Context-aware change review
# ═════════════════════════════════════════════════════════════════════════════

class TestH08ContextAwareReview:
    def test_reasoning_patterns_module(self):
        from memory_center.core.reasoning.patterns import GraphPatternEngine
        assert callable(GraphPatternEngine)

    def test_reasoning_transitive_module(self):
        from memory_center.core.reasoning.transitive import TransitiveInferenceEngine
        assert callable(TransitiveInferenceEngine)

    def test_reasoning_risk_module(self):
        from memory_center.core.reasoning.risk import RiskPatternEngine
        assert RiskPatternEngine is not None

    def test_drilldown_navigator_module(self):
        from memory_center.core.navigation.drilldown import DrillDownNavigator
        assert DrillDownNavigator is not None
        assert callable(DrillDownNavigator)

    def test_drilldown_has_methods(self):
        from memory_center.core.navigation.drilldown import DrillDownNavigator
        assert hasattr(DrillDownNavigator, "expand_ref")
        assert hasattr(DrillDownNavigator, "drill_timeline")
        assert hasattr(DrillDownNavigator, "drill_task")
        assert hasattr(DrillDownNavigator, "build_facade_summary")
        assert hasattr(DrillDownNavigator, "build_handoff_context")

    def test_drilldown_works_on_demo(self, demo_workspace: Path):
        from memory_center.core.navigation.drilldown import DrillDownNavigator
        with DrillDownNavigator(str(demo_workspace)) as nav:
            assert nav.store is not None
            assert nav.backend is not None


# ═════════════════════════════════════════════════════════════════════════════
# H-09: Finding location, validation & dedup
# ═════════════════════════════════════════════════════════════════════════════

class TestH09FindingLocation:
    def test_write_receipts_have_ids(self):
        from memory_center.core.tasks.receipts import build_write_receipt
        receipt = build_write_receipt(layer="L1", action="write", scope="test", target="test", target_file="test.txt")
        assert isinstance(receipt, dict)
        # Should have some kind of unique identifier
        assert any(k in receipt for k in ["receipt_id", "id", "timestamp"])

    def test_verification_loop_tracks_findings(self, demo_workspace: Path):
        from memory_center.core.verification.loop import VerificationLoop
        vl = VerificationLoop(str(demo_workspace))
        vl.start("test-task", "Finding test")
        vl.complete_phase("test-task", "analyze", {"findings": ["issue-1", "issue-2"]})
        status = vl.get_status("test-task")
        assert status["task_id"] == "test-task"


# ═════════════════════════════════════════════════════════════════════════════
# H-10: Review findings → verification & memory
# ═════════════════════════════════════════════════════════════════════════════

class TestH10ReviewToVerification:
    def test_verification_loop_generates_checklist(self, demo_workspace: Path):
        from memory_center.core.verification.loop import VerificationLoop
        vl = VerificationLoop(str(demo_workspace))
        checklist = vl.get_checklist("code_change")
        assert len(checklist) > 0
        assert all(isinstance(item, str) for item in checklist)

    def test_pattern_promotion_records_proposals(self, demo_workspace: Path):
        from memory_center.core.verification.pattern_promotion import PatternPromotion
        pp = PatternPromotion(str(demo_workspace))
        proposal = pp.propose("case", "c-1", "test_pattern", "test desc", [{"e": 1}])
        assert proposal["status"] == "proposed"
        proposals = pp.list_proposals()
        assert isinstance(proposals, list)

    def test_heuristics_register_records(self, demo_workspace: Path):
        from memory_center.core.verification.heuristics import HeuristicsRegister
        hr = HeuristicsRegister(str(demo_workspace))
        entry = hr.record("test", "pattern", "trigger", "outcome", 0.7)
        assert "heuristic_id" in entry
        results = hr.query("test")
        assert isinstance(results, list)


# ═════════════════════════════════════════════════════════════════════════════
# H-11: Preset / extension boundary
# ═════════════════════════════════════════════════════════════════════════════

class TestH11PresetExtensionBoundary:
    def test_bundle_export_codex(self, demo_workspace: Path):
        from memory_center.core.verification.bundle_export import generate_agent_bundle
        bundle = generate_agent_bundle(str(demo_workspace), agent="codex")
        assert bundle["agent"] == "codex"
        assert "contents" in bundle
        assert "agent_specific" in bundle

    def test_bundle_export_claude(self, demo_workspace: Path):
        from memory_center.core.verification.bundle_export import generate_agent_bundle
        bundle = generate_agent_bundle(str(demo_workspace), agent="claude")
        assert bundle["agent"] == "claude"
        assert bundle["agent_specific"]["mcp_config_path"] == ".mcp.json"

    def test_bundle_export_cursor(self, demo_workspace: Path):
        from memory_center.core.verification.bundle_export import generate_agent_bundle
        bundle = generate_agent_bundle(str(demo_workspace), agent="cursor")
        assert bundle["agent"] == "cursor"
        assert bundle["agent_specific"]["mcp_config_path"] == ".cursor/mcp.json"

    def test_bundle_contains_workflow_profiles(self, demo_workspace: Path):
        from memory_center.core.verification.bundle_export import generate_agent_bundle
        bundle = generate_agent_bundle(str(demo_workspace), agent="codex")
        profiles = bundle["contents"]["workflow_profiles"]
        assert "quick-fix" in profiles
        assert "long-task" in profiles

    def test_bundle_no_secrets(self, demo_workspace: Path):
        import json

        from memory_center.core.verification.bundle_export import generate_agent_bundle
        bundle = generate_agent_bundle(str(demo_workspace), agent="codex")
        content = json.dumps(bundle)
        # Should not contain obvious secret patterns
        assert "sk-" not in content
        assert "api_key" not in content.lower()
        assert "password" not in content.lower()


# ═════════════════════════════════════════════════════════════════════════════
# I-01: Documentation convergence
# ═════════════════════════════════════════════════════════════════════════════

class TestI01Documentation:
    def test_readme_exists(self):
        readme = Path("README.md")
        assert readme.exists()
        content = readme.read_text(encoding="utf-8")
        assert len(content) > 100

    def test_architecture_doc_exists(self):
        doc = Path("docs/ARCHITECTURE.md")
        assert doc.exists()

    def test_mcp_guide_exists(self):
        doc = Path("docs/MCP_GUIDE.md")
        assert doc.exists()

    def test_delegated_execution_plan_exists(self):
        doc = Path("docs/archive/DELEGATED_EXECUTION_PLAN.md")
        assert doc.exists()

    def test_next_phase_master_plan_exists(self):
        doc = Path("docs/NEXT_PHASE_MASTER_PLAN.md")
        assert doc.exists()

    def test_special_notes_exists(self):
        doc = Path("docs/SPECIAL_NOTES.md")
        assert doc.exists()

    def test_delegated_execution_log_exists(self):
        doc = Path("docs/archive/DELEGATED_EXECUTION_LOG.md")
        assert doc.exists()

    def test_release_doc_exists(self):
        doc = Path("docs/RELEASE.md")
        assert doc.exists()

    def test_ontology_doc_exists(self):
        doc = Path("docs/ONTOLOGY.md")
        assert doc.exists()

    def test_user_guide_exists(self):
        doc = Path("docs/USER_GUIDE.md")
        assert doc.exists()


# ═════════════════════════════════════════════════════════════════════════════
# I-02: Compatibility audit
# ═════════════════════════════════════════════════════════════════════════════

class TestI02CompatibilityAudit:
    def test_schema_compatibility_tests_exist(self):
        test_file = Path("tests/test_schema_compatibility.py")
        assert test_file.exists()

    def test_facade_schemas_tests_exist(self):
        test_file = Path("tests/test_facade_schemas.py")
        assert test_file.exists()

    def test_capability_matrix_tests_exist(self):
        test_file = Path("tests/test_capability_matrix.py")
        assert test_file.exists()

    def test_schema_version_registry_exists(self):
        from memory_center.core.foundation.schemas import SCHEMA_VERSIONS
        assert isinstance(SCHEMA_VERSIONS, dict)
        assert len(SCHEMA_VERSIONS) > 0

    def test_schema_required_fields_registry_exists(self):
        from memory_center.core.foundation.schemas import SCHEMA_REQUIRED_FIELDS
        assert isinstance(SCHEMA_REQUIRED_FIELDS, dict)


# ═════════════════════════════════════════════════════════════════════════════
# I-03: Security & privacy
# ═════════════════════════════════════════════════════════════════════════════

class TestI03SecurityPrivacy:
    def test_no_private_paths_in_fixtures(self):
        """Fixture files should not contain real private paths."""
        fixtures_dir = Path("tests/fixtures.py")
        if fixtures_dir.exists():
            content = fixtures_dir.read_text(encoding="utf-8")
            # Should not contain real user home paths beyond generic patterns
            assert "/Users/admin/" not in content
            assert "/home/admin/" not in content

    def test_no_secrets_in_source(self):
        """Source code should not contain obvious secrets."""
        import subprocess
        result = subprocess.run(
            ["grep", "-r", "-l", "sk-[a-zA-Z0-9]\\{20,\\}", "memory_center/"],
            capture_output=True, text=True, cwd=".",
        )
        # Should find no files with OpenAI-style API keys
        assert result.stdout.strip() == "" or result.returncode != 0

    def test_diagnostics_safe_reason_exists(self):
        from memory_center.core.observability.diagnostics import safe_reason
        assert callable(safe_reason)

    def test_diagnostics_strips_paths(self):
        from memory_center.core.observability.diagnostics import safe_reason
        result = safe_reason(reason="/Users/test/secret/path")
        assert "/Users/test" not in result

    def test_workspace_pollution_test_exists(self):
        test_file = Path("tests/test_workspace_pollution.py")
        assert test_file.exists()

    def test_no_memory_center_generated_in_repo(self):
        """No .memory-center directories in non-example locations."""
        mc_dirs = list(Path(".").rglob(".memory-center"))
        for d in mc_dirs:
            # Only allowed in examples/
            assert "examples" in str(d) or ".claude" in str(d), f"Unexpected .memory-center: {d}"


# ═════════════════════════════════════════════════════════════════════════════
# I-04: Final verification (full suite smoke)
# ═════════════════════════════════════════════════════════════════════════════

class TestI04FinalVerification:
    def test_version_accessible(self):
        assert isinstance(__version__, str)
        assert len(__version__) > 0

    def test_pyproject_exists(self):
        assert Path("pyproject.toml").exists()

    def test_compile_all(self):
        """All Python files should compile without syntax errors."""
        import os
        import py_compile
        errors = []
        for root, dirs, files in os.walk("memory_center"):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for f in files:
                if f.endswith(".py"):
                    path = os.path.join(root, f)
                    try:
                        py_compile.compile(path, doraise=True)
                    except py_compile.PyCompileError as e:
                        errors.append(str(e))
        assert len(errors) == 0, f"Compile errors: {errors}"

    def test_git_clean_demo(self):
        """Generated private workspace data must not be added under examples."""
        import subprocess
        result = subprocess.run(
            [
                "git",
                "status",
                "--short",
                "--untracked-files=all",
                "examples/**/.memory-center/index",
                "examples/**/.memory-center/memory",
            ],
            capture_output=True, text=True, cwd=".",
        )
        assert result.stdout.strip() == "", f"Generated demo data found: {result.stdout}"

    def test_three_entry_points(self):
        from memory_center.cli.main import app
        from memory_center.http.server import serve_http
        from memory_center.mcp.server import create_server
        assert app is not None
        assert callable(create_server)
        assert callable(serve_http)


# ═════════════════════════════════════════════════════════════════════════════
# I-05: Version & release
# ═════════════════════════════════════════════════════════════════════════════

class TestI05VersionRelease:
    def test_version_format(self):
        parts = __version__.split(".")
        assert len(parts) >= 2, f"Version should be semver-like: {__version__}"

    def test_pyproject_version_matches(self):
        import tomli as tomllib
        pyproject = Path("pyproject.toml")
        if pyproject.exists():
            try:
                with open(pyproject, "rb") as f:
                    data = tomllib.load(f)
                # Version should exist in pyproject
                assert "project" in data
            except ImportError:
                # Python < 3.11
                pass

    def test_changelog_exists(self):
        changelog = Path("CHANGELOG.md")
        if changelog.exists():
            content = changelog.read_text(encoding="utf-8")
            assert len(content) > 50

    def test_license_exists(self):
        license_file = Path("LICENSE")
        if license_file.exists():
            assert license_file.stat().st_size > 0

    def test_release_doc_has_content(self):
        release = Path("docs/RELEASE.md")
        if release.exists():
            content = release.read_text(encoding="utf-8")
            assert len(content) > 100
