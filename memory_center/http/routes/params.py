from __future__ import annotations


def _require_workspace(params: dict, default_workspace: str | None) -> str:
    value = params.get("workspace", [default_workspace])[0]
    if not value:
        raise ValueError("workspace query param is required when no default workspace is configured")
    return value


def _require_one(params: dict, key: str) -> str:
    value = params.get(key, [""])[0].strip()
    if not value:
        raise ValueError(f"{key} query param is required")
    return value


def _parse_int(params: dict, key: str, default: int, min_val: int = 1, max_val: int = 10000) -> int:
    raw = params.get(key, [str(default)])[0]
    try:
        value = int(raw)
    except (ValueError, TypeError):
        raise ValueError(f"{key} must be an integer, got: {raw!r}")
    return max(min_val, min(value, max_val))


__all__ = [
    "_require_workspace",
    "_require_one",
    "_parse_int",
    "RouteParams",
]


class RouteParams:
    """Thin adapter around the parsed query string ``params`` dict.

    Routes share many optional fields (``view``, ``budget``, ``task_id``,
    ``session_id``, ``intent``, ``project``, ``auto_sync_mode``,
    ``report_level``, ``limit``).  ``RouteParams`` keeps the public path/param
    contract identical while letting handlers say ``rp.view()`` instead of
    ``rp.view()``.  This collapses the most common
    duplication without inventing a heavyweight schema layer.
    """

    __slots__ = ("params", "default_workspace")

    def __init__(self, params: dict, default_workspace: str | None) -> None:
        self.params = params
        self.default_workspace = default_workspace

    # --- required -----------------------------------------------------------
    def workspace(self) -> str:
        return _require_workspace(self.params, self.default_workspace)

    def require(self, key: str) -> str:
        return _require_one(self.params, key)

    # --- optional strings ---------------------------------------------------
    def get(self, key: str, default: str = "") -> str:
        return self.params.get(key, [default])[0]

    def task_id(self) -> str:
        return self.get("task_id", "")

    def session_id(self) -> str:
        return self.get("session_id", "")

    def intent(self) -> str:
        return self.get("intent", "")

    def project(self) -> str:
        return self.get("project", "")

    def title(self) -> str:
        return self.get("title", "")

    def view(self, default: str = "compact") -> str:
        return self.get("view", default)

    def budget(self, default: str = "medium") -> str:
        return self.get("budget", default)

    def auto_sync_mode(self, default: str = "balanced") -> str:
        return self.get("auto_sync_mode", default)

    def report_level(self, default: str = "standard") -> str:
        return self.get("report_level", default)

    def target_model(self, default: str = "codex") -> str:
        return self.get("target_model", default)

    # --- optional ints / lists ---------------------------------------------
    def limit(self, default: int = 20, *, max_val: int = 10000) -> int:
        return _parse_int(self.params, "limit", default, max_val=max_val)

    def int_param(self, key: str, default: int, *, min_val: int = 1, max_val: int = 10000) -> int:
        return _parse_int(self.params, key, default, min_val=min_val, max_val=max_val)

    def list_param(self, key: str) -> list[str]:
        return [item for item in self.params.get(key, []) if item]

    def bool_param(self, key: str, default: bool = False) -> bool:
        raw = self.params.get(key, [str(default).lower()])[0]
        return str(raw).strip().lower() == "true"

    # --- composites ---------------------------------------------------------
    def view_budget(self) -> dict:
        return {"view": self.view(), "budget": self.budget()}

    def task_session(self) -> dict:
        return {"task_id": self.task_id(), "session_id": self.session_id()}

    def task_session_intent(self) -> dict:
        out = self.task_session()
        out["intent"] = self.intent()
        return out

__all__ = ["RouteParams", "_parse_int", "_require_one", "_require_workspace"]
