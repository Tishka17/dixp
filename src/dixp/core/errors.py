from __future__ import annotations

from types import MappingProxyType
from typing import Any, Mapping

from .error_formatting import format_error_message


class ContainerError(Exception):
    """Base error for the container."""

    default_code = "container_error"

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        resolved_code = code or self.default_code
        resolved_details = MappingProxyType(dict(details or {}))
        super().__init__(format_error_message(resolved_code, resolved_details, fallback=message))
        self.code = resolved_code
        self.details = resolved_details


class RegistrationError(ContainerError):
    """Raised when a registration is invalid."""

    default_code = "registration_error"


class ResolutionError(ContainerError):
    """Raised when a dependency cannot be resolved."""

    default_code = "resolution_error"


class AmbientResolverError(ResolutionError):
    """Raised when ambient resolution is requested outside an active context."""

    default_code = "no_active_resolver"


class MissingRegistrationError(ResolutionError):
    """Raised when no service exists for a requested key."""

    default_code = "missing_registration"


class AutowireError(ResolutionError):
    """Raised when implicit autowiring fails for a type."""

    default_code = "autowire_failure"


class OpenGenericResolutionError(ResolutionError):
    """Raised when an open generic binding cannot be specialized."""

    default_code = "open_generic_resolution"


class InvocationPreparationError(ResolutionError):
    """Raised when callable arguments cannot be prepared before invocation."""

    default_code = "invocation_preparation"


class InvocationSignatureError(ResolutionError):
    """Raised when the final callable signature remains invalid after injection."""

    default_code = "invocation_signature"


class AsyncApiUsageError(ResolutionError):
    """Raised when an async provider is used through the sync API."""

    default_code = "async_api_required"


class InvalidOverrideError(ResolutionError):
    """Raised when an override declaration is incomplete."""

    default_code = "invalid_override"


class CircularDependencyError(ResolutionError):
    """Raised when the dependency graph contains a cycle."""

    default_code = "circular_dependency"


class LifetimeMismatchError(ResolutionError):
    """Raised when a scoped dependency leaks into a singleton."""

    default_code = "lifetime_mismatch"


class ContainerClosedError(ContainerError):
    """Raised when a closed container or scope is used."""

    default_code = "container_closed"


class ValidationError(ContainerError):
    """Raised when the dependency graph is invalid."""

    default_code = "validation_error"


class GraphValidationError(ValidationError):
    """Raised when overall dependency graph validation fails."""

    default_code = "graph_validation"


class MissingRegistrationValidationError(ValidationError):
    """Raised when graph validation encounters a missing service."""

    default_code = "missing_registration"


class BundleContractValidationError(ValidationError):
    """Raised when bundle dependency rules are violated."""

    default_code = "bundle_contract_violation"
