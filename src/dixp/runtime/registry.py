from __future__ import annotations

from typing import Any, Callable, get_args, get_origin

from ..core.errors import ResolutionError
from ..core.graph import (
    CallPlan,
    OpenGenericBinding,
    Registration,
    compile_call_plan,
    describe_key,
    maybe_await,
    type_var_map,
)
from ..core.models import ActivationBinding, InterceptorBinding, Lifetime, RegistrationInfo, ServiceKey
from ..core.ports import RegistryPort
from ..configuration.registry import RegistrySnapshot
from .context import injectable_spec, is_autowirable


class RuntimeRegistry(RegistryPort):
    def __init__(self, snapshot: RegistrySnapshot) -> None:
        self._registrations = dict(snapshot.registrations)
        self._multi_registrations = dict(snapshot.multi_registrations)
        self._open_generic_bindings = dict(snapshot.open_generic_bindings)
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

    def catalog(self, *, include_dynamic: bool = False) -> tuple[RegistrationInfo, ...]:
        items: list[RegistrationInfo] = []

        for registration in self._registrations.values():
            items.append(
                RegistrationInfo(
                    key=registration.service_key,
                    kind="single",
                    lifetime=registration.lifetime,
                    description=registration.description,
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
                    )
                )
        for key, binding in self._open_generic_bindings.items():
            items.append(
                RegistrationInfo(
                    key=key,
                    kind="open_generic",
                    lifetime=binding.lifetime,
                    description=binding.description,
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
                    )
                )
            for registration in self._closed_generic_registrations.values():
                items.append(
                    RegistrationInfo(
                        key=registration.service_key,
                        kind="closed_generic",
                        lifetime=registration.lifetime,
                        description=registration.description,
                    )
                )
        return tuple(sorted(items, key=lambda item: (repr(item.key), item.kind, item.description)))

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
                self._closed_generic_failures[key] = exc
                if suppress_autowire_errors:
                    return None
                raise exc
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
            failure = exc if isinstance(exc, ResolutionError) else ResolutionError(str(exc))
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
        return tuple(registrations)

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
        )
        registration = self._apply_activations(registration)
        return self._apply_interceptors(registration)

    def _specialize_open_generic(self, key: ServiceKey, binding: OpenGenericBinding) -> Registration:
        args = get_args(key)
        if not args:
            raise ResolutionError(f"Open generic resolution requires a closed generic key: {describe_key(key)}")
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
        )
        registration = self._apply_activations(registration)
        return self._apply_interceptors(registration)

    def _apply_activations(self, registration: Registration) -> Registration:
        wrapped = registration
        for binding in self._activations:
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
        )

    def _apply_interceptors(self, registration: Registration) -> Registration:
        bindings = sorted(
            (binding for binding in self._interceptors if binding.predicate(registration.service_key, registration.lifetime)),
            key=lambda item: item.order,
        )
        if not bindings:
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

        for binding in bindings:
            provider = wrap_sync(provider, binding.interceptor, key=registration.service_key, lifetime=registration.lifetime)
            aprovider = wrap_async(
                aprovider,
                binding.interceptor,
                binding.ainterceptor,
                key=registration.service_key,
                lifetime=registration.lifetime,
            )

        return Registration(
            service_key=registration.service_key,
            graph_key=registration.graph_key,
            lifetime=registration.lifetime,
            provider=provider,
            aprovider=aprovider,
            dependencies=registration.dependencies,
            description=registration.description,
            display=registration.display,
            cache_token=registration.cache_token,
            cache=registration.cache,
            activation_hooks=registration.activation_hooks,
            interceptors=registration.interceptors + tuple(
                getattr(binding.interceptor, "__name__", type(binding.interceptor).__name__) for binding in bindings
            ),
        )
