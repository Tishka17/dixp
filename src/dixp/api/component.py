from __future__ import annotations

import inspect
from typing import Any, Callable

from ..core.metadata import ComponentSpec, InjectableSpec, ProviderSpec
from ..core.models import Lifetime, ServiceKey


def component(
    target: type[Any] | Callable[..., Any] | None = None,
    *,
    as_: ServiceKey | None = None,
    lifetime: Lifetime = Lifetime.TRANSIENT,
    multiple: bool = False,
) -> Any:
    def decorate(subject: type[Any] | Callable[..., Any]) -> type[Any] | Callable[..., Any]:
        setattr(subject, "__dixp_component__", ComponentSpec(key=as_, lifetime=lifetime, multiple=multiple))
        if inspect.isclass(subject):
            setattr(subject, "__dixp_injectable__", InjectableSpec(lifetime=lifetime))
        else:
            setattr(subject, "__dixp_provider__", ProviderSpec(key=as_, lifetime=lifetime, multiple=multiple))
        return subject

    if target is None:
        return decorate
    return decorate(target)
