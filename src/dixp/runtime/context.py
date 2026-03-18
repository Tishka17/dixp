from __future__ import annotations

import inspect
from typing import Any

from ..core.metadata import InjectableSpec
from ..core.models import AutowirePolicy, ServiceKey


def injectable_spec(target: Any) -> InjectableSpec | None:
    return getattr(target, "__dixp_injectable__", None)


def is_protocol(cls: type[Any]) -> bool:
    return bool(getattr(cls, "_is_protocol", False))


def is_autowirable(key: ServiceKey, policy: AutowirePolicy) -> bool:
    if not isinstance(key, type) or inspect.isabstract(key) or is_protocol(key):
        return False
    if policy is AutowirePolicy.DISABLED:
        return False
    if policy is AutowirePolicy.ANNOTATED:
        return injectable_spec(key) is not None
    return True
