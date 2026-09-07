"""CLI 命令面快照测试 / CLI command-surface snapshot test.

cli/main.py 按 ADR-0002 拆至 cli/commands/ 家族模块后,命令注册顺序按家族重组,
`--help` 列出顺序与拆分前不同;命令名与调用路径必须保持不变。
本测试锚定完整命令面(153 根命令 + 4 子组),防止未来家族拆分/迁移时静默丢失或新增命令。

After cli/main.py was split into cli/commands/ family modules per ADR-0002, command
registration order is regrouped by family so `--help` listing order changed; command
names and invocation paths must stay unchanged. This test anchors the full surface
(152 root commands + 4 sub-groups) so future family splits cannot silently drop or
add commands.
"""

import click
import typer

from memory_center.cli.main import app

EXPECTED_ROOT_COMMANDS = frozenset({
    "agent-execution-import", "agent-execution-summary", "architecture-communities", "artifact", "assertion-inspect", "assertion-query",
    "assertion-status", "audit", "backend-consistency", "bench-profile",
    "bootstrap-context", "bundle-export", "business-flow", "business-flow-impact",
    "callees", "callers", "case-decisions", "case-reinstate", "case-supersede", "change-impact-confirm", "change-impact-reports",
    "change-review", "check-contract", "check-rules", "consolidate-session", "consolidation-candidates", "constraint", "context",
    "decide-consolidation-candidate",
    "continuity-dashboard", "contracts", "detect-changes", "discover", "doctor",
    "drill-ref", "drill-task", "drill-timeline", "dsh-delivery-capture", "end-session",
    "eval-agent-guidance", "eval-agent-guidance-adoption",
    "eval-agent-guidance-adoption-trend", "eval-agent-guidance-replay",
    "eval-agent-guidance-replay-campaign", "eval-agent-guidance-replay-trend",
    "eval-agent-guidance-trend", "eval-assertion-reindex-gate",
    "eval-assertion-scope-gate", "eval-cochange", "eval-context-weight",
    "eval-golden", "eval-golden-baseline-save", "eval-handoff",
    "eval-index-freshness", "eval-lookup-contract", "eval-lookup-contract-baseline-save", "eval-lookup-contract-coverage", "eval-lookup-facades", "eval-java-call-resolution",
    "eval-java-call-resolution-metrics", "eval-java-call-resolution-review",
    "eval-java-call-resolution-unresolved", "eval-ontology-gate",
    "eval-parser-benchmark", "eval-reasoning-prompts", "eval-regression-suite", "eval-resume", "eval-session-recall",
    "eval-retrieval-replay", "eval-retrieval-replay-cases", "eval-token-benchmark", "eval-token-benchmark-compare",
    "eval-token-benchmark-save", "eval-token-benchmark-trend", "eval-token-gain",
    "eval-tool-adoption", "eval-workflow-orchestration", "eval-write-quality",
    "explanation", "export-evidence-subgraph", "export-mermaid",
    "export-workspace-dashboard", "external-capability-audit",
    "external-capability-snapshot", "generate-hooks", "generate-skills",
    "group", "handoff-history", "handoff-packet", "heuristics",
    "http-route-contract-audit", "impact", "init", "inspect", "job-cancel", "job-status",
    "knowledge-candidates", "knowledge-link-attach", "knowledge-link-drift", "knowledge-link-mark",
    "knowledge-link-metrics", "knowledge-links",
    "log-session-event", "lookup-hint", "mcp-bridge-action", "mcp-bridge-status",
    "memory-backend-query", "memory-execute-write", "memory-plan-write",
    "memory-write-judge", "method-walkthrough", "metrics-summary", "model-profile",
    "next-actions", "parser-status", "pattern-promotion", "performance-snapshot",
    "performance-status", "plan-change", "provider-action", "provider-evidence-fuse",
    "query", "recent-evidence", "recent-sessions", "record-case", "ref-batch",
    "ref-get", "registry", "regression-alerts", "regression-smoke", "reindex",
    "release-gate", "replay-write-chain", "resume-context", "resume-packet",
    "quality-gate",
    "retrieval-model-profile", "retrieval-reranker-prewarm",
    "retrieval-reranker-status", "run-hook", "runtime-audit", "runtime-governance",
    "scoped-refresh-performance", "search-code", "serve-http", "session-archive",
    "session-archive-plan", "session-summary",
    "setup-agent", "sniff", "start-session", "status", "suggest-case", "symbol",
    "sync-case-artifacts", "sync-sniff-artifacts", "task-shadow-authority", "task-shadow-bind",
    "task-shadow-discard", "task-shadow-handoff-claim", "task-shadow-handoff-close",
    "task-shadow-handoff-create", "task-shadow-handoff-get", "task-shadow-handoff-hand-off",
    "task-shadow-handoff-list", "task-shadow-observation", "task-shadow-observation-list",
    "task-shadow-promote", "task-shadow-record-snapshot", "task-shadow-retention",
    "task-shadow-status", "tool-usage-report", "trace",
    "unresolved-items", "vector-ann-rebuild", "vector-ann-status",
    "vector-ann-tune", "verification-loop", "verify-checklist", "walkthrough-eval",
    "walkthrough-export", "walkthrough-health", "watcher-run", "watcher-start",
    "watcher-status", "watcher-stop", "wiki-assets-sync", "wiki-promotion-confirm", "wiki-promotion-preview",
    "work-close", "work-handoff", "work-health",
    "work-log", "work-resume", "work-resume-check", "work-start", "work-sync",
    "workflow-profile", "workflow-recommend", "workspace", "workspace-dashboard",
    "write-receipts",
})

EXPECTED_SUBGROUP_COMMANDS = {
    "artifact": frozenset({
        "append-change-log", "append-task-change-log", "archive-task",
        "assertion-sparsify", "assertion-vacuum", "asset-approve", "asset-bind",
        "asset-loadout", "asset-register", "asset-share", "asset-status",
        "asset-sync", "auto-archive-tasks", "compact-change-log", "compact-task",
        "context", "create-task", "delivery-breakdown", "delivery-contract",
        "delivery-execute-validation", "delivery-failure-candidates",
        "delivery-init", "delivery-matrix", "delivery-policy",
        "delivery-record-validation", "delivery-skill-canary",
        "delivery-skill-candidate", "delivery-skill-contract-update",
        "delivery-skill-eval-init", "delivery-skill-eval-run",
        "delivery-skill-eval-status", "delivery-skill-evaluate",
        "delivery-skill-observe", "delivery-skill-publish",
        "delivery-skill-recommend", "delivery-skill-replay",
        "delivery-skill-rollback", "delivery-skill-status",
        "delivery-skill-synthesize", "delivery-status",
        "delivery-subtask-status", "delivery-transition", "generation-gc", "get",
        "get-task", "health-task", "health-tasks", "index-export-cleanup", "jsonl-export-status",
        "jsonl-export-sync", "list",
        "list-tasks", "outline", "repair-plan-task", "repair-task", "resolve-task",
        "semantic-index-compact", "storage-budget", "storage-legacy-cleanup",
        "storage-vacuum", "touch-task-activity", "update", "update-task",
        "update-task-status", "wiki-document-ingest",
    }),
    "group": frozenset({"add", "create", "impact", "query", "status"}),
    "registry": frozenset({"add", "list"}),
    "workspace": frozenset({"add-service", "list-services", "remove-service"}),
}


def test_root_command_surface_snapshot():
    cmd = typer.main.get_command(app)
    assert set(cmd.commands) == EXPECTED_ROOT_COMMANDS, (
        f"根命令面差异: missing={sorted(EXPECTED_ROOT_COMMANDS - set(cmd.commands))}, "
        f"added={sorted(set(cmd.commands) - EXPECTED_ROOT_COMMANDS)}"
    )


def test_subgroup_command_surface_snapshot():
    cmd = typer.main.get_command(app)
    # typer 0.27 + click 8.4 下 add_typer 产生 TyperGroup（click.Group 的子类
    # 之外的独立类型），isinstance(sub, click.Group) 不再成立——按"有子命令表"
    # 识别（根命令都是单命令 callback，没有 .commands）。
    subgroups = {
        name for name, sub in cmd.commands.items()
        if isinstance(sub, click.Group) or getattr(sub, "commands", None)
    }
    assert subgroups == set(EXPECTED_SUBGROUP_COMMANDS), (
        f"子命令组差异: missing={sorted(set(EXPECTED_SUBGROUP_COMMANDS) - subgroups)}, "
        f"added={sorted(subgroups - set(EXPECTED_SUBGROUP_COMMANDS))}"
    )
    for group, expected in EXPECTED_SUBGROUP_COMMANDS.items():
        actual = set(cmd.commands[group].commands)
        assert actual == expected, (
            f"'{group}' 子命令差异: missing={sorted(expected - actual)}, "
            f"added={sorted(actual - expected)}"
        )
