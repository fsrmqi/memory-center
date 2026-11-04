"""Completion status helpers for walkthrough-style results."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

__all__ = [
    "CompletionStatus",
    "evaluate_completion",
    "evaluate_walkthrough_completion",
]


@dataclass(frozen=True)
class CompletionStatus:
    """Machine-readable completion state for an indexed analysis result."""

    state: str
    terminal_anchor: str
    missing_layers: tuple[str, ...]
    stop_reason: str
    recommended_action: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "terminal_anchor": self.terminal_anchor,
            "missing_layers": list(self.missing_layers),
            "stop_reason": self.stop_reason,
            "recommended_action": self.recommended_action,
        }


def _ordered_unique(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for raw in values:
        value = str(raw or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return tuple(ordered)


def evaluate_completion(
    *,
    expected_layers: Iterable[str],
    observed_layers: Iterable[str],
    terminal_anchor: str = "",
    index_stale: bool = False,
) -> CompletionStatus:
    """Classify whether the current evidence is complete enough to stop searching."""

    expected = _ordered_unique(expected_layers)
    observed = _ordered_unique(observed_layers)
    observed_set = set(observed)
    missing = tuple(layer for layer in expected if layer not in observed_set)

    if index_stale:
        return CompletionStatus(
            state="stale",
            terminal_anchor=terminal_anchor,
            missing_layers=missing,
            stop_reason="index_not_fresh",
            recommended_action="live_read_or_reindex",
        )
    if not observed:
        return CompletionStatus(
            state="blocked",
            terminal_anchor=terminal_anchor,
            missing_layers=missing,
            stop_reason="no_layers_observed",
            recommended_action="targeted_lookup_or_reindex",
        )
    if missing:
        return CompletionStatus(
            state="partial",
            terminal_anchor=terminal_anchor,
            missing_layers=missing,
            stop_reason="missing_expected_layers",
            recommended_action="fill_missing_layers",
        )
    return CompletionStatus(
        state="complete",
        terminal_anchor=terminal_anchor,
        missing_layers=(),
        stop_reason="all_expected_layers_observed",
        recommended_action="use_current_evidence",
    )


def _anchor(item: dict[str, Any], *, class_key: str = "class", method_key: str = "method") -> str:
    cls = str(item.get(class_key) or item.get("controller") or item.get("interface") or "").strip()
    method = str(item.get(method_key) or "").strip()
    if cls and method:
        return f"{cls}#{method}"
    return cls or method


def _has_items(value: Any) -> bool:
    return isinstance(value, list) and bool(value)


def evaluate_walkthrough_completion(result: dict[str, Any]) -> dict[str, Any]:
    """Derive completion status from a method walkthrough result."""

    expected_layers: list[str] = ["entry"]
    observed: list[str] = []
    terminal_anchor = ""

    target = result.get("target", {}) or {}
    if result.get("found") and target:
        observed.append("entry")
        terminal_anchor = _anchor(target)

    if _has_items(result.get("local_service_continuations")):
        expected_layers.append("local_service")
        observed.append("local_service")
        first_local = (result.get("local_service_continuations") or [{}])[0].get("target", {}) or {}
        terminal_anchor = _anchor(first_local) or terminal_anchor

    if _has_items(result.get("same_class_method_continuations")):
        expected_layers.append("same_class_method")
        observed.append("same_class_method")
        first_same = (result.get("same_class_method_continuations") or [{}])[0].get("target", {}) or {}
        terminal_anchor = _anchor(first_same) or terminal_anchor

    feigns = result.get("feign_continuations") or []
    if feigns:
        expected_layers.extend(["remote_feign", "server_controller"])
        observed.append("remote_feign")
        first_feign = feigns[0] or {}
        terminal_anchor = _anchor(first_feign, class_key="interface") or terminal_anchor

    for feign in feigns:
        server_walkthroughs = feign.get("server_walkthroughs") or []
        if server_walkthroughs and "server_controller" not in observed:
            observed.append("server_controller")
        for server in server_walkthroughs:
            terminal_anchor = _anchor(server, class_key="controller") or terminal_anchor
            service_impls = server.get("service_impl_continuations") or []
            if service_impls and "server_impl" not in expected_layers:
                expected_layers.append("server_impl")
            if service_impls and "server_impl" not in observed:
                observed.append("server_impl")
            for impl in service_impls:
                impl_target = impl.get("target", {}) or {}
                terminal_anchor = _anchor(impl_target) or terminal_anchor
                same_methods = impl.get("same_class_method_continuations") or []
                if same_methods and "bottom_method" not in expected_layers:
                    expected_layers.append("bottom_method")
                if same_methods and "bottom_method" not in observed:
                    observed.append("bottom_method")
                for same in same_methods:
                    same_target = same.get("target", {}) or {}
                    terminal_anchor = _anchor(same_target) or terminal_anchor

    status = evaluate_completion(
        expected_layers=expected_layers,
        observed_layers=observed,
        terminal_anchor=terminal_anchor,
        index_stale=bool((result.get("index_freshness") or {}).get("index_stale")),
    )
    payload = status.to_dict()
    payload["expected_layers"] = list(expected_layers)
    payload["observed_layers"] = list(_ordered_unique(observed))
    return payload
