from __future__ import annotations

from contextlib import ExitStack, contextmanager
from contextvars import ContextVar, Token
from typing import Any, Callable, TypeVar

from ..core.errors import AmbientResolverError, ContainerClosedError, InvalidOverrideError, MissingRegistrationError
from ..core.graph import (
    MISSING,
    Registration,
    RequestKind,
    RequestSpec,
    collection_spec,
    compile_call_plan,
    describe_key,
    describe_source,
    describe_source_location,
    request_wrapper_spec,
)
from ..core.models import Factory, Lazy, Lifetime, Provider, RegistrationInfo, ServiceKey
from ..core.ports import CachePort, InspectorPort, RegistryPort
from ..core.resolution import ResolutionContext
from ..configuration.registry import RegistrySnapshot
from ..inspection.graph import DoctorReport, GraphInspector
from .cache import InstanceCache
from .registry import RuntimeRegistry

T = TypeVar("T")
ContextBinding = tuple[ServiceKey, Any]
_CURRENT_RESOLVER: ContextVar["_Resolver | None"] = ContextVar("dixp_current_resolver", default=None)


def current_resolver() -> "Container | Scope":
    resolver = _CURRENT_RESOLVER.get()
    if resolver is None:
        raise AmbientResolverError(
            details={"hint": "Use `with container.activate(...):` or `with scope.activate():`."}
        )
    return resolver


class _ActiveResolverContext:
    def __init__(self, resolver: "_Resolver", bindings: tuple[ContextBinding, ...]) -> None:
        self._base_resolver = resolver
        self._bindings = bindings
        self._active_resolver: "_Resolver" = resolver
        self._scope: Scope | None = None
        self._stack: ExitStack | None = None
        self._token: Token[_Resolver | None] | None = None

    def __enter__(self) -> "Container | Scope":
        self._base_resolver._assert_open()
        scope = self._base_resolver.scope()
        stack = ExitStack()
        try:
            for key, value in self._bindings:
                stack.enter_context(scope.override(key, value))
            self._active_resolver = scope
            self._scope = scope
            self._stack = stack
        except Exception:
            stack.close()
            scope.close()
            raise
        self._token = _CURRENT_RESOLVER.set(self._active_resolver)
        return self._active_resolver

    def __exit__(self, *_: Any) -> None:
        if self._token is not None:
            _CURRENT_RESOLVER.reset(self._token)
            self._token = None
        if self._stack is not None:
            self._stack.close()
            self._stack = None
        if self._scope is not None:
            self._scope.close()
            self._scope = None

    async def __aenter__(self) -> "Container | Scope":
        return self.__enter__()

    async def __aexit__(self, *_: Any) -> None:
        if self._token is not None:
            _CURRENT_RESOLVER.reset(self._token)
            self._token = None
        if self._stack is not None:
            self._stack.close()
            self._stack = None
        if self._scope is not None:
            await self._scope.aclose()
            self._scope = None


class _Resolver:
    _container: "Container"
    _override_parent: "_Resolver | None"

    def __init__(self) -> None:
        self._overrides: dict[ServiceKey, list[Registration]] = {}

    def _assert_open(self) -> None:
        return None

    def _missing_registration_details(self, key: ServiceKey) -> dict[str, object]:
        target = describe_key(key)
        suggestions = [
            f"add `@service(provides={target})` to an implementation",
            f"wire it explicitly with `app.bind({target}).singleton(...)` or `.to(...)`",
            f"or provide a concrete value with `app.bind({target}).value(...)`",
        ]
        if isinstance(key, str):
            suggestions = [
                "use a typed key instead of a bare string in app code",
                f"or bind the string explicitly with `app.bind({key!r}).value(...)`",
            ]
        return {"key": target, "suggestions": tuple(suggestions)}

    def __getitem__(self, key: ServiceKey) -> Any:
        return self.get(key)

    def __contains__(self, key: ServiceKey) -> bool:
        return self.has(key)

    def resolve(self, key: ServiceKey) -> Any:
        self._assert_open()
        return self._resolve(key, ResolutionContext())

    def get(self, key: ServiceKey) -> Any:
        return self.resolve(key)

    async def aresolve(self, key: ServiceKey) -> Any:
        self._assert_open()
        return await self._aresolve(key, ResolutionContext())

    async def aget(self, key: ServiceKey) -> Any:
        return await self.aresolve(key)

    def try_resolve(self, key: ServiceKey, default: T | None = None) -> Any | T | None:
        self._assert_open()
        if not self._can_resolve(key):
            return default
        return self.resolve(key)

    def maybe(self, key: ServiceKey, default: T | None = None) -> Any | T | None:
        return self.try_resolve(key, default)

    def can_resolve(self, key: ServiceKey) -> bool:
        self._assert_open()
        return self._can_resolve(key)

    def has(self, key: ServiceKey) -> bool:
        return self.can_resolve(key)

    def invoke(self, target: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
        self._assert_open()
        plan = self._container._registry.invocation_plan(target)
        return plan.invoke(self, ResolutionContext(), args=args, kwargs=kwargs)

    def call(self, target: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
        return self.invoke(target, *args, **kwargs)

    async def ainvoke(self, target: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
        self._assert_open()
        plan = self._container._registry.invocation_plan(target)
        return await plan.ainvoke(self, ResolutionContext(), args=args, kwargs=kwargs)

    async def acall(self, target: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
        return await self.ainvoke(target, *args, **kwargs)

    def scope(self) -> "Scope":
        self._assert_open()
        return Scope(self._container, override_parent=self)

    def child(self) -> "Scope":
        return self.scope()

    def activate(self, *bindings: ContextBinding) -> _ActiveResolverContext:
        self._assert_open()
        return _ActiveResolverContext(self, tuple(bindings))

    def warmup(self, *keys: ServiceKey) -> "_Resolver":
        self._assert_open()
        for key in keys:
            self.resolve(key)
        return self

    async def awarmup(self, *keys: ServiceKey) -> "_Resolver":
        self._assert_open()
        for key in keys:
            await self.aresolve(key)
        return self

    @contextmanager
    def override(
        self,
        key: ServiceKey,
        value: Any = MISSING,
        *,
        implementation: type[Any] | None = None,
        factory: Callable[..., Any] | None = None,
        lifetime: Lifetime = Lifetime.TRANSIENT,
    ) -> Any:
        self._assert_open()
        registration = self._container._build_override_registration(
            key,
            value=value,
            implementation=implementation,
            factory=factory,
            lifetime=lifetime,
        )
        stack = self._overrides.setdefault(key, [])
        stack.append(registration)
        try:
            yield self
        finally:
            stack.pop()
            if not stack:
                self._overrides.pop(key, None)

    def _resolve(self, key: ServiceKey, context: ResolutionContext) -> Any:
        request = request_wrapper_spec(key)
        if request is not None:
            return self._resolve_request(request, context)
        collection = collection_spec(key)
        if collection is not None:
            return self._resolve_collection(key, context)
        registration = self._find_registration(key, suppress_autowire_errors=False)
        if registration is None:
            raise MissingRegistrationError(details=self._missing_registration_details(key))
        nested_context = context.enter(registration.graph_key, registration.lifetime, display=registration.display)
        return registration.resolve(self, nested_context)

    async def _aresolve(self, key: ServiceKey, context: ResolutionContext) -> Any:
        request = request_wrapper_spec(key)
        if request is not None:
            return await self._aresolve_request(request, context)
        collection = collection_spec(key)
        if collection is not None:
            return await self._aresolve_collection(key, context)
        registration = self._find_registration(key, suppress_autowire_errors=False)
        if registration is None:
            raise MissingRegistrationError(details=self._missing_registration_details(key))
        nested_context = context.enter(registration.graph_key, registration.lifetime, display=registration.display)
        return await registration.aresolve(self, nested_context)

    def _find_registration(self, key: ServiceKey, *, suppress_autowire_errors: bool) -> Registration | None:
        override = self._find_override(key)
        if override is not None:
            return override
        return self._container._registry.registration_for(key, suppress_autowire_errors=suppress_autowire_errors)

    def _find_override(self, key: ServiceKey) -> Registration | None:
        stack = self._overrides.get(key)
        if stack:
            return stack[-1]
        if self._override_parent is not None:
            return self._override_parent._find_override(key)
        return None

    def _can_resolve(self, key: ServiceKey) -> bool:
        request = request_wrapper_spec(key)
        if request is not None:
            return self._can_resolve_request(request)
        if collection_spec(key) is not None:
            return True
        return self._find_override(key) is not None or self._container._registry.can_resolve(key)

    def _provider_for(self, key: ServiceKey, context: ResolutionContext) -> Provider[Any]:
        return Provider(
            getter=lambda key=key, context=context: self._resolve(key, context),
            agetter=lambda key=key, context=context: self._aresolve(key, context),
        )

    def _resolve_request(self, request: RequestSpec, context: ResolutionContext) -> Any:
        if request.kind is RequestKind.DIRECT:
            return self._resolve(request.key, context)
        if request.kind is RequestKind.PROVIDER:
            return self._provider_for(request.key, context)
        if request.kind is RequestKind.FACTORY:
            return Factory(self._provider_for(request.key, context))
        return Lazy(self._provider_for(request.key, context))

    async def _aresolve_request(self, request: RequestSpec, context: ResolutionContext) -> Any:
        return self._resolve_request(request, context)

    def _can_resolve_request(self, request: RequestSpec) -> bool:
        return self._can_resolve(request.key)

    def resolve_all(self, key: ServiceKey) -> tuple[Any, ...]:
        self._assert_open()
        return self._resolve_all(key, ResolutionContext())

    def all(self, key: ServiceKey) -> tuple[Any, ...]:
        return self.resolve_all(key)

    async def aresolve_all(self, key: ServiceKey) -> tuple[Any, ...]:
        self._assert_open()
        return await self._aresolve_all(key, ResolutionContext())

    async def aall(self, key: ServiceKey) -> tuple[Any, ...]:
        return await self.aresolve_all(key)

    def _resolve_collection(self, key: ServiceKey, context: ResolutionContext) -> Any:
        kind, item_key = collection_spec(key) or (None, None)
        assert kind is not None
        values = self._resolve_all(item_key, context.enter(key, Lifetime.TRANSIENT))
        return list(values) if kind is list else values

    async def _aresolve_collection(self, key: ServiceKey, context: ResolutionContext) -> Any:
        kind, item_key = collection_spec(key) or (None, None)
        assert kind is not None
        values = await self._aresolve_all(item_key, context.enter(key, Lifetime.TRANSIENT))
        return list(values) if kind is list else values

    def _resolve_all(self, key: ServiceKey, context: ResolutionContext) -> tuple[Any, ...]:
        values: list[Any] = []
        for registration in self._container._registry.registrations_for_collection(key, suppress_autowire_errors=False):
            nested_context = context.enter(registration.graph_key, registration.lifetime, display=registration.display)
            values.append(registration.resolve(self, nested_context))
        return tuple(values)

    async def _aresolve_all(self, key: ServiceKey, context: ResolutionContext) -> tuple[Any, ...]:
        values: list[Any] = []
        for registration in self._container._registry.registrations_for_collection(
            key,
            suppress_autowire_errors=False,
        ):
            nested_context = context.enter(registration.graph_key, registration.lifetime, display=registration.display)
            values.append(await registration.aresolve(self, nested_context))
        return tuple(values)

    def _scoped_value(self, cache_token: object, factory: Callable[[], Any]) -> Any:
        raise NotImplementedError

    async def _async_scoped_value(self, cache_token: object, factory: Callable[[], Any]) -> Any:
        raise NotImplementedError


class Container(_Resolver):
    def __init__(self, snapshot: RegistrySnapshot) -> None:
        super().__init__()
        self._container = self
        self._override_parent = None
        self._registry: RegistryPort = RuntimeRegistry(snapshot)
        self._inspector: InspectorPort = GraphInspector(self._registry)
        self._singleton_cache: CachePort = InstanceCache(async_error_scope="singleton")
        self._closed = False

    def __enter__(self) -> "Container":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    async def __aenter__(self) -> "Container":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.aclose()

    def _assert_open(self) -> None:
        if self._closed:
            raise ContainerClosedError(details={"target": "container"})

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._singleton_cache.close()

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._singleton_cache.aclose()

    def validate(self, *roots: ServiceKey) -> None:
        self._assert_open()
        self._inspector.validate(*roots)

    def catalog(self, *, include_dynamic: bool = False) -> tuple[RegistrationInfo, ...]:
        self._assert_open()
        return self._registry.catalog(include_dynamic=include_dynamic)

    def explain(self, key: ServiceKey) -> str:
        self._assert_open()
        return self._inspector.explain(key)

    def doctor(self, *roots: ServiceKey) -> DoctorReport:
        self._assert_open()
        return self._inspector.doctor(*roots)

    def _scoped_value(self, cache_token: object, factory: Callable[[], Any]) -> Any:
        return self._singleton_value(cache_token, factory)

    def _singleton_value(self, cache_token: object, factory: Callable[[], Any]) -> Any:
        return self._singleton_cache.get_or_create(cache_token, factory)

    async def _async_singleton_value(self, cache_token: object, factory: Callable[[], Any]) -> Any:
        return await self._singleton_cache.aget_or_create(cache_token, factory)

    def _build_override_registration(
        self,
        key: ServiceKey,
        *,
        value: Any = MISSING,
        implementation: type[Any] | None = None,
        factory: Callable[..., Any] | None = None,
        lifetime: Lifetime,
    ) -> Registration:
        if value is not MISSING:
            registration = Registration(
                service_key=key,
                graph_key=key,
                lifetime=Lifetime.SINGLETON,
                provider=lambda _resolver, _context, value=value: value,
                aprovider=lambda _resolver, _context, value=value: value,
                dependencies=(),
                description=f"override instance for {describe_key(key)}",
                display=describe_key(key),
                source=describe_source(value, instance=True),
                source_location=describe_source_location(value, instance=True),
            )
            return self._registry.compose_registration(registration)
        if implementation is not None:
            description = f"override implementation {describe_key(implementation)} for {describe_key(key)}"
            plan = compile_call_plan(
                implementation,
                hint_source=implementation.__init__,
                strict=True,
                description=description,
            )
            registration = Registration(
                service_key=key,
                graph_key=key,
                lifetime=lifetime,
                provider=lambda resolver, context, plan=plan: plan.invoke(resolver, context),
                aprovider=lambda resolver, context, plan=plan: plan.ainvoke(resolver, context),
                dependencies=plan.dependencies,
                description=description,
                display=describe_key(key),
                source=describe_source(implementation),
                source_location=describe_source_location(implementation),
            )
            return self._registry.compose_registration(registration)
        if factory is not None:
            description = f"override factory {describe_key(factory)} for {describe_key(key)}"
            plan = compile_call_plan(factory, strict=True, description=description)
            registration = Registration(
                service_key=key,
                graph_key=key,
                lifetime=lifetime,
                provider=lambda resolver, context, plan=plan: plan.invoke(resolver, context),
                aprovider=lambda resolver, context, plan=plan: plan.ainvoke(resolver, context),
                dependencies=plan.dependencies,
                description=description,
                display=describe_key(key),
                source=describe_source(factory),
                source_location=describe_source_location(factory),
            )
            return self._registry.compose_registration(registration)
        raise InvalidOverrideError(details={"key": describe_key(key)})


class Scope(_Resolver):
    def __init__(self, container: Container, *, override_parent: _Resolver | None = None) -> None:
        super().__init__()
        self._container = container
        self._override_parent = override_parent
        self._scoped_cache: CachePort = InstanceCache(async_error_scope="scoped")
        self._closed = False

    def __enter__(self) -> "Scope":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    async def __aenter__(self) -> "Scope":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.aclose()

    def _assert_open(self) -> None:
        if self._closed or self._container._closed:
            raise ContainerClosedError(details={"target": "scope"})

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._scoped_cache.close()

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._scoped_cache.aclose()

    def _scoped_value(self, cache_token: object, factory: Callable[[], Any]) -> Any:
        return self._scoped_cache.get_or_create(cache_token, factory)

    async def _async_scoped_value(self, cache_token: object, factory: Callable[[], Any]) -> Any:
        return await self._scoped_cache.aget_or_create(cache_token, factory)
