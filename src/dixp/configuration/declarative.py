from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from ..core.graph import MISSING
from ..core.metadata import ComponentSpec
from ..core.models import Lifetime, ServiceKey


class SupportsApply(Protocol):
    def apply(self, builder: Any) -> None: ...


def _component_spec(target: Any) -> ComponentSpec | None:
    return getattr(target, "__dixp_component__", None)


def _apply_entry(builder: Any, entry: Any) -> None:
    if isinstance(entry, ModuleSpec):
        entry.apply(builder)
        return
    if hasattr(entry, "apply"):
        entry.apply(builder)
        return

    spec = _component_spec(entry)
    if spec is not None:
        key = spec.key or entry
        if inspect.isclass(entry):
            if spec.multiple:
                builder.multibind(key, entry, lifetime=spec.lifetime)
            else:
                builder.add(key, entry, lifetime=spec.lifetime)
            return
        if spec.multiple:
            builder.multibind(key, factory=entry, lifetime=spec.lifetime)
        else:
            builder.add(key, factory=entry, lifetime=spec.lifetime)
        return

    raise TypeError(f"Unsupported declarative entry: {entry!r}")


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

    def apply(self, builder: Any) -> None:
        if self.open_generic:
            if self.key is None or self.implementation is None:
                raise TypeError("Open generic bindings require key and implementation")
            builder.open_generic(
                self.key,
                self.implementation,
                lifetime=self.lifetime,
                replace=self.replace,
            )
            return
        if self.multiple:
            builder.multibind(
                self.key,
                self.implementation,
                factory=self.factory,
                instance=self.instance,
                lifetime=self.lifetime,
            )
            return
        builder.add(
            self.key,
            self.implementation,
            factory=self.factory,
            instance=self.instance,
            lifetime=self.lifetime,
            replace=self.replace,
        )


@dataclass(frozen=True, slots=True)
class AliasSpec:
    key: ServiceKey
    target: ServiceKey
    lifetime: Lifetime = Lifetime.TRANSIENT
    replace: bool | None = None

    def apply(self, builder: Any) -> None:
        builder.alias(self.key, self.target, lifetime=self.lifetime, replace=self.replace)


@dataclass(frozen=True, slots=True)
class ActivationSpec:
    predicate: Callable[[ServiceKey, Lifetime], bool] | None
    key: ServiceKey | None
    hook: Callable[..., Any]
    ahook: Callable[..., Any] | None = None
    order: int = 0

    def apply(self, builder: Any) -> None:
        if self.predicate is not None:
            builder.on_activate_where(self.predicate, self.hook, ahook=self.ahook, order=self.order)
            return
        assert self.key is not None
        builder.on_activate(self.key, self.hook, ahook=self.ahook, order=self.order)


@dataclass(frozen=True, slots=True)
class InterceptorSpec:
    predicate: Callable[[ServiceKey, Lifetime], bool] | None
    key: ServiceKey | None
    interceptor: Callable[..., Any]
    ainterceptor: Callable[..., Any] | None = None
    order: int = 0

    def apply(self, builder: Any) -> None:
        if self.predicate is not None:
            builder.intercept_where(
                self.predicate,
                self.interceptor,
                ainterceptor=self.ainterceptor,
                order=self.order,
            )
            return
        assert self.key is not None
        builder.intercept(self.key, self.interceptor, ainterceptor=self.ainterceptor, order=self.order)


@dataclass(frozen=True, slots=True)
class PolicySpec:
    policy: Any

    def apply(self, builder: Any) -> None:
        builder.add_policy(self.policy)


@dataclass(frozen=True, slots=True)
class ModuleSpec:
    entries: tuple[Any, ...]
    name: str | None = None

    def apply(self, builder: Any) -> None:
        for entry in self.entries:
            _apply_entry(builder, entry)


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


def policy(rule: BuildPolicy) -> PolicySpec:
    return PolicySpec(policy=rule)
