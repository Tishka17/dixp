from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Callable

from ..core.graph import MISSING
from ..core.models import AutowirePolicy, BuildProfile, DuplicatePolicy, Lifetime, ServiceKey
from .compiler import GraphCompiler
from .compiled import CompiledGraph
from .declarative import (
    BindingSpec,
    ModuleSpec,
    activate,
    contribute,
    decorate,
    module as declarative_module,
    scoped,
    singleton,
    transient,
)


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
@dataclass(frozen=True, slots=True)
class Builder:
    entries: tuple[Any, ...] = ()
    duplicate_policy: DuplicatePolicy | None = None
    autowire_policy: AutowirePolicy | None = None
    profile: BuildProfile = BuildProfile.STANDARD

    def add(self, *entries: Any) -> "Builder":
        return replace(self, entries=self.entries + tuple(entries))

    def use(self, mode: Callable[["Builder"], "Builder"] | Any) -> "Builder":
        if hasattr(mode, "apply"):
            return mode.apply(self)  # type: ignore[return-value]
        return mode(self)

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

    def alias(
        self,
        key: ServiceKey,
        target: ServiceKey,
        *,
        lifetime: Lifetime = Lifetime.TRANSIENT,
        replace: bool | None = None,
    ) -> "Builder":
        from .declarative import alias

        return self.add(alias(key, target, lifetime=lifetime, replace=replace))

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
