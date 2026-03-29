from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from ..core.graph import OpenGenericBinding, Registration
from ..core.models import ActivationBinding, AutowirePolicy, InterceptorBinding, ServiceKey


@dataclass(frozen=True, slots=True)
class RegistrySnapshot:
    registrations: Mapping[ServiceKey, Registration]
    multi_registrations: Mapping[ServiceKey, tuple[Registration, ...]]
    open_generic_bindings: Mapping[ServiceKey, OpenGenericBinding]
    activations: tuple[ActivationBinding, ...]
    interceptors: tuple[InterceptorBinding, ...]
    autowire_policy: AutowirePolicy

    def __post_init__(self) -> None:
        object.__setattr__(self, "registrations", MappingProxyType(dict(self.registrations)))
        object.__setattr__(
            self,
            "multi_registrations",
            MappingProxyType({key: tuple(value) for key, value in self.multi_registrations.items()}),
        )
        object.__setattr__(self, "open_generic_bindings", MappingProxyType(dict(self.open_generic_bindings)))
        object.__setattr__(self, "activations", tuple(self.activations))
        object.__setattr__(self, "interceptors", tuple(self.interceptors))
