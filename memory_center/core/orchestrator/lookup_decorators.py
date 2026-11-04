"""Post-retrieval result decorators with no retrieval side effects."""
from __future__ import annotations

from typing import Any, Callable


def apply_project_scope(
    result: dict[str, Any],
    *,
    effective_project: str,
    shard_available: bool,
    intent: dict[str, Any],
    project_matches: Callable[[str, str], bool],
    rebuild_summary: Callable[[list[dict[str, Any]], dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    """Strictly filter explicit/inferred project hits and rebuild result summaries."""
    if not effective_project or not shard_available:
        return result
    results = result.get("results", [])
    project_results = [item for item in results if project_matches(effective_project, item.get("node", {}).get("project", ""))]
    if project_results:
        for item in project_results:
            item["score"] = item.get("score", 0) * 2.0
            item["_project_boost"] = True
        project_results.sort(key=lambda item: item.get("score", 0), reverse=True)
        rebuilt = rebuild_summary(project_results, intent)
        result.update({
            "results": project_results,
            "total_found": rebuilt["total_found"],
            "returned": rebuilt["returned"],
            "retrieval_summary": rebuilt["retrieval_summary"],
            "progressive": rebuilt["progressive"],
        })
        return result
    rebuilt = rebuild_summary([], intent)
    result.update({"results": [], "total_found": 0, "returned": 0,
                   "retrieval_summary": rebuilt["retrieval_summary"], "progressive": rebuilt["progressive"]})
    return result


__all__ = ["apply_project_scope"]
