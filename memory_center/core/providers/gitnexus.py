"""GitNexus 的受限只读 CLI 适配器。"""
from __future__ import annotations

import shutil
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

_Runner = Callable[..., subprocess.CompletedProcess[str]]
_MAX_OUTPUT_CHARS = 12_000
_ACTION_TIMEOUTS = {
    "status": 5.0,
    "query": 8.0,
    "context": 8.0,
    "impact": 12.0,
    "trace": 12.0,
    "detect_changes": 12.0,
    "check": 20.0,
    "analyze": 1_800.0,
    "clean": 60.0,
}


class GitNexusProvider:
    """GitNexus 的固定命令适配器，读操作自动执行，写操作需要确认。"""

    name = "gitnexus"

    def __init__(self, runner: _Runner = subprocess.run, executable: str | None = None) -> None:
        self._runner = runner
        self._executable = executable or shutil.which("gitnexus")

    def probe(self, root: str | Path, *, timeout_seconds: float = 2.0) -> dict[str, Any]:
        root_path = Path(root).expanduser().resolve()
        if not self._executable:
            return self._unavailable(root_path, "gitnexus_not_installed")
        result = self._run([self._executable, "status"], root_path, timeout_seconds)
        if result["status"] != "ready":
            return result
        output = result["output"].lower()
        if any(marker in output for marker in ("not indexed", "no index", "not found")):
            result.update(status="unavailable", reason="gitnexus_index_not_found")
        return result

    def lookup(
        self,
        root: str | Path,
        query: str,
        *,
        target: str = "",
        intent: str = "",
        limit: int = 8,
        timeout_seconds: float = 5.0,
    ) -> dict[str, Any]:
        root_path = Path(root).expanduser().resolve()
        probe = self.probe(root_path)
        if probe["status"] != "ready":
            return probe
        bounded_limit = max(1, min(int(limit), 12))
        if target.strip():
            argv = [self._executable, "context", target.strip()]
        else:
            argv = [self._executable, "query", (query or intent).strip(), "--limit", str(bounded_limit)]
            if intent.strip():
                argv.extend(["--context", intent.strip()[:500]])
        result = self._run(argv, root_path, timeout_seconds)
        result["operation"] = "context" if target.strip() else "query"
        result["provider"] = self.name
        result["scope_checked"] = {"root": str(root_path), "limit": bounded_limit}
        return result

    def action_descriptors(self) -> list[dict[str, Any]]:
        """返回固定操作的权限与输入契约，不暴露任意 argv。"""
        return [
            {"action": "status", "capability": "code_navigation", "mode": "read_only", "confirmation_required": False},
            {"action": "query", "capability": "code_navigation", "mode": "read_only", "confirmation_required": False},
            {"action": "context", "capability": "symbol_context", "mode": "read_only", "confirmation_required": False},
            {"action": "impact", "capability": "impact_navigation", "mode": "read_only", "confirmation_required": False},
            {"action": "trace", "capability": "path_navigation", "mode": "read_only", "confirmation_required": False},
            {"action": "detect_changes", "capability": "change_detection", "mode": "read_only", "confirmation_required": False},
            {"action": "check", "capability": "graph_validation", "mode": "read_only", "confirmation_required": False},
            {"action": "analyze", "capability": "index_refresh", "mode": "controlled_write", "confirmation_required": True},
            {"action": "clean", "capability": "index_cleanup", "mode": "destructive", "confirmation_required": True},
        ]

    def execute(
        self,
        root: str | Path,
        action: str,
        *,
        query: str = "",
        target: str = "",
        confirm: bool = False,
        force: bool = False,
        limit: int = 8,
        depth: int = 3,
    ) -> dict[str, Any]:
        """执行预定义 GitNexus 操作；绝不接受调用方传入的 argv。"""
        root_path = Path(root).expanduser().resolve()
        normalized = action.strip().lower().replace("-", "_")
        descriptors = {item["action"]: item for item in self.action_descriptors()}
        descriptor = descriptors.get(normalized)
        if descriptor is None:
            return self._unavailable(root_path, "gitnexus_action_not_allowed")
        if descriptor["confirmation_required"] and not confirm:
            return {
                "provider": self.name,
                "status": "confirmation_required",
                "action": normalized,
                "mode": descriptor["mode"],
                "scope_checked": {"root": str(root_path)},
                "next_action": f"确认后以 confirm=true 执行 GitNexus {normalized}。",
            }
        if not self._executable:
            return self._unavailable(root_path, "gitnexus_not_installed")
        try:
            argv = self._action_argv(normalized, query=query, target=target, force=force, limit=limit, depth=depth)
        except ValueError as exc:
            return {
                "provider": self.name,
                "status": "invalid_input",
                "reason": str(exc),
                "action": normalized,
                "scope_checked": {"root": str(root_path)},
            }
        result = self._run([self._executable, *argv], root_path, _ACTION_TIMEOUTS[normalized])
        result.update(
            action=normalized,
            mode=descriptor["mode"],
            scope_checked={"root": str(root_path), "limit": max(1, min(int(limit), 12)), "depth": max(1, min(int(depth), 5))},
        )
        return result

    @staticmethod
    def _action_argv(action: str, *, query: str, target: str, force: bool, limit: int, depth: int) -> list[str]:
        bounded_limit = max(1, min(int(limit), 12))
        bounded_depth = max(1, min(int(depth), 5))
        if action == "status":
            return ["status"]
        if action == "query":
            if not query.strip():
                raise ValueError("query is required for GitNexus query")
            return ["query", query.strip(), "--limit", str(bounded_limit)]
        if action == "context":
            return ["context", target.strip()] if target.strip() else ["context"]
        if action == "impact":
            if not target.strip():
                raise ValueError("target is required for GitNexus impact")
            return ["impact", target.strip(), "--depth", str(bounded_depth), "--limit", str(bounded_limit)]
        if action == "trace":
            symbols = [item.strip() for item in target.split("->") if item.strip()]
            if len(symbols) != 2:
                raise ValueError("target must use '<from> -> <to>' for GitNexus trace")
            return ["trace", symbols[0], symbols[1]]
        if action == "detect_changes":
            return ["detect-changes"]
        if action == "check":
            return ["check"]
        if action == "analyze":
            return ["analyze", "--index-only", *( ["--force"] if force else [])]
        if action == "clean":
            return ["clean", "--force"]
        raise ValueError("gitnexus_action_not_allowed")

    def _run(self, argv: list[str], cwd: Path, timeout_seconds: float) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            completed = self._runner(
                argv,
                cwd=str(cwd),
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return self._unavailable(cwd, "gitnexus_timeout", duration_ms=round((time.perf_counter() - started) * 1000, 2))
        except OSError:
            return self._unavailable(cwd, "gitnexus_unavailable", duration_ms=round((time.perf_counter() - started) * 1000, 2))
        output = (completed.stdout or completed.stderr or "").strip()[:_MAX_OUTPUT_CHARS]
        if completed.returncode != 0:
            return {
                "provider": self.name,
                "status": "unavailable",
                "reason": "gitnexus_command_failed",
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                "output": output,
            }
        return {
            "provider": self.name,
            "status": "ready",
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            "output": output,
        }

    def _unavailable(self, root: Path, reason: str, *, duration_ms: float = 0.0) -> dict[str, Any]:
        return {
            "provider": self.name,
            "status": "unavailable",
            "reason": reason,
            "duration_ms": duration_ms,
            "scope_checked": {"root": str(root)},
        }
