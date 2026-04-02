from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Awaitable, Callable, Generic, Hashable, Protocol, TypeVar

ServiceKey = Hashable
T = TypeVar("T")


class Lifetime(str, Enum):
    TRANSIENT = "transient"
    SCOPED = "scoped"
    SINGLETON = "singleton"


class DuplicatePolicy(str, Enum):
    ERROR = "error"
    REPLACE = "replace"


class AutowirePolicy(str, Enum):
    IMPLICIT = "implicit"
    ANNOTATED = "annotated"
    DISABLED = "disabled"


class BuildProfile(str, Enum):
    STANDARD = "standard"
    STRICT = "strict"
    ENTERPRISE = "enterprise"


@dataclass(frozen=True, slots=True)
class Qualifier:
    key: ServiceKey
    name: str
    namespace: str | None = None

    def __repr__(self) -> str:
        prefix = f"{self.namespace}:" if self.namespace else ""
        return f"{self.key!r}@{prefix}{self.name}"


def qualified(key: ServiceKey, name: str, *, namespace: str | None = None) -> Qualifier:
    return Qualifier(key=key, name=name, namespace=namespace)


@dataclass(frozen=True, slots=True)
class Inject:
    key: ServiceKey | None = None

    @classmethod
    def named(cls, key: ServiceKey, name: str, *, namespace: str | None = None) -> "Inject":
        return cls(key=qualified(key, name, namespace=namespace))

    @classmethod
    def qualified(cls, key: ServiceKey, name: str, *, namespace: str | None = None) -> "Inject":
        return cls.named(key, name, namespace=namespace)


class Provider(Generic[T]):
    def __init__(self, getter: Callable[[], T], agetter: Callable[[], Awaitable[T]]) -> None:
        self._getter = getter
        self._agetter = agetter

    def get(self) -> T:
        return self._getter()

    async def aget(self) -> T:
        return await self._agetter()


class Factory(Generic[T]):
    def __init__(self, provider: Provider[T]) -> None:
        self._provider = provider

    def __call__(self) -> T:
        return self._provider.get()

    async def acall(self) -> T:
        return await self._provider.aget()


class Lazy(Generic[T]):
    def __init__(self, provider: Provider[T]) -> None:
        self._provider = provider
        self._resolved = False
        self._value: T | None = None

    @property
    def value(self) -> T:
        if not self._resolved:
            self._value = self._provider.get()
            self._resolved = True
        return self._value  # type: ignore[return-value]

    async def aget(self) -> T:
        if not self._resolved:
            self._value = await self._provider.aget()
            self._resolved = True
        return self._value  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class RegistrationInfo:
    key: ServiceKey
    kind: str
    lifetime: Lifetime
    description: str
    bundle: str | None = None
    source: str | None = None
    source_location: str | None = None


@dataclass(frozen=True, slots=True)
class BundleContract:
    exports: tuple[ServiceKey, ...] | None = None
    requires: tuple[ServiceKey, ...] | None = None
    private: tuple[ServiceKey, ...] = ()
    layer: str | None = None
    tags: tuple[str, ...] = ()
    forbid_outgoing_to: tuple[str, ...] = ()
    allow_incoming_from: tuple[str, ...] | None = None
    forbid_outgoing_to_layers: tuple[str, ...] = ()
    allow_incoming_from_layers: tuple[str, ...] | None = None
    forbid_outgoing_to_tags: tuple[str, ...] = ()
    allow_incoming_from_tags: tuple[str, ...] | None = None


class Interceptor(Protocol):
    def __call__(self, instance: Any, *, key: ServiceKey, lifetime: Lifetime) -> Any: ...


class AsyncInterceptor(Protocol):
    async def __call__(self, instance: Any, *, key: ServiceKey, lifetime: Lifetime) -> Any: ...


@dataclass(frozen=True, slots=True)
class InterceptorBinding:
    predicate: Callable[[ServiceKey, Lifetime], bool]
    interceptor: Callable[..., Any]
    ainterceptor: Callable[..., Awaitable[Any]] | None = None
    order: int = 0


class ActivationHook(Protocol):
    def __call__(self, instance: Any, *, key: ServiceKey, lifetime: Lifetime) -> Any: ...


class AsyncActivationHook(Protocol):
    async def __call__(self, instance: Any, *, key: ServiceKey, lifetime: Lifetime) -> Any: ...


@dataclass(frozen=True, slots=True)
class ActivationBinding:
    predicate: Callable[[ServiceKey, Lifetime], bool]
    hook: Callable[..., Any]
    ahook: Callable[..., Awaitable[Any]] | None = None
    order: int = 0
