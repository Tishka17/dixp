from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from types import NoneType, UnionType
from enum import Enum
from typing import Annotated, Any, Callable, TypeVar, Union, get_args, get_origin, get_type_hints

from .errors import ResolutionError
from .models import Factory, Inject, Lazy, Lifetime, Provider, Qualifier, ServiceKey

T = TypeVar("T")
ResolverProvider = Callable[[Any, Any], Any]
MISSING = object()


def describe_key(key: ServiceKey) -> str:
    if isinstance(key, Qualifier):
        scope = f"{key.namespace}:" if key.namespace else ""
        return f"{describe_key(key.key)}@{scope}{key.name}"
    if isinstance(key, type):
        return f"{key.__module__}.{key.__qualname__}"
    return repr(key)


def collection_spec(key: ServiceKey) -> tuple[type[Any], ServiceKey] | None:
    origin = get_origin(key)
    args = get_args(key)
    if origin is list and len(args) == 1:
        return list, args[0]
    if origin is tuple and len(args) == 2 and args[1] is Ellipsis:
        return tuple, args[0]
    return None


def is_optional(annotation: Any) -> tuple[Any, bool]:
    origin = get_origin(annotation)
    if origin not in (UnionType, Union):
        return annotation, False

    args = [arg for arg in get_args(annotation) if arg is not NoneType]
    if len(args) == 1:
        return args[0], True
    return annotation, False


def dependency_from_annotation(annotation: Any) -> ServiceKey | None:
    if annotation in (inspect._empty, Any):
        return None

    inject_metadata: Inject | None = None
    origin = get_origin(annotation)
    if origin is Annotated:
        base_annotation, *metadata = get_args(annotation)
        annotation = base_annotation
        for item in metadata:
            if isinstance(item, Inject):
                inject_metadata = item
    annotation, _ = is_optional(annotation)
    if inject_metadata is not None and inject_metadata.key is not None:
        return inject_metadata.key
    if annotation is Any:
        return None
    if inject_metadata is not None:
        return annotation
    return annotation


class RequestKind(str, Enum):
    DIRECT = "direct"
    PROVIDER = "provider"
    FACTORY = "factory"
    LAZY = "lazy"


@dataclass(frozen=True, slots=True)
class RequestSpec:
    kind: RequestKind
    key: ServiceKey


def request_from_annotation(annotation: Any) -> RequestSpec | None:
    if annotation in (inspect._empty, Any):
        return None

    inject_metadata: Inject | None = None
    origin = get_origin(annotation)
    if origin is Annotated:
        base_annotation, *metadata = get_args(annotation)
        annotation = base_annotation
        for item in metadata:
            if isinstance(item, Inject):
                inject_metadata = item

    annotation, _ = is_optional(annotation)
    request_origin = get_origin(annotation)
    requested_key = inject_metadata.key if inject_metadata is not None and inject_metadata.key is not None else None

    if request_origin in (Provider, Factory, Lazy):
        args = get_args(annotation)
        if len(args) != 1:
            return None
        dependency = requested_key or dependency_from_annotation(args[0])
        if dependency is None:
            return None
        if request_origin is Provider:
            kind = RequestKind.PROVIDER
        elif request_origin is Factory:
            kind = RequestKind.FACTORY
        else:
            kind = RequestKind.LAZY
        return RequestSpec(kind=kind, key=dependency)

    dependency = requested_key or dependency_from_annotation(annotation)
    if dependency is None:
        return None
    return RequestSpec(kind=RequestKind.DIRECT, key=dependency)


def request_wrapper_spec(annotation: Any) -> RequestSpec | None:
    request = request_from_annotation(annotation)
    if request is None or request.kind is RequestKind.DIRECT:
        return None
    return request


def substitute_typevars(annotation: Any, mapping: dict[TypeVar, Any]) -> Any:
    if not mapping:
        return annotation
    if isinstance(annotation, TypeVar):
        return mapping.get(annotation, annotation)

    origin = get_origin(annotation)
    if origin is None:
        return annotation

    if origin is Annotated:
        base_annotation, *metadata = get_args(annotation)
        substituted = substitute_typevars(base_annotation, mapping)
        return Annotated.__class_getitem__((substituted, *metadata))

    args = tuple(substitute_typevars(arg, mapping) for arg in get_args(annotation))
    if origin in (Union, UnionType):
        result = args[0]
        for arg in args[1:]:
            result = result | arg
        return result
    if len(args) == 1:
        return origin[args[0]]
    return origin[args]


def type_var_map(origin: Any, args: tuple[Any, ...]) -> dict[TypeVar, Any]:
    parameters = getattr(origin, "__parameters__", ())
    return dict(zip(parameters, args, strict=False))


def maybe_awaitable_close(value: Any) -> None:
    close = getattr(value, "close", None)
    if callable(close):
        close()


async def maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


@dataclass(frozen=True, slots=True)
class ParameterPlan:
    name: str
    request: RequestSpec | None
    has_default: bool
    default: Any


@dataclass(frozen=True, slots=True)
class DependencySpec:
    key: ServiceKey
    has_default: bool


@dataclass(frozen=True, slots=True)
class OpenGenericBinding:
    service_origin: ServiceKey
    implementation_origin: type[Any]
    lifetime: Lifetime
    description: str


@dataclass(frozen=True, slots=True)
class CallPlan:
    target: Callable[..., Any]
    signature: inspect.Signature
    parameters: tuple[ParameterPlan, ...]
    dependencies: tuple[DependencySpec, ...]
    description: str

    def invoke(
        self,
        resolver: Any,
        context: Any,
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
    ) -> Any:
        bound = self.signature.bind_partial(*args, **(kwargs or {}))
        for parameter in self.parameters:
            if parameter.name in bound.arguments:
                continue
            if parameter.request is None:
                if parameter.has_default:
                    continue
                raise ResolutionError(
                    f"Cannot inject required parameter {parameter.name!r} for {self.description}"
                )
            if parameter.has_default and not resolver._can_resolve_request(parameter.request):
                continue
            bound.arguments[parameter.name] = resolver._resolve_request(parameter.request, context)
        try:
            result = self.target(*bound.args, **bound.kwargs)
        except TypeError as exc:
            raise ResolutionError(f"Failed to invoke {self.description}: {exc}") from exc
        if inspect.isawaitable(result):
            maybe_awaitable_close(result)
            raise ResolutionError(f"{self.description} is async; use the async API")
        return result

    async def ainvoke(
        self,
        resolver: Any,
        context: Any,
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
    ) -> Any:
        bound = self.signature.bind_partial(*args, **(kwargs or {}))
        for parameter in self.parameters:
            if parameter.name in bound.arguments:
                continue
            if parameter.request is None:
                if parameter.has_default:
                    continue
                raise ResolutionError(
                    f"Cannot inject required parameter {parameter.name!r} for {self.description}"
                )
            if parameter.has_default and not resolver._can_resolve_request(parameter.request):
                continue
            bound.arguments[parameter.name] = await resolver._aresolve_request(parameter.request, context)
        try:
            return await maybe_await(self.target(*bound.args, **bound.kwargs))
        except TypeError as exc:
            raise ResolutionError(f"Failed to invoke {self.description}: {exc}") from exc


def compile_call_plan(
    target: Callable[..., Any],
    *,
    hint_source: Callable[..., Any] | None = None,
    strict: bool,
    description: str,
    type_var_mapping: dict[TypeVar, Any] | None = None,
) -> CallPlan:
    signature = inspect.signature(target)
    hints = get_type_hints(hint_source or target, include_extras=True)
    mapping = type_var_mapping or {}
    parameters: list[ParameterPlan] = []
    dependencies: list[DependencySpec] = []

    for parameter in signature.parameters.values():
        if parameter.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        annotation = substitute_typevars(hints.get(parameter.name, parameter.annotation), mapping)
        request = request_from_annotation(annotation)
        has_default = parameter.default is not inspect._empty
        if strict and request is None and not has_default:
            raise ResolutionError(
                f"Cannot compile {description}: parameter {parameter.name!r} has no injectable type hint. "
                "Add a type annotation, use `Annotated[..., Inject(...)]`, or give the parameter a default value."
            )
        parameters.append(
            ParameterPlan(
                name=parameter.name,
                request=request,
                has_default=has_default,
                default=parameter.default if has_default else MISSING,
            )
        )
        if request is not None:
            dependencies.append(DependencySpec(key=request.key, has_default=has_default))
    return CallPlan(
        target=target,
        signature=signature,
        parameters=tuple(parameters),
        dependencies=tuple(dependencies),
        description=description,
    )


@dataclass(slots=True)
class Registration:
    service_key: ServiceKey
    graph_key: ServiceKey
    lifetime: Lifetime
    provider: ResolverProvider
    aprovider: ResolverProvider
    dependencies: tuple[DependencySpec, ...]
    description: str
    display: str
    cache_token: object = field(default_factory=object)
    cache: bool = True
    activation_hooks: tuple[str, ...] = ()
    interceptors: tuple[str, ...] = ()

    def resolve(self, resolver: Any, context: Any) -> Any:
        if not self.cache or self.lifetime is Lifetime.TRANSIENT:
            value = self.provider(resolver, context)
            if inspect.isawaitable(value):
                maybe_awaitable_close(value)
                raise ResolutionError(
                    f"{self.description} is async and cannot be resolved through the synchronous API"
                )
            return value
        if self.lifetime is Lifetime.SINGLETON:
            return resolver._container._singleton_value(self.cache_token, lambda: self.provider(resolver, context))
        return resolver._scoped_value(self.cache_token, lambda: self.provider(resolver, context))

    async def aresolve(self, resolver: Any, context: Any) -> Any:
        if not self.cache or self.lifetime is Lifetime.TRANSIENT:
            return await maybe_await(self.aprovider(resolver, context))
        if self.lifetime is Lifetime.SINGLETON:
            return await resolver._container._async_singleton_value(
                self.cache_token,
                lambda: self.aprovider(resolver, context),
            )
        return await resolver._async_scoped_value(
            self.cache_token,
            lambda: self.aprovider(resolver, context),
        )
