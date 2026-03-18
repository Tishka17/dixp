from __future__ import annotations

import inspect
from dataclasses import dataclass, replace
from typing import Any, Callable, Protocol

from ..core.graph import MISSING
from ..core.metadata import ComponentSpec
from ..core.models import AutowirePolicy, BuildPolicy, BuildProfile, DuplicatePolicy, Lifetime, ServiceKey, qualified
from .compiler import GraphCompiler
from .compiled import CompiledGraph
from .declarative import (
    BindingSpec,
    ModuleSpec,
    activate,
    alias,
    contribute,
    decorate,
    module as declarative_module,
    open_generic,
    policy,
    scoped,
    singleton,
    transient,
)


class Bundle(Protocol):
    def apply(self, builder: "Builder") -> "Builder": ...


@dataclass(frozen=True, slots=True)
class ProfileBundle:
    profile: BuildProfile

    def apply(self, builder: "Builder") -> "Builder":
        if self.profile is BuildProfile.STRICT:
            return builder.strict()
        if self.profile is BuildProfile.ENTERPRISE:
            return builder.enterprise()
        return replace(builder, profile=self.profile)


StrictMode = ProfileBundle(BuildProfile.STRICT)
EnterpriseMode = ProfileBundle(BuildProfile.ENTERPRISE)


def _component_spec(target: Any) -> ComponentSpec | None:
    return getattr(target, "__dixp_component__", None)


@dataclass(frozen=True, slots=True)
class Builder:
    entries: tuple[Any, ...] = ()
    duplicate_policy: DuplicatePolicy | None = None
    autowire_policy: AutowirePolicy | None = None
    profile: BuildProfile = BuildProfile.STANDARD

    def add(self, *entries: Any) -> "Builder":
        return replace(self, entries=self.entries + tuple(entries))

    def use(self, bundle: Bundle | Callable[["Builder"], "Builder"]) -> "Builder":
        if hasattr(bundle, "apply"):
            return bundle.apply(self)  # type: ignore[return-value]
        return bundle(self)

    def strict(self) -> "Builder":
        return replace(self, profile=BuildProfile.STRICT)

    def enterprise(self) -> "Builder":
        return replace(self, profile=BuildProfile.ENTERPRISE)

    def singleton(
        self,
        key: ServiceKey | None = None,
        implementation: type[Any] | None = None,
        *,
        factory: Callable[..., Any] | None = None,
        replace: bool | None = None,
    ) -> "Builder":
        return self.add(singleton(key, implementation, factory=factory, replace=replace))

    def scoped(
        self,
        key: ServiceKey | None = None,
        implementation: type[Any] | None = None,
        *,
        factory: Callable[..., Any] | None = None,
        replace: bool | None = None,
    ) -> "Builder":
        return self.add(scoped(key, implementation, factory=factory, replace=replace))

    def transient(
        self,
        key: ServiceKey | None = None,
        implementation: type[Any] | None = None,
        *,
        factory: Callable[..., Any] | None = None,
        replace: bool | None = None,
    ) -> "Builder":
        return self.add(transient(key, implementation, factory=factory, replace=replace))

    def instance(self, key: ServiceKey | None = None, value: Any = MISSING, *, replace: bool | None = None) -> "Builder":
        return self.add(BindingSpec(key=key, instance=value, lifetime=Lifetime.SINGLETON, replace=replace))

    def contribute(
        self,
        key: ServiceKey | None = None,
        implementation: type[Any] | None = None,
        *,
        factory: Callable[..., Any] | None = None,
    ) -> "Builder":
        return self.add(contribute(key, implementation, factory=factory))

    def qualify(
        self,
        key: ServiceKey,
        name: str,
        *,
        namespace: str | None = None,
        implementation: type[Any] | None = None,
        factory: Callable[..., Any] | None = None,
        instance: Any = MISSING,
        lifetime: Lifetime = Lifetime.TRANSIENT,
        replace: bool | None = None,
    ) -> "Builder":
        return self.add(
            BindingSpec(
                key=qualified(key, name, namespace=namespace),
                implementation=implementation,
                factory=factory,
                instance=instance,
                lifetime=lifetime,
                replace=replace,
            )
        )

    def contribute_qualified(
        self,
        key: ServiceKey,
        name: str,
        *,
        namespace: str | None = None,
        implementation: type[Any] | None = None,
        factory: Callable[..., Any] | None = None,
        lifetime: Lifetime = Lifetime.TRANSIENT,
    ) -> "Builder":
        return self.add(
            BindingSpec(
                key=qualified(key, name, namespace=namespace),
                implementation=implementation,
                factory=factory,
                lifetime=lifetime,
                multiple=True,
            )
        )

    def alias(
        self,
        key: ServiceKey,
        target: ServiceKey,
        *,
        lifetime: Lifetime = Lifetime.TRANSIENT,
        replace: bool | None = None,
    ) -> "Builder":
        return self.add(alias(key, target, lifetime=lifetime, replace=replace))

    def open_generic(
        self,
        key: ServiceKey,
        implementation: type[Any],
        *,
        lifetime: Lifetime = Lifetime.TRANSIENT,
        replace: bool | None = None,
    ) -> "Builder":
        return self.add(open_generic(key, implementation, lifetime=lifetime, replace=replace))

    def policy(self, rule: BuildPolicy) -> "Builder":
        return self.add(policy(rule))

    def component(
        self,
        target: type[Any] | Callable[..., Any],
        *,
        as_: ServiceKey | None = None,
        lifetime: Lifetime | None = None,
        multiple: bool | None = None,
        replace: bool | None = None,
    ) -> "Builder":
        spec = _component_spec(target)
        key = as_
        resolved_lifetime = lifetime
        resolved_multiple = multiple
        if spec is not None:
            if key is None:
                key = spec.key
            if resolved_lifetime is None:
                resolved_lifetime = spec.lifetime
            if resolved_multiple is None:
                resolved_multiple = spec.multiple
        resolved_lifetime = resolved_lifetime or Lifetime.TRANSIENT
        resolved_multiple = bool(resolved_multiple)

        if inspect.isclass(target):
            binding = BindingSpec(
                key=key or target,
                implementation=target,
                lifetime=resolved_lifetime,
                multiple=resolved_multiple,
                replace=replace,
            )
        else:
            binding = BindingSpec(
                key=key,
                factory=target,
                lifetime=resolved_lifetime,
                multiple=resolved_multiple,
                replace=replace,
            )
        return self.add(binding)

    def module(self, *entries: Any, name: str | None = None) -> "Builder":
        if len(entries) == 1 and isinstance(entries[0], ModuleSpec) and name is None:
            return self.add(entries[0])
        return self.add(declarative_module(*entries, name=name))

    def activate(
        self,
        key: ServiceKey,
        hook: Callable[..., Any],
        *,
        ahook: Callable[..., Any] | None = None,
        order: int = 0,
    ) -> "Builder":
        return self.add(activate(key, hook, ahook=ahook, order=order))

    def decorate(
        self,
        key: ServiceKey,
        interceptor: Callable[..., Any],
        *,
        ainterceptor: Callable[..., Any] | None = None,
        order: int = 0,
    ) -> "Builder":
        return self.add(decorate(key, interceptor, ainterceptor=ainterceptor, order=order))

    def activate_where(
        self,
        predicate: Callable[[ServiceKey, Lifetime], bool],
        hook: Callable[..., Any],
        *,
        ahook: Callable[..., Any] | None = None,
        order: int = 0,
    ) -> "Builder":
        from .declarative import activate_where

        return self.add(activate_where(predicate, hook, ahook=ahook, order=order))

    def decorate_where(
        self,
        predicate: Callable[[ServiceKey, Lifetime], bool],
        interceptor: Callable[..., Any],
        *,
        ainterceptor: Callable[..., Any] | None = None,
        order: int = 0,
    ) -> "Builder":
        from .declarative import decorate_where

        return self.add(decorate_where(predicate, interceptor, ainterceptor=ainterceptor, order=order))

    def pipeline(self, key: ServiceKey) -> "ServicePipeline":
        return ServicePipeline(self, key)

    def compile(self, *, validate: bool | None = None) -> CompiledGraph:
        compiler = GraphCompiler(
            duplicate_policy=self.duplicate_policy,
            autowire_policy=self.autowire_policy,
            profile=self.profile,
        )
        should_validate = self.profile is BuildProfile.ENTERPRISE if validate is None else validate
        compiled = CompiledGraph(snapshot=compiler.compile(self.entries), validate_on_build=should_validate)
        if should_validate:
            compiled.validate()
        return compiled

    def build(self, *, validate: bool | None = None):
        return self.compile(validate=validate).build()

    def validate(self, *roots: ServiceKey) -> "Builder":
        self.compile(validate=False).validate(*roots)
        return self


@dataclass(frozen=True, slots=True)
class ServicePipeline:
    builder: Builder
    key: ServiceKey

    def activate(
        self,
        hook: Callable[..., Any],
        *,
        ahook: Callable[..., Any] | None = None,
        order: int = 0,
    ) -> Builder:
        return self.builder.activate(self.key, hook, ahook=ahook, order=order)

    def decorate(
        self,
        interceptor: Callable[..., Any],
        *,
        ainterceptor: Callable[..., Any] | None = None,
        order: int = 0,
    ) -> Builder:
        return self.builder.decorate(self.key, interceptor, ainterceptor=ainterceptor, order=order)
