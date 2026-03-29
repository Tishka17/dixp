"""Public API for dixp."""

from .api import App, Blueprint, SafeMode, StrictMode, bundle, named, scoped, service, singleton, transient
from .inspection import DoctorReport
from .runtime import Container, Scope
from .testing import TestApp, stub
from .core.errors import (
    CircularDependencyError,
    ContainerError,
    ContainerClosedError,
    LifetimeMismatchError,
    RegistrationError,
    ResolutionError,
    ValidationError,
)
from .core.models import (
    Factory,
    Inject,
    Lazy,
    Lifetime,
    Provider,
)

__all__ = [
    "App",
    "Blueprint",
    "CircularDependencyError",
    "Container",
    "ContainerError",
    "ContainerClosedError",
    "DoctorReport",
    "Factory",
    "Inject",
    "Lazy",
    "Lifetime",
    "LifetimeMismatchError",
    "Provider",
    "RegistrationError",
    "ResolutionError",
    "SafeMode",
    "Scope",
    "StrictMode",
    "TestApp",
    "ValidationError",
    "bundle",
    "named",
    "scoped",
    "service",
    "singleton",
    "stub",
    "transient",
]
