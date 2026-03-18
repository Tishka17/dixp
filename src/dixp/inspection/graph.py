from __future__ import annotations

from ..core.errors import ResolutionError, ValidationError
from ..core.graph import Registration, collection_spec, describe_key, request_wrapper_spec
from ..core.models import Lifetime, ServiceKey
from ..core.ports import InspectorPort, RegistryPort
from ..core.resolution import ResolutionContext, format_path


class GraphInspector(InspectorPort):
    def __init__(self, registry: RegistryPort) -> None:
        self._registry = registry

    def validate(self, *roots: ServiceKey) -> None:
        targets = tuple(dict.fromkeys(roots)) if roots else self._registry.root_keys()
        errors: list[str] = []

        def validate_key(key: ServiceKey, context: ResolutionContext) -> None:
            try:
                request = request_wrapper_spec(key)
                if request is not None:
                    validate_key(
                        request.key,
                        context.enter(key, Lifetime.TRANSIENT, display=describe_key(key)),
                    )
                    return
                collection = collection_spec(key)
                if collection is not None:
                    _, item_key = collection
                    nested_context = context.enter(key, Lifetime.TRANSIENT)
                    for registration in self._registry.registrations_for_collection(
                        item_key,
                        suppress_autowire_errors=False,
                    ):
                        contributor_context = nested_context.enter(
                            registration.graph_key,
                            registration.lifetime,
                            display=registration.display,
                        )
                        for dependency in registration.dependencies:
                            if dependency.has_default and not self._registry.can_resolve(dependency.key):
                                continue
                            validate_key(dependency.key, contributor_context)
                    return

                registration = self._registry.registration_for(key, suppress_autowire_errors=False)
                if registration is None:
                    registrations = self._registry.registrations_for_collection(key, suppress_autowire_errors=False)
                    if registrations:
                        nested_context = context.enter(key, Lifetime.TRANSIENT, display=f"{describe_key(key)}[]")
                        for item_registration in registrations:
                            contributor_context = nested_context.enter(
                                item_registration.graph_key,
                                item_registration.lifetime,
                                display=item_registration.display,
                            )
                            for dependency in item_registration.dependencies:
                                if dependency.has_default and not self._registry.can_resolve(dependency.key):
                                    continue
                                validate_key(dependency.key, contributor_context)
                        return
                    if context.frames:
                        path = format_path(context.frames, tail=key)
                        raise ValidationError(f"Missing registration for {describe_key(key)}: {path}")
                    raise ValidationError(f"Missing registration for {describe_key(key)}")
                nested_context = context.enter(
                    registration.graph_key,
                    registration.lifetime,
                    display=registration.display,
                )
                for dependency in registration.dependencies:
                    if dependency.has_default and not self._registry.can_resolve(dependency.key):
                        continue
                    validate_key(dependency.key, nested_context)
            except (ResolutionError, ValidationError) as exc:
                message = str(exc)
                if message not in errors:
                    errors.append(message)

        for key in targets:
            validate_key(key, ResolutionContext())

        if errors:
            details = "\n".join(f"- {message}" for message in errors)
            raise ValidationError(f"Dependency graph validation failed:\n{details}")

    def explain(self, key: ServiceKey) -> str:
        lines: list[str] = []

        def line(prefix: str, text: str) -> None:
            lines.append(f"{prefix}{text}")

        def walk(service_key: ServiceKey, prefix: str, path: tuple[ServiceKey, ...]) -> None:
            request = request_wrapper_spec(service_key)
            if request is not None:
                line(prefix, f"{describe_key(service_key)}")
                walk(request.key, prefix + "  ", path)
                return
            collection = collection_spec(service_key)
            if collection is not None:
                _, item_key = collection
                line(prefix, f"{describe_key(service_key)}")
                registrations = self._registry.registrations_for_collection(item_key, suppress_autowire_errors=False)
                if not registrations:
                    line(prefix + "  ", "<empty>")
                    return
                for registration in registrations:
                    walk_registration(registration, prefix + "  ", path)
                return

            registration = self._registry.registration_for(service_key, suppress_autowire_errors=False)
            if registration is None:
                line(prefix, f"{describe_key(service_key)} [missing]")
                return
            walk_registration(registration, prefix, path)

        def walk_registration(registration: Registration, prefix: str, path: tuple[ServiceKey, ...]) -> None:
            line(prefix, f"{registration.display} [{registration.lifetime.value}]")
            if registration.policies:
                line(prefix + "  ", f"policies: {', '.join(registration.policies)}")
            if registration.activation_hooks:
                line(prefix + "  ", f"activations: {', '.join(registration.activation_hooks)}")
            if registration.interceptors:
                line(prefix + "  ", f"interceptors: {', '.join(registration.interceptors)}")
            if registration.graph_key in path:
                line(prefix + "  ", "<cycle>")
                return
            next_path = path + (registration.graph_key,)
            if not registration.dependencies:
                line(prefix + "  ", "<leaf>")
                return
            for dependency in registration.dependencies:
                marker = "optional " if dependency.has_default else ""
                line(prefix + "  ", f"{marker}{describe_key(dependency.key)}")
                walk(dependency.key, prefix + "    ", next_path)

        walk(key, "", ())
        return "\n".join(lines)
