from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Callable

from ..configuration.compiled import CompiledGraph
from ..configuration.declarative import ModuleSpec, module
from ..configuration.modern import Builder, EnterpriseMode, StrictMode
from ..core.models import Lifetime, RegistrationInfo, ServiceKey, qualified
from ..inspection.graph import DoctorReport


SafeMode = EnterpriseMode
LifetimeLike = Lifetime | str


def _coerce_lifetime(value: LifetimeLike) -> Lifetime:
    if isinstance(value, Lifetime):
        return value
    try:
        return Lifetime(value.lower())
    except ValueError as exc:
        allowed = ", ".join(item.value for item in Lifetime)
        raise ValueError(f"Unsupported lifetime {value!r}. Use one of: {allowed}.") from exc


def named(key: ServiceKey, name: str, *, namespace: str | None = None):
    """Create a typed named key."""
    return qualified(key, name, namespace=namespace)


def bundle(*entries: Any, name: str | None = None) -> ModuleSpec:
    """Group related entries into a reusable composition unit."""
    return module(*entries, name=name)


def _resolve_key(key: ServiceKey, *, name: str | None, namespace: str | None) -> ServiceKey:
    if name is None:
        return key
    return named(key, name, namespace=namespace)


def _bind(
    builder: Builder,
    key: ServiceKey,
    target: type[Any] | Callable[..., Any],
    *,
    lifetime: LifetimeLike,
    replace: bool | None,
) -> Builder:
    method = getattr(builder, _coerce_lifetime(lifetime).value)
    if inspect.isclass(target):
        return method(key, target, replace=replace)
    return method(key, factory=target, replace=replace)


def _contribute(builder: Builder, key: ServiceKey, target: type[Any] | Callable[..., Any]) -> Builder:
    if inspect.isclass(target):
        return builder.contribute(key, target)
    return builder.contribute(key, factory=target)


@dataclass(frozen=True, slots=True)
class Blueprint:
    """Frozen, inspectable application graph."""

    _compiled: CompiledGraph

    @property
    def snapshot(self) -> Any:
        """Expose the immutable compiled snapshot."""
        return self._compiled.snapshot

    def start(self):
        """Build a runtime container from this blueprint."""
        return self._compiled.build()

    def validate(self, *roots: ServiceKey) -> None:
        """Validate the graph, optionally focusing on specific roots."""
        self._compiled.validate(*roots)

    def doctor(self, *roots: ServiceKey) -> DoctorReport:
        """Return a readable health report for the graph."""
        return self._compiled.doctor(*roots)

    def explain(self, key: ServiceKey) -> str:
        """Explain how a service would be resolved."""
        return self._compiled.explain(key)

    def catalog(self, *, include_dynamic: bool = False) -> tuple[RegistrationInfo, ...]:
        """List registered services."""
        return self._compiled.catalog(include_dynamic=include_dynamic)


@dataclass(frozen=True, slots=True)
class App:
    """Immutable application composition entry point."""

    _builder: Builder = Builder()

    def include(self, *entries: Any, name: str | None = None) -> "App":
        """Include services, bundles, or modules in the app graph."""
        return App(self._builder.module(*entries, name=name))

    def value(
        self,
        key: ServiceKey,
        value: Any,
        *,
        name: str | None = None,
        namespace: str | None = None,
        replace: bool | None = None,
    ) -> "App":
        """Bind a concrete value under a service key."""
        return self.bind(key, name=name, namespace=namespace).value(value, replace=replace)

    def singleton(
        self,
        key: ServiceKey,
        target: type[Any] | Callable[..., Any],
        *,
        name: str | None = None,
        namespace: str | None = None,
        replace: bool | None = None,
    ) -> "App":
        """Bind a singleton implementation or factory."""
        return self.bind(key, name=name, namespace=namespace).singleton(target, replace=replace)

    def scoped(
        self,
        key: ServiceKey,
        target: type[Any] | Callable[..., Any],
        *,
        name: str | None = None,
        namespace: str | None = None,
        replace: bool | None = None,
    ) -> "App":
        """Bind a scoped implementation or factory."""
        return self.bind(key, name=name, namespace=namespace).scoped(target, replace=replace)

    def transient(
        self,
        key: ServiceKey,
        target: type[Any] | Callable[..., Any],
        *,
        name: str | None = None,
        namespace: str | None = None,
        replace: bool | None = None,
    ) -> "App":
        """Bind a transient implementation or factory."""
        return self.bind(key, name=name, namespace=namespace).transient(target, replace=replace)

    def factory(
        self,
        key: ServiceKey,
        target: Callable[..., Any],
        *,
        lifetime: LifetimeLike = Lifetime.TRANSIENT,
        name: str | None = None,
        namespace: str | None = None,
        replace: bool | None = None,
    ) -> "App":
        """Bind a factory under a specific key."""
        return self.bind(key, name=name, namespace=namespace).factory(target, lifetime=lifetime, replace=replace)

    def many(
        self,
        key: ServiceKey,
        *targets: type[Any] | Callable[..., Any],
        name: str | None = None,
        namespace: str | None = None,
    ) -> "App":
        """Contribute many implementations under one extension point."""
        return self.bind(key, name=name, namespace=namespace).many(*targets)

    def bind(self, key: ServiceKey, *, name: str | None = None, namespace: str | None = None) -> "BindingBuilder":
        """Open a fluent binding builder for a service key."""
        return BindingBuilder(self, _resolve_key(key, name=name, namespace=namespace))

    def on(self, key: ServiceKey, *, name: str | None = None, namespace: str | None = None) -> "HookBuilder":
        """Attach hooks to a concrete service key."""
        return HookBuilder(self, _resolve_key(key, name=name, namespace=namespace))

    def when(self, predicate: Callable[[ServiceKey, Lifetime], bool]) -> "PredicateHookBuilder":
        """Attach hooks to services matched by a predicate."""
        return PredicateHookBuilder(self, predicate)

    def use(self, mode: Any) -> "App":
        """Apply a predefined mode or bundle."""
        return App(self._builder.use(mode))

    def strict(self) -> "App":
        """Disable implicit autowiring."""
        return App(self._builder.strict())

    def safe(self) -> "App":
        """Enable stricter validation and typed-key rules."""
        return App(self._builder.enterprise())

    def check(self, *roots: ServiceKey) -> "App":
        """Validate the graph and return the same app for chaining."""
        self._builder.validate(*roots)
        return self

    def doctor(self, *roots: ServiceKey) -> DoctorReport:
        """Return a human-readable health report for the current graph."""
        return self.freeze(validate=False).doctor(*roots)

    def freeze(self, *, validate: bool | None = None) -> Blueprint:
        """Compile the app into an inspectable blueprint."""
        return Blueprint(self._builder.compile(validate=validate))

    def start(self, *, validate: bool | None = None):
        """Build a runtime container."""
        return self.freeze(validate=validate).start()

    def test(self):
        """Open the testing helper API."""
        from ..testing import TestApp

        return TestApp(self)


@dataclass(frozen=True, slots=True)
class BindingBuilder:
    """Fluent binding helper returned by ``App.bind(...)``."""

    app: App
    key: ServiceKey

    def to(
        self,
        target: type[Any] | Callable[..., Any],
        *,
        lifetime: LifetimeLike = Lifetime.TRANSIENT,
        replace: bool | None = None,
    ) -> App:
        """Bind an implementation or factory with an explicit lifetime."""
        return App(_bind(self.app._builder, self.key, target, lifetime=lifetime, replace=replace))

    def factory(
        self,
        target: Callable[..., Any],
        *,
        lifetime: LifetimeLike = Lifetime.TRANSIENT,
        replace: bool | None = None,
    ) -> App:
        """Bind a factory with an explicit lifetime."""
        return App(_bind(self.app._builder, self.key, target, lifetime=lifetime, replace=replace))

    def instance(self, value: Any, *, replace: bool | None = None) -> App:
        """Bind a concrete instance."""
        return App(self.app._builder.instance(self.key, value, replace=replace))

    def value(self, value: Any, *, replace: bool | None = None) -> App:
        """Alias for ``instance(...)``."""
        return self.instance(value, replace=replace)

    def transient(self, target: type[Any] | Callable[..., Any], *, replace: bool | None = None) -> App:
        """Bind a transient implementation or factory."""
        return self.to(target, lifetime=Lifetime.TRANSIENT, replace=replace)

    def scoped(self, target: type[Any] | Callable[..., Any], *, replace: bool | None = None) -> App:
        """Bind a scoped implementation or factory."""
        return self.to(target, lifetime=Lifetime.SCOPED, replace=replace)

    def singleton(self, target: type[Any] | Callable[..., Any], *, replace: bool | None = None) -> App:
        """Bind a singleton implementation or factory."""
        return self.to(target, lifetime=Lifetime.SINGLETON, replace=replace)

    def many(self, *targets: type[Any] | Callable[..., Any]) -> App:
        """Contribute multiple implementations under one key."""
        builder = self.app._builder
        for target in targets:
            builder = _contribute(builder, self.key, target)
        return App(builder)

    def alias(
        self,
        target: ServiceKey,
        *,
        lifetime: LifetimeLike = Lifetime.TRANSIENT,
        replace: bool | None = None,
    ) -> App:
        """Alias one key to another."""
        return App(self.app._builder.alias(self.key, target, lifetime=_coerce_lifetime(lifetime), replace=replace))


@dataclass(frozen=True, slots=True)
class HookBuilder:
    """Fluent hook helper returned by ``App.on(...)``."""

    app: App
    key: ServiceKey

    def init(
        self,
        hook: Callable[..., Any],
        *,
        async_hook: Callable[..., Any] | None = None,
        order: int = 0,
    ) -> App:
        """Run a hook after a service is created."""
        return App(self.app._builder.activate(self.key, hook, ahook=async_hook, order=order))

    def wrap(
        self,
        interceptor: Callable[..., Any],
        *,
        async_wrap: Callable[..., Any] | None = None,
        order: int = 0,
    ) -> App:
        """Wrap a service instance with an interceptor."""
        return App(self.app._builder.decorate(self.key, interceptor, ainterceptor=async_wrap, order=order))


@dataclass(frozen=True, slots=True)
class PredicateHookBuilder:
    """Fluent hook helper returned by ``App.when(...)``."""

    app: App
    predicate: Callable[[ServiceKey, Lifetime], bool]

    def init(
        self,
        hook: Callable[..., Any],
        *,
        async_hook: Callable[..., Any] | None = None,
        order: int = 0,
    ) -> App:
        """Run a hook for every service matched by the predicate."""
        return App(self.app._builder.activate_where(self.predicate, hook, ahook=async_hook, order=order))

    def wrap(
        self,
        interceptor: Callable[..., Any],
        *,
        async_wrap: Callable[..., Any] | None = None,
        order: int = 0,
    ) -> App:
        """Wrap every service matched by the predicate."""
        return App(self.app._builder.decorate_where(self.predicate, interceptor, ainterceptor=async_wrap, order=order))
