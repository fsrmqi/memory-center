from __future__ import annotations

from collections.abc import Callable
from typing import Any, Generic, TypeVar

T = TypeVar("T")


class CommandRegistry(Generic[T]):
    """Registry seam for command/action dispatch.

    The interface stays intentionally small: callers register named handlers and
    dispatch one name.  That keeps MCP, HTTP and CLI adapters thin while leaving
    each adapter free to bind its own parameters before registration.
    """

    def __init__(self, *, label: str = "command") -> None:
        self.label = label
        self._handlers: dict[str, Callable[..., T]] = {}

    def register(self, name: str, handler: Callable[..., T]) -> CommandRegistry[T]:
        self._handlers[name] = handler
        return self

    def register_many(self, handlers: dict[str, Callable[..., T]]) -> CommandRegistry[T]:
        self._handlers.update(handlers)
        return self

    def has(self, name: str) -> bool:
        return name in self._handlers

    def names(self) -> list[str]:
        return sorted(self._handlers.keys())

    def dispatch(self, name: str, *args: Any, **kwargs: Any) -> T:
        handler = self._handlers.get(name)
        if handler is None:
            valid = ", ".join(self.names())
            raise ValueError(f"Unknown {self.label}: {name}. Valid {self.label}s: {valid}")
        return handler(*args, **kwargs)


ActionRegistry = CommandRegistry[Any]
