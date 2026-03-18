from __future__ import annotations

from dataclasses import dataclass

from .models import Lifetime, ServiceKey


@dataclass(frozen=True, slots=True)
class InjectableSpec:
    lifetime: Lifetime


@dataclass(frozen=True, slots=True)
class ProviderSpec:
    key: ServiceKey | None
    lifetime: Lifetime
    multiple: bool


@dataclass(frozen=True, slots=True)
class ComponentSpec:
    key: ServiceKey | None
    lifetime: Lifetime
    multiple: bool
