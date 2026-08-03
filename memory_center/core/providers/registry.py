"""受限外部能力的注册、选择和诊断。"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .gitnexus import GitNexusProvider
from .health import ProviderHealthMonitor


class ContextProvider(Protocol):
    """外部上下文 Provider 的最小接口。"""

    name: str

    def lookup(self, root: str | Path, query: str, *, target: str = "", intent: str = "", limit: int = 8) -> dict[str, Any]: ...

    def execute(self, root: str | Path, action: str, **kwargs: Any) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ProviderSpec:
    provider_id: str
    capabilities: tuple[str, ...]
    factory: Callable[[], ContextProvider]
    mutation_mode: str = "read_only"
    privacy_mode: str = "metadata_only"
    timeout_seconds: float = 5.0
    max_results: int = 12
    priority: int = 100

    def descriptor(self) -> dict[str, Any]:
        return {
            "provider": self.provider_id,
            "capabilities": list(self.capabilities),
            "mutation_mode": self.mutation_mode,
            "privacy_mode": self.privacy_mode,
            "timeout_seconds": self.timeout_seconds,
            "max_results": self.max_results,
            "priority": self.priority,
        }


class ProviderRegistry:
    """按能力、安全属性和确认状态选择 Provider。"""

    def __init__(self, specs: tuple[ProviderSpec, ...] | list[ProviderSpec] | None = None, *, health: ProviderHealthMonitor | None = None) -> None:
        self._specs = tuple(sorted(specs or (), key=lambda item: item.priority))
        self._health = health or ProviderHealthMonitor()

    def descriptors(self) -> list[dict[str, Any]]:
        return [spec.descriptor() for spec in self._specs]

    def health_snapshot(self) -> dict[str, dict[str, float | int | str]]:
        """返回进程内观测结果，供路由诊断与行动卡使用。"""
        return {spec.provider_id: self._health.snapshot(spec.provider_id) for spec in self._specs}

    def lookup(
        self,
        root: str | Path,
        query: str,
        *,
        target: str = "",
        intent: str = "",
        limit: int = 8,
        capability: str = "code_navigation",
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        candidates = sorted(
            (spec for spec in self._specs if capability in spec.capabilities),
            key=lambda spec: spec.priority + self._health.routing_penalty(spec.provider_id),
        )
        attempted: list[dict[str, str]] = []
        last_result: dict[str, Any] | None = None
        for spec in candidates:
            provider = spec.factory()
            result = provider.lookup(root, query, target=target, intent=intent, limit=min(max(1, limit), spec.max_results))
            status = str(result.get("status", "unavailable") or "unavailable")
            self._health.record(spec.provider_id, float(result.get("duration_ms", 0.0) or 0.0), status)
            attempted.append({"provider": spec.provider_id, "status": status})
            last_result = result
            if status == "ready":
                return result, {
                    "capability": capability,
                    "selected": spec.provider_id,
                    "attempted": attempted,
                    "registry": self.descriptors(),
                    "health": self.health_snapshot(),
                }
        unavailable = last_result or {
            "provider": "",
            "status": "unavailable",
            "reason": "no_ready_provider",
            "scope_checked": {"root": str(Path(root).expanduser().resolve())},
        }
        return unavailable, {
            "capability": capability,
            "selected": "",
            "attempted": attempted,
            "registry": self.descriptors(),
            "health": self.health_snapshot(),
        }

    def execute(
        self,
        root: str | Path,
        *,
        provider_id: str,
        action: str,
        query: str = "",
        target: str = "",
        confirm: bool = False,
        force: bool = False,
        limit: int = 8,
        depth: int = 3,
    ) -> dict[str, Any]:
        """通过固定 Provider 与动作名执行受控操作，禁止自由命令。"""
        spec = next((item for item in self._specs if item.provider_id == provider_id), None)
        if spec is None:
            return {"executed": False, "reason": "provider_not_registered", "provider": provider_id, "action": action}
        provider = spec.factory()
        result = provider.execute(
            root, action, query=query, target=target, confirm=confirm, force=force, limit=limit, depth=depth
        )
        self._health.record(provider_id, float(result.get("duration_ms", 0.0) or 0.0), str(result.get("status", "unavailable")))
        return {
            "executed": result.get("status") == "ready",
            "provider": provider_id,
            "action": action,
            "result": result,
            "provider_registry": self.descriptors(),
            "provider_health": self.health_snapshot(),
        }


DEFAULT_PROVIDER_REGISTRY = ProviderRegistry(
    (
        ProviderSpec(
            provider_id="gitnexus",
            capabilities=(
                "code_navigation", "symbol_context", "impact_navigation", "path_navigation",
                "change_detection", "graph_validation", "index_refresh", "index_cleanup",
            ),
            factory=GitNexusProvider,
            mutation_mode="mixed",
            priority=10,
        ),
    )
)
