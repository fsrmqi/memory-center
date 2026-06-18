from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Dict

from ..orchestrator.common import SESSION_EVENTS_FILE, load_context
from ..store import WorkspaceStore, _safe_path
from . import answer, escalation
from .artifact import render_walkthrough_markdown, slugify_walkthrough_symbol
from .cache import WalkthroughCache
from .quality import evaluate_walkthrough_result


WalkthroughProvider = Callable[..., Dict[str, Any]]


def build_walkthrough_health(
    workspace_file: str | Path,
    *,
    symbol: str = "",
    project: str = "",
    report_level: str = "standard",
    walkthrough_provider: WalkthroughProvider,
    cache: WalkthroughCache,
) -> Dict[str, Any]:
    workspace_file = escalation.resolve_walkthrough_workspace_input(workspace_file)
    config, store = load_context(workspace_file)
    template_info = answer.load_method_walkthrough_template(workspace_file)
    glossary = answer.load_walkthrough_glossary(workspace_file)
    index_signature = escalation.walkthrough_index_signature(store)
    index_files = {
        name: {"exists": bool(mtime), "mtime": mtime}
        for name, mtime in index_signature.items()
    }
    checks: list[Dict[str, Any]] = []

    def check(name: str, status: str, detail: str = "", evidence: Dict[str, Any] | None = None) -> None:
        checks.append({"name": name, "status": status, "detail": detail, "evidence": evidence or {}})

    check("workspace_file", "pass" if Path(workspace_file).exists() else "fail", str(workspace_file))
    missing_indexes = [name for name, row in index_files.items() if not row["exists"]]
    check("required_indexes", "pass" if not missing_indexes else "warn", "缺失索引文件会降低 walkthrough 完整度。", {"missing": missing_indexes})
    check("template", "pass" if template_info.get("status") == "configured" else "warn", template_info.get("path", "") or "未配置模板，将使用内置报告。")
    check("glossary", "pass" if glossary else "warn", "已配置业务词汇。" if glossary else "未配置 glossary，glossary_hits 会为空。")
    check("cache", "pass", f"进程内短期缓存 TTL={cache.ttl_seconds}s。", cache.stats())
    bypass_feedback = escalation.walkthrough_recent_bypass_feedback(store, SESSION_EVENTS_FILE)
    check(
        "agent_bypass_feedback",
        "warn" if bypass_feedback["suspected_bypasses"] else "pass",
        "近期日志发现绕过 walkthrough 的低效定位动作。" if bypass_feedback["suspected_bypasses"] else "近期日志未发现明显绕过动作。",
        bypass_feedback,
    )

    sample: Dict[str, Any] = {}
    if symbol:
        sample = walkthrough_provider(
            workspace_file, symbol, depth=4, limit=40, project=project,
            view="compact", budget="small", report_level=report_level,
        )
        check("sample_found", "pass" if sample.get("found") else "fail", symbol)
        required_fields = ["schema_version", "fields_contract", "summary_lines", "answer_markdown", "agent_usage_policy"]
        missing = [field for field in required_fields if not sample.get(field)]
        check("sample_contract", "pass" if not missing else "fail", "核心 walkthrough 字段契约检查。", {"missing": missing})
        freshness = sample.get("index_freshness", {}) or {}
        check("sample_freshness", "warn" if freshness.get("index_stale") else "pass", freshness.get("recommended_action", "索引未发现 stale 主链路文件。"), freshness)

    status = "pass"
    if any(item["status"] == "fail" for item in checks):
        status = "fail"
    elif any(item["status"] == "warn" for item in checks):
        status = "warn"
    return {
        "workspace": config.workspace,
        "workspace_file": str(workspace_file),
        "status": status,
        "checks": checks,
        "index_files": index_files,
        "template": {key: value for key, value in template_info.items() if key != "template"},
        "glossary_terms": len(glossary),
        "recent_agent_bypass_feedback": bypass_feedback,
        "sample": sample,
    }


def evaluate_walkthrough(
    workspace_file: str | Path,
    symbol: str,
    *,
    project: str = "",
    report_level: str = "standard",
    walkthrough_provider: WalkthroughProvider,
) -> Dict[str, Any]:
    result = walkthrough_provider(
        workspace_file, symbol, depth=4, limit=40, project=project,
        view="compact", budget="small", report_level=report_level,
    )
    return {
        "workspace_file": str(escalation.resolve_walkthrough_workspace_input(workspace_file)),
        "symbol": symbol,
        **evaluate_walkthrough_result(result),
        "result": result,
    }


def export_walkthrough(
    workspace_file: str | Path,
    symbol: str,
    *,
    project: str = "",
    report_level: str = "deep",
    title: str = "",
    walkthrough_provider: WalkthroughProvider,
) -> Dict[str, Any]:
    workspace_file = escalation.resolve_walkthrough_workspace_input(workspace_file)
    config, _ = load_context(workspace_file)
    store = WorkspaceStore(workspace_file)
    result = walkthrough_provider(
        workspace_file, symbol, depth=4, limit=80, project=project,
        view="compact", budget="medium", report_level=report_level,
    )
    filename = f"walkthroughs/{slugify_walkthrough_symbol(symbol)}.md"
    path = _safe_path(store.artifacts_dir, filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    markdown = render_walkthrough_markdown(
        config.workspace,
        symbol,
        result,
        read_targets=answer.method_walkthrough_read_targets_text(result),
        title=title,
    )
    path.write_text(markdown, encoding="utf-8")
    return {
        "workspace": config.workspace,
        "symbol": symbol,
        "exported": True,
        "artifact": filename,
        "path": str(path),
        "bytes": len(markdown.encode("utf-8")),
        "result_summary": {
            "found": result.get("found", False),
            "schema_version": result.get("schema_version", 0),
            "summary_lines": len(result.get("summary_lines", []) or []),
            "branch_outline": len(result.get("branch_outline", []) or []),
        },
    }
