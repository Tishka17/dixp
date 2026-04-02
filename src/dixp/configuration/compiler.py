from __future__ import annotations

import inspect
from typing import Any, Callable, get_type_hints

from ..core.errors import RegistrationError
from ..core.graph import (
    DependencySpec,
    MISSING,
    OpenGenericBinding,
    Registration,
    compose_registration,
    compile_call_plan,
    dependency_from_annotation,
    describe_key,
    describe_source,
    describe_source_location,
)
from ..core.metadata import ComponentSpec
from ..core.models import (
    ActivationBinding,
    AutowirePolicy,
    BundleContract,
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
        self._bundle_contracts: dict[str, BundleContract] = {}
        self._profile = profile
        self._duplicate_policy = duplicate_policy or DuplicatePolicy.ERROR
        self._autowire_policy = autowire_policy or self._default_autowire_policy(profile)
        self._multibind_counter = 0
        self._collection_counter = 0
        self._bundle_counter = 0
        self._activations: list[ActivationBinding] = []
        self._interceptors: list[InterceptorBinding] = []

    def compile(self, entries: tuple[Any, ...]) -> RegistrySnapshot:
        for entry in entries:
            self._apply_entry(entry, owner=None)
        snapshot = RegistrySnapshot(
            registrations=dict(self._registrations),
            multi_registrations={key: tuple(registrations) for key, registrations in self._multi_registrations.items()},
            open_generic_bindings=dict(self._open_generic_bindings),
            bundle_contracts=dict(self._bundle_contracts),
            activations=tuple(self._activations),
            interceptors=tuple(self._interceptors),
            autowire_policy=self._autowire_policy,
        )
        return snapshot

    def _apply_entry(self, entry: Any, *, owner: str | None) -> None:
        if isinstance(entry, ModuleSpec):
            module_owner = self._resolve_module_owner(entry, owner=owner)
            for child in entry.entries:
                self._apply_entry(child, owner=module_owner)
            return
        if isinstance(entry, BindingSpec):
            self._apply_binding(entry, owner=owner)
            return
        if isinstance(entry, AliasSpec):
            self._apply_alias(entry, owner=owner)
            return
        if isinstance(entry, ActivationSpec):
            self._apply_activation(entry)
            return
        if isinstance(entry, InterceptorSpec):
            self._apply_interceptor(entry)
            return
        spec = getattr(entry, "__dixp_component__", None)
        if isinstance(spec, ComponentSpec):
            self._apply_component(entry, spec, owner=owner)
            return

        raise RegistrationError(code="unsupported_composition_entry", details={"entry": repr(entry)})

    def _resolve_module_owner(self, spec: ModuleSpec, *, owner: str | None) -> str | None:
        has_contract = spec.has_contract()
        if spec.name is None and not has_contract:
            return owner

        bundle = spec.name
        if bundle is None:
            self._bundle_counter += 1
            bundle = f"bundle#{self._bundle_counter}"

        contract = BundleContract(
            exports=spec.exported_keys,
            requires=spec.required_keys,
            private=tuple(dict.fromkeys(spec.private_keys)),
            layer=spec.layer_name,
            tags=tuple(dict.fromkeys(spec.tags)),
            forbid_outgoing_to=tuple(dict.fromkeys(spec.forbidden_outgoing_bundles)),
            allow_incoming_from=spec.allowed_incoming_bundles,
            forbid_outgoing_to_layers=tuple(dict.fromkeys(spec.forbidden_outgoing_layers)),
            allow_incoming_from_layers=spec.allowed_incoming_layers,
            forbid_outgoing_to_tags=tuple(dict.fromkeys(spec.forbidden_outgoing_tags)),
            allow_incoming_from_tags=spec.allowed_incoming_tags,
        )
        previous = self._bundle_contracts.get(bundle)
        if previous is None:
            self._bundle_contracts[bundle] = contract
        elif previous != contract:
            raise RegistrationError(code="conflicting_bundle_contract", details={"bundle": repr(bundle)})
        return bundle

    def _apply_component(self, entry: Any, spec: ComponentSpec, *, owner: str | None) -> None:
        key = spec.key or entry
        if inspect.isclass(entry):
            self._add_registration(
                key,
                entry,
                None,
                MISSING,
                spec.lifetime,
                replace=None,
                multiple=spec.multiple,
                owner=owner,
            )
            return
        self._add_registration(
            key,
            None,
            entry,
            MISSING,
            spec.lifetime,
            replace=None,
            multiple=spec.multiple,
            owner=owner,
        )

    def _apply_binding(self, spec: BindingSpec, *, owner: str | None) -> None:
        if spec.open_generic:
            self._open_generic(
                spec.key,
                spec.implementation,
                lifetime=spec.lifetime,
                replace=spec.replace,
                owner=owner,
            )
            return
        self._add_registration(
            spec.key,
            spec.implementation,
            spec.factory,
            spec.instance,
            spec.lifetime,
            replace=spec.replace,
            multiple=spec.multiple,
            owner=owner,
        )

    def _apply_alias(self, spec: AliasSpec, *, owner: str | None) -> None:
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
            collection_order=self._next_collection_order(),
            bundle=owner,
            source=f"alias to {describe_key(spec.target)}",
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
        owner: str | None,
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
            collection_order=self._next_collection_order(),
            owner=owner,
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
                raise RegistrationError(code="missing_factory_return_type")
            dependency = dependency_from_annotation(hints["return"])
            if dependency is None:
                raise RegistrationError(code="invalid_factory_return_key")
            return dependency
        if instance is not MISSING:
            return type(instance)
        raise RegistrationError(code="missing_service_key_or_target")

    def _default_autowire_policy(self, profile: BuildProfile) -> AutowirePolicy:
        if profile is BuildProfile.STRICT:
            return AutowirePolicy.DISABLED
        if profile is BuildProfile.ENTERPRISE:
            return AutowirePolicy.ANNOTATED
        return AutowirePolicy.IMPLICIT

    def _validate_service_key(self, key: ServiceKey) -> None:
        if self._profile is BuildProfile.ENTERPRISE and isinstance(key, str):
            raise RegistrationError(code="typed_service_key_required", details={"key": key})

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
            raise RegistrationError(code="duplicate_registration", details={"key": describe_key(key)})
        self._base_registrations[key] = base_registration
        self._registrations[key] = registration

    def _next_collection_order(self) -> int:
        self._collection_counter += 1
        return self._collection_counter

    def _validate_registration(self, registration: Registration) -> Registration:
        return Registration(
            service_key=registration.service_key,
            graph_key=registration.graph_key,
            lifetime=registration.lifetime,
            provider=registration.provider,
            aprovider=registration.aprovider,
            dependencies=registration.dependencies,
            description=registration.description,
            display=registration.display,
            collection_order=registration.collection_order,
            bundle=registration.bundle,
            source=registration.source,
            source_location=registration.source_location,
            cache_token=registration.cache_token,
            cache=registration.cache,
            activation_hooks=registration.activation_hooks,
            interceptors=registration.interceptors,
        )

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
        return compose_registration(registration, activations=self._activations, interceptors=self._interceptors)

    def _build_registration(
        self,
        key: ServiceKey,
        *,
        implementation: type[Any] | None,
        factory: Callable[..., Any] | None,
        instance: Any,
        lifetime: Lifetime,
        graph_suffix: str = "",
        collection_order: int,
        owner: str | None = None,
    ) -> Registration:
        choices = [
            implementation is not None,
            factory is not None,
            instance is not MISSING,
        ]
        if sum(choices) > 1:
            raise RegistrationError(code="multiple_binding_sources")
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
                collection_order=collection_order,
                bundle=owner,
                source=describe_source(instance, instance=True),
                source_location=describe_source_location(instance, instance=True),
            )

        if implementation is None and factory is None:
            if isinstance(key, type):
                implementation = key
            else:
                raise RegistrationError(code="missing_binding_target", details={"key": describe_key(key)})

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
                collection_order=collection_order,
                bundle=owner,
                source=describe_source(implementation),
                source_location=describe_source_location(implementation),
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
            collection_order=collection_order,
            bundle=owner,
            source=describe_source(factory),
            source_location=describe_source_location(factory),
        )

    def _validate_implementation(self, key: ServiceKey, implementation: type[Any]) -> None:
        if not isinstance(key, type) or not isinstance(implementation, type):
            return
        try:
            if not issubclass(implementation, key):
                raise RegistrationError(
                    code="incompatible_implementation",
                    details={
                        "implementation": describe_key(implementation),
                        "key": describe_key(key),
                    },
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
                code="factory_return_mismatch",
                details={
                    "factory": describe_key(factory),
                    "returned": describe_key(dependency),
                    "key": describe_key(key),
                },
            )

    def _validate_open_generic(self, service_origin: ServiceKey, implementation_origin: type[Any]) -> None:
        parameters = getattr(service_origin, "__parameters__", ())
        implementation_parameters = getattr(implementation_origin, "__parameters__", ())
        if not parameters:
            raise RegistrationError(
                code="open_generic_missing_parameters",
                details={"key": describe_key(service_origin)},
            )
        if parameters != implementation_parameters:
            raise RegistrationError(
                code="open_generic_parameters_mismatch",
                details={
                    "implementation": describe_key(implementation_origin),
                    "key": describe_key(service_origin),
                },
            )

    def _open_generic(
        self,
        service_origin: ServiceKey | None,
        implementation_origin: type[Any] | None,
        *,
        lifetime: Lifetime,
        replace: bool | None,
        owner: str | None,
    ) -> None:
        if service_origin is None or implementation_origin is None:
            raise RegistrationError(code="open_generic_missing_parts")
        self._validate_service_key(service_origin)
        self._validate_open_generic(service_origin, implementation_origin)
        should_replace = self._duplicate_policy is DuplicatePolicy.REPLACE if replace is None else replace
        if not should_replace and service_origin in self._open_generic_bindings:
            raise RegistrationError(
                code="duplicate_open_generic_registration",
                details={"key": describe_key(service_origin)},
            )
        self._open_generic_bindings[service_origin] = OpenGenericBinding(
            service_origin=service_origin,
            implementation_origin=implementation_origin,
            lifetime=lifetime,
            description=f"open generic {describe_key(implementation_origin)} for {describe_key(service_origin)}",
            collection_order=self._next_collection_order(),
            bundle=owner,
            source=describe_source(implementation_origin),
            source_location=describe_source_location(implementation_origin),
        )
