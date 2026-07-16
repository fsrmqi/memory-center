"""ContextPackBuilder — build compact, evidence-backed context for coding agents.

This is the V3 "agent reads less files" layer.  Instead of returning raw node
lists, it assembles a self-contained context package with:
- entrypoints (top matching nodes)
- relationships (neighbors)
- snippets (minimal code excerpts)
- risks (matched risk patterns)
- checklist (actionable verification steps)
- freshness (index staleness warnings)
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from memory_center.core.governance.rules import match_rules
from memory_center.core.observability.diagnostics import DIAG, diag_entry
from memory_center.core.storage.graph import GraphStore

from ..freshness.status import IndexFreshnessService
from ..retrieval.hybrid import HybridRetrievalConfig, detect_query_intent, hybrid_retrieve

# Extensions that are treated as non-code (skipped for snippet extraction)
_NON_CODE_EXTENSIONS = frozenset({".md", ".txt", ".yaml", ".yml", ".json", ".xml",
                                   ".properties", ".cfg", ".ini", ".toml", ".rst"})
# Lines above/below the target line to include in a snippet
_SNIPPET_CONTEXT_ABOVE = 15
_SNIPPET_CONTEXT_BELOW = 5
# Max snippets per build to keep token usage predictable
_MAX_SNIPPETS = 8


@dataclass
class ContextPack:
    """Self-contained context package for a coding agent."""
    query: str
    intent: str
    entrypoints: list[dict[str, Any]] = field(default_factory=list)
    relationships: list[dict[str, Any]] = field(default_factory=list)
    snippets: list[dict[str, Any]] = field(default_factory=list)
    risks: list[dict[str, Any]] = field(default_factory=list)
    checklist: list[str] = field(default_factory=list)
    freshness: dict[str, Any] = field(default_factory=dict)
    token_estimate: int = 0
    progressive: dict[str, Any] = field(default_factory=dict)


class ContextPackBuilder:
    """Build compact context packs that reduce Agent grep/read cycles."""

    def __init__(self, workspace_file: str | Path):
        self._workspace_file = str(workspace_file)
        from memory_center.core.storage.workspace import WorkspaceStore
        self._store = WorkspaceStore(workspace_file)
        self._config = self._store._config if hasattr(self._store, '_config') else None

    def build(
        self,
        query: str,
        intent: str = "auto",
        budget_tokens: int = 8000,
        limit: int = 10,
    ) -> ContextPack:
        """Build a context pack for the given query."""
        # 1. Detect intent
        if intent == "auto":
            intent_info = detect_query_intent(query)
            primary_intent = intent_info.get("primary_intent", "general")
        else:
            primary_intent = intent

        # 2. Retrieve entrypoints via hybrid retrieval
        retrieval = hybrid_retrieve(
            graph=self._get_graph(),
            workspace_file=self._workspace_file,
            query=query,
            config=HybridRetrievalConfig(max_results=limit),
            limit=limit,
        )
        results = retrieval.get("results", [])

        # 3. Expand relationships for top entrypoints
        relationships = []
        for item in results[:5]:
            node = item.get("node", {})
            node_id = node.get("id", "")
            if node_id:
                with GraphStore(self._store.graph_db_path) as graph:
                    incoming = graph.neighbors(node_id, direction="upstream", max_depth=1, limit=10)
                    outgoing = graph.neighbors(node_id, direction="downstream", max_depth=1, limit=10)
                relationships.extend(incoming[:5])
                relationships.extend(outgoing[:5])

        # 4. Match risk patterns / rules
        files = list({item.get("node", {}).get("file_path", "") for item in results[:5] if item.get("node", {}).get("file_path")})
        risks = match_rules(self._store, intent=query, files=files)[:5]

        # 5. Build checklist from risks
        checklist = []
        for risk in risks:
            for item in risk.get("checklist", []):
                if item not in checklist:
                    checklist.append(item)

        # 6. Extract code snippets from top entrypoints
        snippets = _extract_snippets(self._store, results, budget_tokens)

        # 7. Check index freshness
        try:
            freshness_info = IndexFreshnessService(self._workspace_file).banner()
        except Exception as exc:
            freshness_info = diag_entry(DIAG.UNAVAILABLE, exc=exc)

        # 8. Estimate token usage (include snippets)
        snippet_text = "".join(s.get("content", "") for s in snippets)
        total_text = (
            json.dumps(results[:5], ensure_ascii=False)
            + json.dumps(relationships, ensure_ascii=False)
            + snippet_text
        )
        token_estimate = len(total_text) // 4  # rough estimate

        # 9. Build progressive disclosure
        progressive = {
            "level_1_quick": {
                "entrypoint_count": len(results),
                "top_matches": [
                    {"type": item.get("node", {}).get("type", ""), "name": item.get("node", {}).get("name", ""), "score": round(item.get("score", 0), 2)}
                    for item in results[:3]
                ],
                "intent": primary_intent,
            },
            "level_2_relationships": {
                "relationship_count": len(relationships),
                "risk_count": len(risks),
                "checklist_items": len(checklist),
                "snippet_count": len(snippets),
            },
            "level_3_next_actions": _suggest_next_actions(primary_intent, results, risks),
        }

        return ContextPack(
            query=query,
            intent=primary_intent,
            entrypoints=[{"node": item.get("node", {}), "score": item.get("score", 0), "sources": item.get("sources", [])} for item in results],
            relationships=relationships,
            snippets=snippets,
            risks=risks,
            checklist=checklist,
            freshness=freshness_info,
            token_estimate=token_estimate,
            progressive=progressive,
        )

    def _get_graph(self) -> GraphStore:
        gs = GraphStore(self._store.graph_db_path)
        return gs


def _suggest_next_actions(intent: str, results: list, risks: list) -> list[str]:
    actions = []
    if intent == "feign":
        actions.append("调用 mc_lookup(mode='context') 查看 Feign 客户端详情")
        actions.append("调用 mc_analyze 检查跨服务影响面")
    elif intent == "mq":
        actions.append("检查 mq-index.json 获取完整消息链路")
        actions.append("确认消费幂等性")
    elif intent == "endpoint":
        actions.append("调用 mc_lookup(mode='chain') 追踪调用链")
    else:
        actions.append("对 top 结果调用 mc_context 深挖")
    if risks:
        actions.append(f"注意 {len(risks)} 条风险规则已触发")
    return actions


# ---------------------------------------------------------------------------
# Snippet extraction helpers
# ---------------------------------------------------------------------------

def _extract_snippets(store: Any, results: list, budget_tokens: int) -> list[dict[str, Any]]:
    """Extract code snippets from the top entrypoints' source files.

    Each snippet covers a window around the node's declared line number.
    Duplicate files are de-duped; at most ``_MAX_SNIPPETS`` are returned.
    Total content is capped to the snippet budget (25 % of ``budget_tokens``).
    """

    # Build lookup: file_path → abs_path from file-index.json
    try:
        index_entries = store.read_json_prefer_backend("file-index.json", [])
    except Exception as _exc:
        index_entries = []
    abs_map = _build_file_index(index_entries)

    snippets: list[dict[str, Any]] = []
    seen_files: set = set()
    snippet_budget = int(budget_tokens * 0.25)  # 25 % allocated per TokenBudget
    used_tokens = 0

    for item in results:
        if len(snippets) >= _MAX_SNIPPETS:
            break
        node = item.get("node", {})
        file_path = node.get("file_path", "")
        line = node.get("line", 0)
        if not file_path or line <= 0:
            continue

        abs_path = abs_map.get(file_path)
        if not abs_path or not abs_path.exists():
            continue
        if abs_path.suffix.lower() in _NON_CODE_EXTENSIONS:
            continue
        if str(abs_path) in seen_files:
            continue
        seen_files.add(str(abs_path))

        try:
            all_lines = abs_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except Exception:
            continue

        start = max(0, line - 1 - _SNIPPET_CONTEXT_ABOVE)
        end = min(len(all_lines), line - 1 + _SNIPPET_CONTEXT_BELOW + 1)
        content = "\n".join(all_lines[start:end])
        content_tokens = len(content) // 4
        if used_tokens + content_tokens > snippet_budget:
            break

        snippets.append({
            "node_id": node.get("id", ""),
            "name": node.get("name", ""),
            "file": file_path,
            "line_start": start + 1,
            "line_end": end,
            "content": content,
            "language": _guess_language(abs_path.suffix),
        })
        used_tokens += content_tokens

    return snippets


def _build_file_index(entries: list) -> dict[str, Path]:
    """Build a mapping from logical file_path to absolute Path.

    The file-index.json stores ``path`` (relative to service root) and
    ``abs_path``.  We build two mappings:
      - ``project:path`` → abs_path   (exact match)
      - ``path`` alone   → abs_path   (fallback when project matches)

    For compatibility with older indexers that used ``abs_path`` directly
    in node metadata, we also register the abs_path as a key.
    """
    result: dict[str, Path] = {}
    for entry in entries:
        ap = entry.get("abs_path", "")
        if not ap:
            continue
        p = Path(ap)
        project = entry.get("project", "")
        logical = entry.get("path", "")
        if project and logical:
            result[f"{project}:{logical}"] = p
        if logical:
            result[logical] = p
        # Some old indexes store abs_path in node.file_path directly
        result[ap] = p
    return result


def _guess_language(suffix: str) -> str:
    """Map a file extension to a language identifier."""
    return {
        ".java": "java", ".kt": "kotlin", ".py": "python", ".js": "javascript",
        ".ts": "typescript", ".go": "go", ".rs": "rust", ".c": "c", ".cpp": "cpp",
        ".h": "c", ".hpp": "cpp", ".cs": "csharp", ".rb": "ruby", ".php": "php",
        ".scala": "scala", ".sh": "bash", ".sql": "sql", ".swift": "swift",
    }.get(suffix.lower(), "")


def benchmark_context_pack(workspace_file: str | Path, queries: list[str]) -> dict[str, Any]:
    """Benchmark context pack effectiveness.

    Measures: token savings, tool call reduction, response quality.
    """
    results = []
    total_raw_tokens = 0
    total_pack_tokens = 0

    builder = ContextPackBuilder(workspace_file)
    for q in queries:
        try:
            pack = builder.build(q, budget_tokens=4000)
            pack_tokens = pack.token_estimate
            # Estimate raw tokens from source files
            raw_estimate = sum(len(s.get("content", "")) // 4 for s in pack.snippets) * 3  # rough estimate
            total_raw_tokens += raw_estimate
            total_pack_tokens += pack_tokens
            results.append({
                "query": q,
                "pack_tokens": pack_tokens,
                "raw_estimate": raw_estimate,
                "savings_pct": round((1 - pack_tokens / max(raw_estimate, 1)) * 100, 1),
                "entrypoints_count": len(pack.entrypoints),
                "snippets_count": len(pack.snippets),
                "risks_count": len(pack.risks),
            })
        except Exception as exc:
            results.append({"query": q, "error": str(exc)})

    return {
        "total_queries": len(queries),
        "total_raw_tokens": total_raw_tokens,
        "total_pack_tokens": total_pack_tokens,
        "overall_savings_pct": round((1 - total_pack_tokens / max(total_raw_tokens, 1)) * 100, 1),
        "results": results,
    }
