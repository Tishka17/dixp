from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any

from .api.app import App, named
from .core.models import Lifetime, ServiceKey

LifetimeLike = Lifetime | str


def _coerce_lifetime(value: LifetimeLike) -> Lifetime:
    if isinstance(value, Lifetime):
        return value
    return Lifetime(value.lower())


def _resolve_key(key: ServiceKey, *, name: str | None, namespace: str | None) -> ServiceKey:
    if name is None:
        return key
    return named(key, name, namespace=namespace)


def _bind_stub_member(value: Any) -> Any:
    if not callable(value):
        return value
    try:
        signature = inspect.signature(value)
    except (TypeError, ValueError):
        return value
    if len(signature.parameters) != 0:
        def method(self, *args: Any, **kwargs: Any) -> Any:
            return value(*args, **kwargs)

        return method

    def method(self) -> Any:
        return value()

    return method


def stub(*, name: str = "Stub", **attrs: Any) -> Any:
    """Build a tiny fake object from attributes and callables."""
    namespace = {"__repr__": lambda self: f"<{name}>"}  # noqa: ARG005
    for key, value in attrs.items():
        namespace[key] = _bind_stub_member(value)
    return type(name, (), namespace)()


@dataclass(frozen=True, slots=True)
class TestApp:
    """Testing-focused wrapper around ``App`` with easy overrides."""

    app: App

    def with_instance(
        self,
        key: ServiceKey,
        value: Any,
        *,
        name: str | None = None,
        namespace: str | None = None,
    ) -> "TestApp":
        """Replace a service with a concrete instance."""
        resolved = _resolve_key(key, name=name, namespace=namespace)
        return TestApp(self.app.bind(resolved).instance(value, replace=True))

    def with_impl(
        self,
        key: ServiceKey,
        implementation: type[Any],
        *,
        lifetime: LifetimeLike = Lifetime.TRANSIENT,
        name: str | None = None,
        namespace: str | None = None,
    ) -> "TestApp":
        """Replace a service with a specific implementation."""
        resolved = _resolve_key(key, name=name, namespace=namespace)
        return TestApp(self.app.bind(resolved).to(implementation, lifetime=_coerce_lifetime(lifetime), replace=True))

    def with_factory(
        self,
        key: ServiceKey,
        factory: Any,
        *,
        lifetime: LifetimeLike = Lifetime.TRANSIENT,
        name: str | None = None,
        namespace: str | None = None,
    ) -> "TestApp":
        """Replace a service with a factory."""
        resolved = _resolve_key(key, name=name, namespace=namespace)
        return TestApp(self.app.bind(resolved).factory(factory, lifetime=_coerce_lifetime(lifetime), replace=True))

    def with_stub(
        self,
        key: ServiceKey,
        *,
        name: str | None = None,
        namespace: str | None = None,
        stub_name: str | None = None,
        **attrs: Any,
    ) -> "TestApp":
        """Replace a service with a generated stub object."""
        fake = stub(name=stub_name or f"{getattr(key, '__name__', 'Service')}Stub", **attrs)
        return self.with_instance(key, fake, name=name, namespace=namespace)

    def start(self, *, validate: bool | None = None):
        """Build a runtime container for the test graph."""
        return self.app.start(validate=validate)

    def freeze(self, *, validate: bool | None = None):
        """Compile the test graph into a blueprint."""
        return self.app.freeze(validate=validate)

    def doctor(self, *roots: ServiceKey):
        """Return a health report for the test graph."""
        return self.app.doctor(*roots)
