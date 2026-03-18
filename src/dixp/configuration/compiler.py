from __future__ import annotations

import inspect
from typing import Any, Callable, get_type_hints

from ..core.errors import RegistrationError
from ..core.graph import (
    DependencySpec,
    MISSING,
    OpenGenericBinding,
    Registration,
    compile_call_plan,
    dependency_from_annotation,
    describe_key,
    maybe_await,
)
from ..core.metadata import ComponentSpec
from ..core.models import (
    ActivationBinding,
    AutowirePolicy,
    BuildPolicy,
    BuildProfile,
    DuplicatePolicy,
    InterceptorBinding,
    Lifetime,
    ServiceKey,
)
from .declarative import (
    ActivationSpec,
    AliasSpec,
    BindingSpec,
    InterceptorSpec,
    ModuleSpec,
    PolicySpec,
)
from .registry import RegistrySnapshot


class GraphCompiler:
    def __init__(
        self,
        *,
        duplicate_policy: DuplicatePolicy | None = None,
        autowire_policy: AutowirePolicy | None = None,
        profile: BuildProfile = BuildProfile.STANDARD,
    ) -> None:
        self._base_registrations: dict[ServiceKey, Registration] = {}
        self._base_multi_registrations: dict[ServiceKey, list[Registration]] = {}
        self._registrations: dict[ServiceKey, Registration] = {}
        self._multi_registrations: dict[ServiceKey, list[Registration]] = {}
        self._open_generic_bindings: dict[ServiceKey, OpenGenericBinding] = {}
        self._profile = profile
        self._duplicate_policy = duplicate_policy or DuplicatePolicy.ERROR
        self._autowire_policy = autowire_policy or self._default_autowire_policy(profile)
        self._multibind_counter = 0
        self._activations: list[ActivationBinding] = []
        self._interceptors: list[InterceptorBinding] = []
        self._policies: list[BuildPolicy] = []

    def compile(self, entries: tuple[Any, ...]) -> RegistrySnapshot:
        for entry in entries:
            self._apply_entry(entry)
        snapshot = RegistrySnapshot(
            registrations=dict(self._registrations),
            multi_registrations={key: tuple(registrations) for key, registrations in self._multi_registrations.items()},
            open_generic_bindings=dict(self._open_generic_bindings),
            activations=tuple(self._activations),
            interceptors=tuple(self._interceptors),
            policy_names=tuple(type(policy).__name__ for policy in self._policies),
            autowire_policy=self._autowire_policy,
        )
        self._validate_snapshot(snapshot)
        return snapshot

    def _apply_entry(self, entry: Any) -> None:
        if isinstance(entry, ModuleSpec):
            for child in entry.entries:
                self._apply_entry(child)
            return
        if isinstance(entry, BindingSpec):
            self._apply_binding(entry)
            return
        if isinstance(entry, AliasSpec):
            self._apply_alias(entry)
            return
        if isinstance(entry, ActivationSpec):
            self._apply_activation(entry)
            return
        if isinstance(entry, InterceptorSpec):
            self._apply_interceptor(entry)
            return
        if isinstance(entry, PolicySpec):
            self._policies.append(entry.policy)
            self._rebuild_registrations()
            return

        spec = getattr(entry, "__dixp_component__", None)
        if isinstance(spec, ComponentSpec):
            self._apply_component(entry, spec)
            return

        raise RegistrationError(f"Unsupported composition entry: {entry!r}")

    def _apply_component(self, entry: Any, spec: ComponentSpec) -> None:
        key = spec.key or entry
        if inspect.isclass(entry):
            self._add_registration(key, entry, None, MISSING, spec.lifetime, replace=None, multiple=spec.multiple)
            return
        self._add_registration(key, None, entry, MISSING, spec.lifetime, replace=None, multiple=spec.multiple)

    def _apply_binding(self, spec: BindingSpec) -> None:
        if spec.open_generic:
            self._open_generic(spec.key, spec.implementation, lifetime=spec.lifetime, replace=spec.replace)
            return
        self._add_registration(
            spec.key,
            spec.implementation,
            spec.factory,
            spec.instance,
            spec.lifetime,
            replace=spec.replace,
            multiple=spec.multiple,
        )

    def _apply_alias(self, spec: AliasSpec) -> None:
        self._validate_service_key(spec.key)
        self._validate_service_key(spec.target)
        base_registration = Registration(
            service_key=spec.key,
            graph_key=spec.key,
            lifetime=spec.lifetime,
            provider=lambda resolver, context, target=spec.target: resolver._resolve(target, context),
            aprovider=lambda resolver, context, target=spec.target: resolver._aresolve(target, context),
            dependencies=(DependencySpec(key=spec.target, has_default=False),),
            description=f"alias {describe_key(spec.key)} -> {describe_key(spec.target)}",
            display=describe_key(spec.key),
            cache=False,
        )
        registration = self._validate_registration(self._compose_registration(base_registration))
        self._store_registration(spec.key, base_registration, registration, replace=spec.replace)

    def _apply_activation(self, spec: ActivationSpec) -> None:
        if spec.predicate is None:
            assert spec.key is not None
            predicate = lambda candidate, _lifetime, key=spec.key: candidate == key
        else:
            predicate = spec.predicate
        self._activations.append(ActivationBinding(predicate=predicate, hook=spec.hook, ahook=spec.ahook, order=spec.order))
        self._rebuild_registrations()

    def _apply_interceptor(self, spec: InterceptorSpec) -> None:
        if spec.predicate is None:
            assert spec.key is not None
            predicate = lambda candidate, _lifetime, key=spec.key: candidate == key
        else:
            predicate = spec.predicate
        self._interceptors.append(
            InterceptorBinding(
                predicate=predicate,
                interceptor=spec.interceptor,
                ainterceptor=spec.ainterceptor,
                order=spec.order,
            )
        )
        self._rebuild_registrations()

    def _add_registration(
        self,
        key: ServiceKey | None,
        implementation: type[Any] | None,
        factory: Callable[..., Any] | None,
        instance: Any,
        lifetime: Lifetime,
        *,
        replace: bool | None,
        multiple: bool,
    ) -> None:
        key = self._normalize_key(key, implementation=implementation, factory=factory, instance=instance)
        self._validate_service_key(key)
        base_registration = self._build_registration(
            key,
            implementation=implementation,
            factory=factory,
            instance=instance,
            lifetime=lifetime,
            graph_suffix=f"[{self._multibind_counter}]" if multiple else "",
        )
        registration = self._validate_registration(self._compose_registration(base_registration))
        if multiple:
            self._multibind_counter += 1
            self._base_multi_registrations.setdefault(key, []).append(base_registration)
            self._multi_registrations.setdefault(key, []).append(registration)
            return
        self._store_registration(key, base_registration, registration, replace=replace)

    def _normalize_key(
        self,
        key: ServiceKey | None,
        *,
        implementation: type[Any] | None,
        factory: Callable[..., Any] | None,
        instance: Any,
    ) -> ServiceKey:
        if key is not None:
            return key
        if implementation is not None:
            return implementation
        if factory is not None:
            hints = get_type_hints(factory, include_extras=True)
            if "return" not in hints:
                raise RegistrationError("Factory registration without a key requires a return type hint")
            dependency = dependency_from_annotation(hints["return"])
            if dependency is None:
                raise RegistrationError("Factory return annotation is not a valid service key")
            return dependency
        if instance is not MISSING:
            return type(instance)
        raise RegistrationError("Registration requires a service key or an inferable target")

    def _default_autowire_policy(self, profile: BuildProfile) -> AutowirePolicy:
        if profile is BuildProfile.STRICT:
            return AutowirePolicy.DISABLED
        if profile is BuildProfile.ENTERPRISE:
            return AutowirePolicy.ANNOTATED
        return AutowirePolicy.IMPLICIT

    def _validate_service_key(self, key: ServiceKey) -> None:
        if self._profile is BuildProfile.ENTERPRISE and isinstance(key, str):
            raise RegistrationError(
                "Enterprise profile requires typed service keys; use qualified(...) or a dedicated token object"
            )
        for policy in self._policies:
            try:
                policy.validate_service_key(key)
            except ValueError as exc:
                raise RegistrationError(str(exc)) from exc

    def _store_registration(
        self,
        key: ServiceKey,
        base_registration: Registration,
        registration: Registration,
        *,
        replace: bool | None,
    ) -> None:
        should_replace = self._duplicate_policy is DuplicatePolicy.REPLACE if replace is None else replace
        if not should_replace and key in self._base_registrations:
            raise RegistrationError(f"Duplicate registration for {describe_key(key)}")
        self._base_registrations[key] = base_registration
        self._registrations[key] = registration

    def _validate_registration(self, registration: Registration) -> Registration:
        for policy in self._policies:
            try:
                policy.validate_registration(registration)
            except ValueError as exc:
                raise RegistrationError(str(exc)) from exc
        return Registration(
            service_key=registration.service_key,
            graph_key=registration.graph_key,
            lifetime=registration.lifetime,
            provider=registration.provider,
            aprovider=registration.aprovider,
            dependencies=registration.dependencies,
            description=registration.description,
            display=registration.display,
            cache_token=registration.cache_token,
            cache=registration.cache,
            activation_hooks=registration.activation_hooks,
            interceptors=registration.interceptors,
            policies=tuple(type(policy).__name__ for policy in self._policies),
        )

    def _validate_snapshot(self, snapshot: RegistrySnapshot) -> None:
        for policy in self._policies:
            try:
                policy.validate_snapshot(snapshot)
            except ValueError as exc:
                raise RegistrationError(str(exc)) from exc

    def _rebuild_registrations(self) -> None:
        self._registrations = {
            key: self._validate_registration(self._compose_registration(base_registration))
            for key, base_registration in self._base_registrations.items()
        }
        self._multi_registrations = {
            key: [self._validate_registration(self._compose_registration(base_registration)) for base_registration in registrations]
            for key, registrations in self._base_multi_registrations.items()
        }

    def _compose_registration(self, registration: Registration) -> Registration:
        registration = self._apply_activations(registration)
        return self._apply_interceptors(registration)

    def _apply_interceptors(self, registration: Registration) -> Registration:
        wrapped = registration
        for binding in sorted(self._interceptors, key=lambda item: item.order):
            wrapped = self._apply_interceptor_binding(wrapped, binding)
        return wrapped

    def _apply_activations(self, registration: Registration) -> Registration:
        wrapped = registration
        for binding in sorted(self._activations, key=lambda item: item.order):
            wrapped = self._apply_activation_binding(wrapped, binding)
        return wrapped

    def _apply_activation_binding(self, registration: Registration, binding: ActivationBinding) -> Registration:
        if not binding.predicate(registration.service_key, registration.lifetime):
            return registration

        provider = registration.provider
        aprovider = registration.aprovider

        def wrap_sync(
            current: Callable[..., Any],
            hook: Callable[..., Any],
            *,
            key: ServiceKey,
            lifetime: Lifetime,
        ) -> Callable[..., Any]:
            def invoke(resolver: Any, context: Any) -> Any:
                instance = current(resolver, context)
                result = hook(instance, key=key, lifetime=lifetime)
                return instance if result is None else result

            return invoke

        def wrap_async(
            current: Callable[..., Any],
            hook: Callable[..., Any],
            ahook: Callable[..., Any] | None,
            *,
            key: ServiceKey,
            lifetime: Lifetime,
        ) -> Callable[..., Any]:
            async def invoke(resolver: Any, context: Any) -> Any:
                instance = await maybe_await(current(resolver, context))
                target_hook = ahook or hook
                result = await maybe_await(target_hook(instance, key=key, lifetime=lifetime))
                return instance if result is None else result

            return invoke

        return Registration(
            service_key=registration.service_key,
            graph_key=registration.graph_key,
            lifetime=registration.lifetime,
            provider=wrap_sync(provider, binding.hook, key=registration.service_key, lifetime=registration.lifetime),
            aprovider=wrap_async(
                aprovider,
                binding.hook,
                binding.ahook,
                key=registration.service_key,
                lifetime=registration.lifetime,
            ),
            dependencies=registration.dependencies,
            description=registration.description,
            display=registration.display,
            cache_token=registration.cache_token,
            cache=registration.cache,
            activation_hooks=registration.activation_hooks + (getattr(binding.hook, "__name__", type(binding.hook).__name__),),
            interceptors=registration.interceptors,
            policies=registration.policies,
        )

    def _apply_interceptor_binding(self, registration: Registration, binding: InterceptorBinding) -> Registration:
        if not binding.predicate(registration.service_key, registration.lifetime):
            return registration

        provider = registration.provider
        aprovider = registration.aprovider

        def wrap_sync(
            current: Callable[..., Any],
            interceptor: Callable[..., Any],
            *,
            key: ServiceKey,
            lifetime: Lifetime,
        ) -> Callable[..., Any]:
            def invoke(resolver: Any, context: Any) -> Any:
                instance = current(resolver, context)
                return interceptor(instance, key=key, lifetime=lifetime)

            return invoke

        def wrap_async(
            current: Callable[..., Any],
            interceptor: Callable[..., Any],
            ainterceptor: Callable[..., Any] | None,
            *,
            key: ServiceKey,
            lifetime: Lifetime,
        ) -> Callable[..., Any]:
            async def invoke(resolver: Any, context: Any) -> Any:
                instance = await maybe_await(current(resolver, context))
                if ainterceptor is not None:
                    return await maybe_await(ainterceptor(instance, key=key, lifetime=lifetime))
                return interceptor(instance, key=key, lifetime=lifetime)

            return invoke

        return Registration(
            service_key=registration.service_key,
            graph_key=registration.graph_key,
            lifetime=registration.lifetime,
            provider=wrap_sync(provider, binding.interceptor, key=registration.service_key, lifetime=registration.lifetime),
            aprovider=wrap_async(
                aprovider,
                binding.interceptor,
                binding.ainterceptor,
                key=registration.service_key,
                lifetime=registration.lifetime,
            ),
            dependencies=registration.dependencies,
            description=registration.description,
            display=registration.display,
            cache_token=registration.cache_token,
            cache=registration.cache,
            activation_hooks=registration.activation_hooks,
            interceptors=registration.interceptors + (getattr(binding.interceptor, "__name__", type(binding.interceptor).__name__),),
            policies=registration.policies,
        )

    def _build_registration(
        self,
        key: ServiceKey,
        *,
        implementation: type[Any] | None,
        factory: Callable[..., Any] | None,
        instance: Any,
        lifetime: Lifetime,
        graph_suffix: str = "",
    ) -> Registration:
        choices = [
            implementation is not None,
            factory is not None,
            instance is not MISSING,
        ]
        if sum(choices) > 1:
            raise RegistrationError("Choose only one of implementation, factory, or instance")
        if instance is not MISSING:
            return Registration(
                service_key=key,
                graph_key=(key, graph_suffix) if graph_suffix else key,
                lifetime=Lifetime.SINGLETON,
                provider=lambda _resolver, _context, instance=instance: instance,
                aprovider=lambda _resolver, _context, instance=instance: instance,
                dependencies=(),
                description=f"instance for {describe_key(key)}",
                display=f"{describe_key(key)}{graph_suffix}",
            )

        if implementation is None and factory is None:
            if isinstance(key, type):
                implementation = key
            else:
                raise RegistrationError(
                    f"Registration for {describe_key(key)} requires implementation, factory, or instance"
                )

        if implementation is not None:
            self._validate_implementation(key, implementation)
            description = f"implementation {describe_key(implementation)} for {describe_key(key)}"
            plan = compile_call_plan(
                implementation,
                hint_source=implementation.__init__,
                strict=True,
                description=description,
            )
            return Registration(
                service_key=key,
                graph_key=(key, graph_suffix) if graph_suffix else key,
                lifetime=lifetime,
                provider=lambda resolver, context, plan=plan: plan.invoke(resolver, context),
                aprovider=lambda resolver, context, plan=plan: plan.ainvoke(resolver, context),
                dependencies=plan.dependencies,
                description=description,
                display=f"{describe_key(key)}{graph_suffix}",
            )

        assert factory is not None
        self._validate_factory(key, factory)
        description = f"factory {describe_key(factory)} for {describe_key(key)}"
        plan = compile_call_plan(factory, strict=True, description=description)
        return Registration(
            service_key=key,
            graph_key=(key, graph_suffix) if graph_suffix else key,
            lifetime=lifetime,
            provider=lambda resolver, context, plan=plan: plan.invoke(resolver, context),
            aprovider=lambda resolver, context, plan=plan: plan.ainvoke(resolver, context),
            dependencies=plan.dependencies,
            description=description,
            display=f"{describe_key(key)}{graph_suffix}",
        )

    def _validate_implementation(self, key: ServiceKey, implementation: type[Any]) -> None:
        if not isinstance(key, type) or not isinstance(implementation, type):
            return
        try:
            if not issubclass(implementation, key):
                raise RegistrationError(
                    f"{describe_key(implementation)} is not compatible with service {describe_key(key)}"
                )
        except TypeError:
            return

    def _validate_factory(self, key: ServiceKey, factory: Callable[..., Any]) -> None:
        hints = get_type_hints(factory, include_extras=True)
        if "return" not in hints:
            return
        dependency = dependency_from_annotation(hints["return"])
        if dependency is None:
            return
        if dependency != key:
            raise RegistrationError(
                f"Factory {describe_key(factory)} returns {describe_key(dependency)}, expected {describe_key(key)}"
            )

    def _validate_open_generic(self, service_origin: ServiceKey, implementation_origin: type[Any]) -> None:
        parameters = getattr(service_origin, "__parameters__", ())
        implementation_parameters = getattr(implementation_origin, "__parameters__", ())
        if not parameters:
            raise RegistrationError(f"Open generic service {describe_key(service_origin)} must declare type parameters")
        if parameters != implementation_parameters:
            raise RegistrationError(
                f"Open generic {describe_key(implementation_origin)} must declare the same type parameters as {describe_key(service_origin)}"
            )

    def _open_generic(
        self,
        service_origin: ServiceKey | None,
        implementation_origin: type[Any] | None,
        *,
        lifetime: Lifetime,
        replace: bool | None,
    ) -> None:
        if service_origin is None or implementation_origin is None:
            raise RegistrationError("Open generic binding requires key and implementation")
        self._validate_service_key(service_origin)
        self._validate_open_generic(service_origin, implementation_origin)
        should_replace = self._duplicate_policy is DuplicatePolicy.REPLACE if replace is None else replace
        if not should_replace and service_origin in self._open_generic_bindings:
            raise RegistrationError(f"Duplicate open generic registration for {describe_key(service_origin)}")
        self._open_generic_bindings[service_origin] = OpenGenericBinding(
            service_origin=service_origin,
            implementation_origin=implementation_origin,
            lifetime=lifetime,
            description=f"open generic {describe_key(implementation_origin)} for {describe_key(service_origin)}",
        )
