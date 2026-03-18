from __future__ import annotations


class ContainerError(Exception):
    """Base error for the container."""


class RegistrationError(ContainerError):
    """Raised when a registration is invalid."""


class ResolutionError(ContainerError):
    """Raised when a dependency cannot be resolved."""


class CircularDependencyError(ResolutionError):
    """Raised when the dependency graph contains a cycle."""


class LifetimeMismatchError(ResolutionError):
    """Raised when a scoped dependency leaks into a singleton."""


class ContainerClosedError(ContainerError):
    """Raised when a closed container or scope is used."""


class ValidationError(ContainerError):
    """Raised when the dependency graph is invalid."""
