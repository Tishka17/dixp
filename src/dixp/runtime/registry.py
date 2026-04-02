from __future__ import annotations

from typing import Any, Callable, get_args, get_origin

from ..core.errors import AutowireError, OpenGenericResolutionError, ResolutionError
from ..core.graph import (
    CallPlan,
    OpenGenericBinding,
    Registration,
    compose_registration,
    compile_call_plan,
    describe_key,
    describe_source,
    describe_source_location,
    type_var_map,
)
from ..core.models import BundleContract, Lifetime, RegistrationInfo, ServiceKey
from ..core.ports import RegistryPort
from ..configuration.registry import RegistrySnapshot
from .context import injectable_spec, is_autowirable


class RuntimeRegistry(RegistryPort):
    def __init__(self, snapshot: RegistrySnapshot) -> None:
        self._registrations = dict(snapshot.registrations)
        self._multi_registrations = dict(snapshot.multi_registrations)
        self._open_generic_bindings = dict(snapshot.open_generic_bindings)
        self._bundle_contracts = dict(snapshot.bundle_contracts)
        self._activations = tuple(sorted(snapshot.activations, key=lambda item: item.order))
        self._interceptors = tuple(sorted(snapshot.interceptors, key=lambda item: item.order))
        self._autowire_policy = snapshot.autowire_policy
        self._autowire_registrations: dict[ServiceKey, Registration] = {}
        self._autowire_failures: dict[ServiceKey, ResolutionError] = {}
        self._closed_generic_registrations: dict[ServiceKey, Registration] = {}
        self._closed_generic_failures: dict[ServiceKey, ResolutionError] = {}
        self._invocation_plans: dict[Callable[..., Any], CallPlan] = {}

    def root_keys(self) -> tuple[ServiceKey, ...]:
        return tuple(dict.fromkeys((*self._registrations.keys(), *self._multi_registrations.keys())))

    def can_resolve(self, key: ServiceKey) -> bool:
        return self.registration_for(key, suppress_autowire_errors=True) is not None

    def bundle_contract(self, name: str) -> BundleContract | None:
        return self._bundle_contracts.get(name)

    def catalog(self, *, include_dynamic: bool = False) -> tuple[RegistrationInfo, ...]:
        items: list[RegistrationInfo] = []

        for registration in self._registrations.values():
            items.append(
                RegistrationInfo(
                    key=registration.service_key,
                    kind="single",
                    lifetime=registration.lifetime,
                    description=registration.description,
                    bundle=registration.bundle,
                    source=registration.source,
                    source_location=registration.source_location,
                )
            )
        for key, registrations in self._multi_registrations.items():
            for registration in registrations:
                items.append(
                    RegistrationInfo(
                        key=key,
                        kind="multi",
                        lifetime=registration.lifetime,
                        description=registration.description,
                        bundle=registration.bundle,
                        source=registration.source,
                        source_location=registration.source_location,
                    )
                )
        for key, binding in self._open_generic_bindings.items():
            items.append(
                RegistrationInfo(
                    key=key,
                    kind="open_generic",
                    lifetime=binding.lifetime,
                    description=binding.description,
                    bundle=getattr(binding, "bundle", None),
                    source=getattr(binding, "source", None),
                    source_location=getattr(binding, "source_location", None),
                )
            )
        if include_dynamic:
            for registration in self._autowire_registrations.values():
                items.append(
                    RegistrationInfo(
                        key=registration.service_key,
                        kind="autowire",
                        lifetime=registration.lifetime,
                        description=registration.description,
                        bundle=registration.bundle,
                        source=registration.source,
                        source_location=registration.source_location,
                    )
                )
            for registration in self._closed_generic_registrations.values():
                items.append(
                    RegistrationInfo(
                        key=registration.service_key,
                        kind="closed_generic",
                        lifetime=registration.lifetime,
                        description=registration.description,
                        bundle=registration.bundle,
                        source=registration.source,
                        source_location=registration.source_location,
                    )
                )
        return tuple(sorted(items, key=lambda item: (repr(item.key), item.kind, item.description)))

    def compose_registration(self, registration: Registration) -> Registration:
        return compose_registration(registration, activations=self._activations, interceptors=self._interceptors)

    def registration_for(self, key: ServiceKey, *, suppress_autowire_errors: bool) -> Registration | None:
        registration = self._registrations.get(key)
        if registration is not None:
            return registration
        generic_failure = self._closed_generic_failures.get(key)
        if generic_failure is not None:
            if suppress_autowire_errors:
                return None
            raise generic_failure
        generic_registration = self._closed_generic_registrations.get(key)
        if generic_registration is not None:
            return generic_registration
        origin = get_origin(key)
        if origin in self._open_generic_bindings:
            try:
                registration = self._specialize_open_generic(key, self._open_generic_bindings[origin])
            except ResolutionError as exc:
                failure = (
                    exc
                    if isinstance(exc, OpenGenericResolutionError)
                    else OpenGenericResolutionError(details={"key": describe_key(key), "reason": str(exc)})
                )
                self._closed_generic_failures[key] = failure
                if suppress_autowire_errors:
                    return None
                raise failure
            self._closed_generic_registrations[key] = registration
            return registration
        failure = self._autowire_failures.get(key)
        if failure is not None:
            if suppress_autowire_errors:
                return None
            raise failure
        if key in self._autowire_registrations:
            return self._autowire_registrations[key]
        if not is_autowirable(key, self._autowire_policy):
            return None
        try:
            registration = self._autowire_registration(key)
        except (TypeError, ValueError, ResolutionError) as exc:
            failure = AutowireError(details={"key": describe_key(key), "reason": str(exc)})
            self._autowire_failures[key] = failure
            if suppress_autowire_errors:
                return None
            raise failure
        self._autowire_registrations[key] = registration
        return registration

    def registrations_for_collection(
        self,
        key: ServiceKey,
        *,
        suppress_autowire_errors: bool,
    ) -> tuple[Registration, ...]:
        registrations: list[Registration] = []
        single = self.registration_for(key, suppress_autowire_errors=suppress_autowire_errors)
        if single is not None:
            registrations.append(single)
        registrations.extend(self._multi_registrations.get(key, ()))
        return tuple(sorted(registrations, key=lambda registration: registration.collection_order))

    def invocation_plan(self, target: Callable[..., Any]) -> CallPlan:
        plan = self._invocation_plans.get(target)
        if plan is None:
            plan = compile_call_plan(
                target,
                strict=False,
                description=f"callable {describe_key(target)}",
            )
            self._invocation_plans[target] = plan
        return plan

    def _autowire_registration(self, implementation: type[Any]) -> Registration:
        spec = injectable_spec(implementation)
        lifetime = spec.lifetime if spec is not None else Lifetime.TRANSIENT
        description = f"autowired {describe_key(implementation)}"
        plan = compile_call_plan(
            implementation,
            hint_source=implementation.__init__,
            strict=True,
            description=description,
        )
        registration = Registration(
            service_key=implementation,
            graph_key=implementation,
            lifetime=lifetime,
            provider=lambda resolver, context, plan=plan: plan.invoke(resolver, context),
            aprovider=lambda resolver, context, plan=plan: plan.ainvoke(resolver, context),
            dependencies=plan.dependencies,
            description=description,
            display=describe_key(implementation),
            bundle=None,
            source=describe_source(implementation),
            source_location=describe_source_location(implementation),
        )
        return self.compose_registration(registration)

    def _specialize_open_generic(self, key: ServiceKey, binding: OpenGenericBinding) -> Registration:
        args = get_args(key)
        if not args:
            raise OpenGenericResolutionError(details={"key": describe_key(key), "needs_closed_key": True})
        implementation_map = type_var_map(binding.implementation_origin, args)
        description = f"{binding.description} for {describe_key(key)}"
        plan = compile_call_plan(
            binding.implementation_origin,
            hint_source=binding.implementation_origin.__init__,
            strict=True,
            description=description,
            type_var_mapping=implementation_map,
        )
        registration = Registration(
            service_key=key,
            graph_key=key,
            lifetime=binding.lifetime,
            provider=lambda resolver, context, plan=plan: plan.invoke(resolver, context),
            aprovider=lambda resolver, context, plan=plan: plan.ainvoke(resolver, context),
            dependencies=plan.dependencies,
            description=description,
            display=describe_key(key),
            collection_order=binding.collection_order,
            bundle=getattr(binding, "bundle", None),
            source=getattr(binding, "source", None),
            source_location=getattr(binding, "source_location", None),
        )
        return self.compose_registration(registration)
