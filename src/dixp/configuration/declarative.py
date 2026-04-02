from __future__ import annotations

from dataclasses import dataclass, replace
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
    exported_keys: tuple[ServiceKey, ...] | None = None
    required_keys: tuple[ServiceKey, ...] | None = None
    private_keys: tuple[ServiceKey, ...] = ()
    layer_name: str | None = None
    tags: tuple[str, ...] = ()
    forbidden_outgoing_bundles: tuple[str, ...] = ()
    allowed_incoming_bundles: tuple[str, ...] | None = None
    forbidden_outgoing_layers: tuple[str, ...] = ()
    allowed_incoming_layers: tuple[str, ...] | None = None
    forbidden_outgoing_tags: tuple[str, ...] = ()
    allowed_incoming_tags: tuple[str, ...] | None = None

    def exports(self, *keys: ServiceKey) -> "ModuleSpec":
        return replace(self, exported_keys=tuple(dict.fromkeys(keys)))

    def requires(self, *keys: ServiceKey) -> "ModuleSpec":
        return replace(self, required_keys=tuple(dict.fromkeys(keys)))

    def private(self, *keys: ServiceKey) -> "ModuleSpec":
        merged = (*self.private_keys, *keys)
        return replace(self, private_keys=tuple(dict.fromkeys(merged)))

    def layer(self, name: str) -> "ModuleSpec":
        return replace(self, layer_name=name)

    def tagged(self, *tags: str) -> "ModuleSpec":
        merged = (*self.tags, *tags)
        return replace(self, tags=tuple(dict.fromkeys(merged)))

    def forbid_outgoing_to(self, *bundles: str) -> "ModuleSpec":
        merged = (*self.forbidden_outgoing_bundles, *bundles)
        return replace(self, forbidden_outgoing_bundles=tuple(dict.fromkeys(merged)))

    def allow_incoming_from(self, *bundles: str) -> "ModuleSpec":
        return replace(self, allowed_incoming_bundles=tuple(dict.fromkeys(bundles)))

    def forbid_outgoing_to_layers(self, *layers: str) -> "ModuleSpec":
        merged = (*self.forbidden_outgoing_layers, *layers)
        return replace(self, forbidden_outgoing_layers=tuple(dict.fromkeys(merged)))

    def allow_incoming_from_layers(self, *layers: str) -> "ModuleSpec":
        return replace(self, allowed_incoming_layers=tuple(dict.fromkeys(layers)))

    def forbid_outgoing_to_tags(self, *tags: str) -> "ModuleSpec":
        merged = (*self.forbidden_outgoing_tags, *tags)
        return replace(self, forbidden_outgoing_tags=tuple(dict.fromkeys(merged)))

    def allow_incoming_from_tags(self, *tags: str) -> "ModuleSpec":
        return replace(self, allowed_incoming_tags=tuple(dict.fromkeys(tags)))

    def has_contract(self) -> bool:
        return (
            self.exported_keys is not None
            or self.required_keys is not None
            or bool(self.private_keys)
            or self.layer_name is not None
            or bool(self.tags)
            or bool(self.forbidden_outgoing_bundles)
            or self.allowed_incoming_bundles is not None
            or bool(self.forbidden_outgoing_layers)
            or self.allowed_incoming_layers is not None
            or bool(self.forbidden_outgoing_tags)
            or self.allowed_incoming_tags is not None
        )


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
