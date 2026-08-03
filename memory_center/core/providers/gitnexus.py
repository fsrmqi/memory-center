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


class GitNexusProvider:
    """只允许 status/query/context，不会触发 analyze 或执行任意命令。"""

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
