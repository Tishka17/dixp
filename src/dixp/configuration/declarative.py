from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from ..core.graph import MISSING
from ..core.models import Lifetime, ServiceKey

@dataclass(frozen=True, slots=True)
class BindingSpec:
    key: ServiceKey | None = None
    implementation: type[Any] | None = None
    factory: Callable[..., Any] | None = None
    instance: Any = MISSING
    lifetime: Lifetime = Lifetime.TRANSIENT
    multiple: bool = False
    open_generic: bool = False
    replace: bool | None = None


@dataclass(frozen=True, slots=True)
class AliasSpec:
    key: ServiceKey
    target: ServiceKey
    lifetime: Lifetime = Lifetime.TRANSIENT
    replace: bool | None = None


@dataclass(frozen=True, slots=True)
class ActivationSpec:
    predicate: Callable[[ServiceKey, Lifetime], bool] | None
    key: ServiceKey | None
    hook: Callable[..., Any]
    ahook: Callable[..., Any] | None = None
    order: int = 0


@dataclass(frozen=True, slots=True)
class InterceptorSpec:
    predicate: Callable[[ServiceKey, Lifetime], bool] | None
    key: ServiceKey | None
    interceptor: Callable[..., Any]
    ainterceptor: Callable[..., Any] | None = None
    order: int = 0


@dataclass(frozen=True, slots=True)
class ModuleSpec:
    entries: tuple[Any, ...]
    name: str | None = None


def module(*entries: Any, name: str | None = None) -> ModuleSpec:
    return ModuleSpec(entries=tuple(entries), name=name)


def transient(
    key: ServiceKey | None = None,
    implementation: type[Any] | None = None,
    *,
    factory: Callable[..., Any] | None = None,
    replace: bool | None = None,
) -> BindingSpec:
    return BindingSpec(key=key, implementation=implementation, factory=factory, lifetime=Lifetime.TRANSIENT, replace=replace)


def scoped(
    key: ServiceKey | None = None,
    implementation: type[Any] | None = None,
    *,
    factory: Callable[..., Any] | None = None,
    replace: bool | None = None,
) -> BindingSpec:
    return BindingSpec(key=key, implementation=implementation, factory=factory, lifetime=Lifetime.SCOPED, replace=replace)


def singleton(
    key: ServiceKey | None = None,
    implementation: type[Any] | None = None,
    *,
    factory: Callable[..., Any] | None = None,
    replace: bool | None = None,
) -> BindingSpec:
    return BindingSpec(key=key, implementation=implementation, factory=factory, lifetime=Lifetime.SINGLETON, replace=replace)


def instance(key: ServiceKey | None = None, value: Any = MISSING, *, replace: bool | None = None) -> BindingSpec:
    return BindingSpec(key=key, instance=value, lifetime=Lifetime.SINGLETON, replace=replace)


def contribute(
    key: ServiceKey | None = None,
    implementation: type[Any] | None = None,
    *,
    factory: Callable[..., Any] | None = None,
) -> BindingSpec:
    return BindingSpec(key=key, implementation=implementation, factory=factory, multiple=True)


def open_generic(
    key: ServiceKey,
    implementation: type[Any],
    *,
    lifetime: Lifetime = Lifetime.TRANSIENT,
    replace: bool | None = None,
) -> BindingSpec:
    return BindingSpec(
        key=key,
        implementation=implementation,
        lifetime=lifetime,
        open_generic=True,
        replace=replace,
    )


def alias(
    key: ServiceKey,
    target: ServiceKey,
    *,
    lifetime: Lifetime = Lifetime.TRANSIENT,
    replace: bool | None = None,
) -> AliasSpec:
    return AliasSpec(key=key, target=target, lifetime=lifetime, replace=replace)


def activate(
    key: ServiceKey,
    hook: Callable[..., Any],
    *,
    ahook: Callable[..., Any] | None = None,
    order: int = 0,
) -> ActivationSpec:
    return ActivationSpec(predicate=None, key=key, hook=hook, ahook=ahook, order=order)


def activate_where(
    predicate: Callable[[ServiceKey, Lifetime], bool],
    hook: Callable[..., Any],
    *,
    ahook: Callable[..., Any] | None = None,
    order: int = 0,
) -> ActivationSpec:
    return ActivationSpec(predicate=predicate, key=None, hook=hook, ahook=ahook, order=order)


def decorate(
    key: ServiceKey,
    interceptor: Callable[..., Any],
    *,
    ainterceptor: Callable[..., Any] | None = None,
    order: int = 0,
) -> InterceptorSpec:
    return InterceptorSpec(predicate=None, key=key, interceptor=interceptor, ainterceptor=ainterceptor, order=order)


def decorate_where(
    predicate: Callable[[ServiceKey, Lifetime], bool],
    interceptor: Callable[..., Any],
    *,
    ainterceptor: Callable[..., Any] | None = None,
    order: int = 0,
) -> InterceptorSpec:
    return InterceptorSpec(
        predicate=predicate,
        key=None,
        interceptor=interceptor,
        ainterceptor=ainterceptor,
        order=order,
    )
