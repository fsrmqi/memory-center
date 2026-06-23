"""Drill-down navigation — enhanced timeline/ref/task navigation.

This module implements Phase D of NEXT_PHASE_MASTER_PLAN:
- Stronger ref expansion and reverse jumping
- Enhanced task → timeline → receipt → ref drill-down
- Stronger summary layer for handoff/resume
- Facade output prioritizes summary, details expand via ref
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Set

from ..backend.query import UnifiedBackendQuery
from ..quality import build_quality_summary
from ..store import WorkspaceStore


class DrillDownNavigator:
    """Enhanced navigation through timeline, refs, and tasks."""

    def __init__(self, workspace_file: str | Path):
        self.workspace_file = Path(workspace_file)
        self.store = WorkspaceStore(workspace_file)
        self.backend = UnifiedBackendQuery(self.store.memory_db_path)

    def close(self) -> None:
        self.backend.close()

    def __enter__(self) -> "DrillDownNavigator":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ---- Ref expansion -------------------------------------------------------

    def expand_ref(self, ref_id: str, include_related: bool = True) -> Dict[str, Any]:
        """Expand a ref with full details and related items.

        Provides progressive disclosure:
        - Level 1: Summary (always shown)
        - Level 2: Details (on demand)
        - Level 3: Related items (on demand)
        """
        from ..orchestrator.common import _resolve_memory_ref

        resolved = _resolve_memory_ref(self.store, ref_id)
        if not resolved:
            return {
                "ref_id": ref_id,
                "found": False,
                "summary": "Ref not found",
            }

        raw = resolved.get("raw")
        kind = resolved.get("kind", "unknown")
        summary = resolved.get("summary", "")

        # Build progressive disclosure
        result = {
            "ref_id": ref_id,
            "found": True,
            "kind": kind,
            "summary": summary,
            "level_1_summary": self._build_ref_summary(raw, kind),
            "level_2_details": self._build_ref_details(raw, kind),
            "level_3_related": [] if not include_related else self._find_related_refs(ref_id, raw, kind),
        }

        # Build reverse links
        result["reverse_links"] = self._build_reverse_links(raw, kind)

        return result

    def _build_ref_summary(self, raw: Any, kind: str) -> Dict[str, Any]:
        """Build Level 1 summary for a ref."""
        if not isinstance(raw, dict):
            return {"type": kind, "value": str(raw)[:200] if raw else ""}

        if kind == "session_event":
            return {
                "type": "session_event",
                "event_type": raw.get("event_type", raw.get("type", "")),
                "timestamp": raw.get("created_at", raw.get("timestamp", "")),
                "session_id": raw.get("session_id", ""),
            }
        elif kind == "write_receipt":
            return {
                "type": "write_receipt",
                "file_path": raw.get("file_path", ""),
                "operation": raw.get("operation", ""),
                "timestamp": raw.get("created_at", ""),
            }
        elif kind == "token_gain":
            return {
                "type": "token_gain",
                "tool_name": raw.get("tool_name", ""),
                "savings_pct": raw.get("savings_pct", 0),
                "timestamp": raw.get("timestamp", ""),
            }
        else:
            return {
                "type": kind,
                "keys": list(raw.keys())[:10],
                "preview": str(raw)[:200],
            }

    def _build_ref_details(self, raw: Any, kind: str) -> Dict[str, Any]:
        """Build Level 2 details for a ref."""
        if not isinstance(raw, dict):
            return {}

        if kind == "session_event":
            return {
                "full_payload": raw.get("payload", {}),
                "session_id": raw.get("session_id", ""),
                "project": raw.get("project", ""),
                "metadata": raw.get("metadata", {}),
            }
        elif kind == "write_receipt":
            return {
                "changes": raw.get("changes", []),
                "context": raw.get("context", {}),
                "metadata": raw.get("metadata", {}),
            }
        elif kind == "token_gain":
            return {
                "raw_tokens": raw.get("raw_tokens", 0),
                "compact_tokens": raw.get("compact_tokens", 0),
                "saved_tokens": raw.get("saved_tokens", 0),
                "budget": raw.get("budget", ""),
                "view": raw.get("view", ""),
            }
        else:
            return raw

    def _find_related_refs(self, ref_id: str, raw: Any, kind: str) -> List[Dict[str, Any]]:
        """Find related refs based on context."""
        related = []

        if not isinstance(raw, dict):
            return related

        # Find by session_id
        session_id = raw.get("session_id", "")
        if session_id:
            session_refs = self.backend.query_session_events(session_id=session_id, limit=10)
            for ref in session_refs:
                if ref.get("record_id") != ref_id:
                    related.append({
                        "ref_id": ref.get("record_id", ""),
                        "kind": "session_event",
                        "relation": "same_session",
                        "summary": ref.get("type", ""),
                    })

        # Find by task_id
        task_id = raw.get("task_id", "")
        if task_id:
            # Search for other items with same task_id
            records = self.backend.query_records(limit=50)
            for record in records.get("records", []):
                payload = record.get("payload", {})
                if payload.get("task_id") == task_id and record.get("record_id") != ref_id:
                    related.append({
                        "ref_id": record.get("record_id", ""),
                        "kind": record.get("type", ""),
                        "relation": "same_task",
                        "summary": payload.get("summary", str(payload)[:100]),
                    })

        return related[:10]

    def _build_reverse_links(self, raw: Any, kind: str) -> List[Dict[str, Any]]:
        """Build reverse links (what points TO this ref)."""
        links = []

        if not isinstance(raw, dict):
            return links

        # Extract timeline link
        session_id = raw.get("session_id") or (raw.get("event", {}) or {}).get("session_id", "")
        task_id = raw.get("task_id") or (raw.get("event", {}) or {}).get("task_id", "")

        if session_id:
            links.append({
                "type": "timeline",
                "label": f"查看 session {session_id[:8]}... 的时间线",
                "target": f"/ui/timeline?session_id={session_id}",
            })

        if task_id:
            links.append({
                "type": "task",
                "label": f"查看 task {task_id[:8]}... 的详情",
                "target": f"/ui/task?task_id={task_id}",
            })

        return links

    # ---- Timeline drill-down -------------------------------------------------

    def drill_timeline(
        self,
        session_id: str = "",
        task_id: str = "",
        start_event_id: str = "",
        limit: int = 50,
    ) -> Dict[str, Any]:
        """Drill into timeline with context preservation.

        Supports:
        - Session-based drill-down
        - Task-based drill-down
        - Event-based drill-down (from a specific point)
        """
        if not session_id and not task_id:
            return {"error": "Provide session_id or task_id"}

        # Get events
        events = self.backend.query_timeline(
            session_id=session_id,
            task_id=task_id,
            limit=limit * 2,
        )

        if not events:
            return {
                "session_id": session_id,
                "task_id": task_id,
                "found": False,
                "events": [],
            }

        # If starting from a specific event, find its position
        start_idx = 0
        if start_event_id:
            for idx, event in enumerate(events):
                if event.get("record_id") == start_event_id:
                    start_idx = max(0, idx - 5)  # Show 5 events before
                    break

        # Build context window
        context_events = events[start_idx:start_idx + limit]

        return {
            "session_id": session_id,
            "task_id": task_id,
            "found": True,
            "total_events": len(events),
            "showing": len(context_events),
            "start_index": start_idx,
            "events": context_events,
            "summary": self._build_timeline_summary(context_events),
            "navigation": {
                "has_more_before": start_idx > 0,
                "has_more_after": start_idx + limit < len(events),
                "before_count": start_idx,
                "after_count": max(0, len(events) - start_idx - limit),
            },
        }

    def _build_timeline_summary(self, events: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Build summary of timeline events."""
        event_types: Dict[str, int] = {}
        tool_calls: List[str] = []

        for event in events:
            etype = event.get("type", "unknown")
            event_types[etype] = event_types.get(etype, 0) + 1

            # Extract tool calls
            payload = event.get("payload", {})
            if etype == "tool_call":
                tool_name = payload.get("tool_name", "")
                if tool_name:
                    tool_calls.append(tool_name)

        return {
            "event_count": len(events),
            "event_types": event_types,
            "tool_calls": tool_calls[:10],
            "first_event": events[-1].get("created_at", "") if events else "",
            "last_event": events[0].get("created_at", "") if events else "",
        }

    # ---- Task drill-down -----------------------------------------------------

    def drill_task(self, task_id: str) -> Dict[str, Any]:
        """Drill into a task with full context.

        Returns:
        - Task summary
        - Timeline events
        - Write receipts
        - Token usage
        """
        # Get all related records
        session_events = self.backend.query_session_events(limit=500)
        task_events = [
            e for e in session_events
            if e.get("payload", {}).get("task_id") == task_id
            or e.get("task_id") == task_id
        ]

        write_receipts = self.backend.query_write_receipts(limit=100)
        task_receipts = [
            r for r in write_receipts
            if r.get("payload", {}).get("task_id") == task_id
        ]

        # Build task summary
        summary = self._build_task_summary(task_id, task_events, task_receipts)

        result = {
            "task_id": task_id,
            "found": len(task_events) > 0 or len(task_receipts) > 0,
            "summary": summary,
            "timeline": task_events[:20],
            "write_receipts": task_receipts[:10],
            "drill_down": {
                "timeline": f"使用 drill_timeline(task_id='{task_id}') 查看完整时间线",
                "refs": "对 timeline 中的 record_id 调用 expand_ref 查看详情",
            },
        }
        evidence = [
            {"evidence_type": "fact", "confidence": 1.0}
            for _ in task_events + task_receipts
        ]
        result["_quality"] = build_quality_summary(evidence, freshness_status="unknown")
        return result

    def _build_task_summary(
        self,
        task_id: str,
        events: List[Dict[str, Any]],
        receipts: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Build comprehensive task summary."""
        event_types: Dict[str, int] = {}
        for event in events:
            etype = event.get("type", "unknown")
            event_types[etype] = event_types.get(etype, 0) + 1

        files_changed: Set[str] = set()
        for receipt in receipts:
            file_path = receipt.get("payload", {}).get("file_path", "")
            if file_path:
                files_changed.add(file_path)

        return {
            "task_id": task_id,
            "event_count": len(events),
            "receipt_count": len(receipts),
            "event_types": event_types,
            "files_changed": list(files_changed)[:20],
            "first_activity": events[-1].get("created_at", "") if events else "",
            "last_activity": events[0].get("created_at", "") if events else "",
        }

    # ---- Handoff/Resume enhancement ------------------------------------------

    def build_handoff_context(
        self,
        session_id: str,
        include_refs: bool = True,
    ) -> Dict[str, Any]:
        """Build comprehensive handoff context for model switching.

        Returns summary suitable for passing to a new model session.
        """
        # Get session summary
        session_summary = self.backend.get_session_summary(session_id)

        # Get recent events
        events = self.backend.query_session_events(session_id=session_id, limit=50)

        # Build context
        context = {
            "session_id": session_id,
            "session_summary": session_summary,
            "recent_events": events[:10],
            "key_points": self._extract_key_points(events),
            "open_questions": self._extract_open_questions(events),
            "next_steps": self._extract_next_steps(events),
        }

        if include_refs:
            # Get related refs
            context["related_refs"] = self._find_session_refs(session_id)

        return context

    def _extract_key_points(self, events: List[Dict[str, Any]]) -> List[str]:
        """Extract key points from session events."""
        points = []

        for event in events[:20]:
            payload = event.get("payload", {})
            etype = event.get("type", "")

            if etype == "tool_call":
                tool = payload.get("tool_name", "")
                if tool in {"memory_symbol_tool", "memory_context_tool", "workspace_trace_tool"}:
                    query = payload.get("query", payload.get("target", ""))
                    if query:
                        points.append(f"查询了: {query}")

            elif etype == "write":
                file_path = payload.get("file_path", "")
                if file_path:
                    points.append(f"修改了: {file_path}")

        return points[:10]

    def _extract_open_questions(self, events: List[Dict[str, Any]]) -> List[str]:
        """Extract open questions from session events."""
        questions = []

        for event in events:
            payload = event.get("payload", {})
            etype = event.get("type", "")

            if etype == "user_message":
                content = payload.get("content", "")
                if "?" in content or "？" in content:
                    questions.append(content[:100])

        return questions[-5:]

    def _extract_next_steps(self, events: List[Dict[str, Any]]) -> List[str]:
        """Extract suggested next steps from session context."""
        steps = []

        # Look for TODO/FIXME in write receipts
        for event in events:
            payload = event.get("payload", {})
            if event.get("type") == "write":
                content = payload.get("content", "")
                if "TODO" in content or "FIXME" in content:
                    steps.append(f"处理 {payload.get('file_path', '')} 中的 TODO/FIXME")

        # Look for failed tool calls
        for event in events:
            if event.get("type") == "tool_error":
                steps.append(f"重试失败的工具调用: {event.get('payload', {}).get('tool_name', '')}")

        return steps[:5]

    def _find_session_refs(self, session_id: str) -> List[Dict[str, Any]]:
        """Find all refs associated with a session."""
        refs = []

        # Query session events
        events = self.backend.query_session_events(session_id=session_id, limit=100)
        for event in events:
            record_id = event.get("record_id", "")
            if record_id:
                refs.append({
                    "ref_id": record_id,
                    "kind": "session_event",
                    "summary": event.get("type", ""),
                })

        return refs[:20]

    # ---- Summary layer for facade --------------------------------------------

    def build_facade_summary(
        self,
        intent: str,
        results: Dict[str, Any],
        max_refs: int = 5,
    ) -> Dict[str, Any]:
        """Build facade-friendly summary with progressive disclosure.

        Prioritizes:
        1. Quick summary (always shown)
        2. Key results (shown on request)
        3. Ref links (expandable)
        """
        return {
            "intent": intent,
            "level_1_summary": {
                "result_count": len(results.get("results", results.get("matches", []))),
                "top_match": self._extract_top_match(results),
                "quick_action": self._suggest_quick_action(intent, results),
            },
            "level_2_results": self._extract_key_results(results, max_refs),
            "level_3_refs": self._extract_ref_links(results, max_refs),
            "expand_hint": "调用 expand_ref(ref_id) 查看详情，或 drill_timeline/drill_task 深入",
        }

    def _extract_top_match(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """Extract top match from results."""
        matches = results.get("results", results.get("matches", []))
        if not matches:
            return {}

        top = matches[0]
        if isinstance(top, dict):
            node = top.get("node", top)
            return {
                "type": node.get("type", ""),
                "name": node.get("name", ""),
                "project": node.get("project", ""),
                "score": top.get("score", 0),
            }
        return {}

    def _suggest_quick_action(self, intent: str, results: Dict[str, Any]) -> str:
        """Suggest quick action based on intent and results."""
        matches = results.get("results", results.get("matches", []))

        if not matches:
            return "尝试更具体的查询"

        if "feign" in intent.lower():
            return "调用 memory_context 查看 Feign 详情"
        elif "caller" in intent.lower() or "调用" in intent:
            return "调用 memory_callers 追踪调用链"
        elif "impact" in intent.lower() or "影响" in intent:
            return "调用 mc_analyze 检查影响面"
        else:
            return "对 top 结果调用 memory_context 深挖"

    def _extract_key_results(self, results: Dict[str, Any], max_refs: int) -> List[Dict[str, Any]]:
        """Extract key results for Level 2 display."""
        matches = results.get("results", results.get("matches", []))
        key_results = []

        for match in matches[:max_refs]:
            if isinstance(match, dict):
                node = match.get("node", match)
                key_results.append({
                    "type": node.get("type", ""),
                    "name": node.get("name", ""),
                    "project": node.get("project", ""),
                    "file_path": node.get("file_path", ""),
                    "score": match.get("score", 0),
                })

        return key_results

    def _extract_ref_links(self, results: Dict[str, Any], max_refs: int) -> List[Dict[str, Any]]:
        """Extract ref links for Level 3 expansion."""
        refs = []

        matches = results.get("results", results.get("matches", []))
        for match in matches[:max_refs]:
            if isinstance(match, dict):
                node_id = match.get("node_id", match.get("node", {}).get("id", ""))
                if node_id:
                    refs.append({
                        "ref_id": node_id,
                        "expand_hint": f"expand_ref('{node_id}')",
                    })

        return refs
