from __future__ import annotations

import inspect
from typing import Any, Callable

from ..core.metadata import ComponentSpec, InjectableSpec
from ..core.models import Lifetime, ServiceKey


def _coerce_lifetime(value: Lifetime | str) -> Lifetime:
    if isinstance(value, Lifetime):
        return value
    try:
        return Lifetime(value.lower())
    except ValueError as exc:
        allowed = ", ".join(item.value for item in Lifetime)
        raise ValueError(f"Unsupported lifetime {value!r}. Use one of: {allowed}.") from exc


def service(
    target: type[Any] | Callable[..., Any] | None = None,
    *,
    provides: ServiceKey | None = None,
    lifetime: Lifetime | str = Lifetime.TRANSIENT,
    many: bool = False,
) -> Any:
    """Mark a class or factory as a service definition."""
    resolved_lifetime = _coerce_lifetime(lifetime)

    def decorate(subject: type[Any] | Callable[..., Any]) -> type[Any] | Callable[..., Any]:
        setattr(subject, "__dixp_component__", ComponentSpec(key=provides, lifetime=resolved_lifetime, multiple=many))
        if inspect.isclass(subject):
            setattr(subject, "__dixp_injectable__", InjectableSpec(lifetime=resolved_lifetime))
        return subject

    if target is None:
        return decorate
    return decorate(target)


def singleton(
    target: type[Any] | Callable[..., Any] | None = None,
    *,
    provides: ServiceKey | None = None,
    many: bool = False,
) -> Any:
    """Shortcut for ``@service(..., lifetime='singleton')``."""
    return service(target, provides=provides, lifetime=Lifetime.SINGLETON, many=many)


def scoped(
    target: type[Any] | Callable[..., Any] | None = None,
    *,
    provides: ServiceKey | None = None,
    many: bool = False,
) -> Any:
    """Shortcut for ``@service(..., lifetime='scoped')``."""
    return service(target, provides=provides, lifetime=Lifetime.SCOPED, many=many)


def transient(
    target: type[Any] | Callable[..., Any] | None = None,
    *,
    provides: ServiceKey | None = None,
    many: bool = False,
) -> Any:
    """Shortcut for ``@service(..., lifetime='transient')``."""
    return service(target, provides=provides, lifetime=Lifetime.TRANSIENT, many=many)
