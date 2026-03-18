from __future__ import annotations

import asyncio
import inspect
import threading
from typing import Any, Callable

from ..core.errors import ResolutionError
from ..core.graph import maybe_await, maybe_awaitable_close


def dispose_instance(instance: Any) -> None:
    close = getattr(instance, "close", None)
    if callable(close):
        close()


async def adispose_instance(instance: Any) -> None:
    aclose = getattr(instance, "aclose", None)
    if callable(aclose):
        await aclose()
        return
    dispose_instance(instance)


def iter_unique_cached_values(cache: dict[object, Any]) -> tuple[Any, ...]:
    seen: set[int] = set()
    unique: list[Any] = []
    for instance in reversed(tuple(cache.values())):
        marker = id(instance)
        if marker in seen:
            continue
        seen.add(marker)
        unique.append(instance)
    return tuple(unique)


class InstanceCache:
    def __init__(self, *, async_error_message: str) -> None:
        self._values: dict[object, Any] = {}
        self._lock = threading.RLock()
        self._async_locks: dict[object, asyncio.Lock] = {}
        self._async_error_message = async_error_message

    def get_or_create(self, token: object, factory: Callable[[], Any]) -> Any:
        if token in self._values:
            return self._values[token]
        with self._lock:
            if token not in self._values:
                value = factory()
                if inspect.isawaitable(value):
                    maybe_awaitable_close(value)
                    raise ResolutionError(self._async_error_message)
                self._values[token] = value
            return self._values[token]

    async def aget_or_create(self, token: object, factory: Callable[[], Any]) -> Any:
        if token in self._values:
            return self._values[token]
        lock = self._async_locks.setdefault(token, asyncio.Lock())
        async with lock:
            if token not in self._values:
                self._values[token] = await maybe_await(factory())
            return self._values[token]

    def close(self) -> None:
        for instance in iter_unique_cached_values(self._values):
            dispose_instance(instance)
        self._values.clear()

    async def aclose(self) -> None:
        for instance in iter_unique_cached_values(self._values):
            await adispose_instance(instance)
        self._values.clear()
