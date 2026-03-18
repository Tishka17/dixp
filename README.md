# dixp

`dixp` is a type-driven IoC container for Python built around an immutable
composition API. The recommended surface is `Builder`, `@component`,
declarative `module(...)`, service pipelines, and an explicit `compile()` stage.

## Quick example

```python
from typing import Protocol

from dixp import Builder, EnterpriseMode, Lifetime, component, module


class Clock(Protocol):
    def now(self) -> int: ...


@component(as_=Clock, lifetime=Lifetime.SINGLETON)
class SystemClock:
    def now(self) -> int:
        return 42


app = module(SystemClock)

compiled = Builder().use(EnterpriseMode).module(app).compile()
container = compiled.build()

clock = container.resolve(Clock)
assert clock.now() == 42
```

## Design

- `Builder` is immutable. Every composition step returns a new builder.
- `@component` is the unified registration primitive for classes and factories.
- `module(...)` is declarative composition, not imperative mutation.
- `pipeline(...)` groups activation and decoration for a service.
- `compile()` freezes the graph into a `CompiledGraph` before runtime use.

## Feature guide

- `Builder`: the main entry point for composing an application graph without mutating shared state.
- `@component`: marks a class or factory as a service definition and carries lifetime metadata.
- `module(...)`: groups related registrations into a reusable declarative package.
- `pipeline(...)`: attaches activation hooks and decorators to a service in one place.
- `compile()`: turns composition input into a frozen graph you can validate, inspect, and build from.
- `StrictMode` / `EnterpriseMode`: predefined policy bundles for stricter composition rules.
- `qualified(...)` and `Inject.qualified(...)`: distinguish multiple services of the same base type.
- `Provider[T]`, `Factory[T]`, `Lazy[T]`: inject deferred access instead of eager object creation.
- multibindings: contribute many implementations under one service key and resolve them as collections.
- open generics: register generic service definitions once and resolve closed generic variants later.
- async resolution: support async factories, async invocation, and async disposal.
- diagnostics: inspect catalog, validate graphs early, and explain dependency resolution paths.

## How to choose

If you are starting fresh, use this default path:

1. Define services with `@component`.
2. Group related entries with `module(...)`.
3. Compose the application with `Builder`.
4. Add `pipeline(...)` only for cross-cutting behavior.
5. Use `compile(validate=True)` when you want an explicit pre-runtime verification step.

Use the more specialized features only when the problem actually needs them:

- Use qualifiers when two services share the same base type but represent different roles.
- Use `Provider[T]`, `Factory[T]`, or `Lazy[T]` when immediate construction would be wasteful or semantically wrong.
- Use multibindings when many implementations contribute to one extension point.
- Use open generics when the same generic infrastructure pattern repeats across many closed types.
- Use `StrictMode` or `EnterpriseMode` when team-level safety matters more than convenience.
- Use direct `decorate_where(...)` or `activate_where(...)` only when service-key-specific pipelines are too narrow.

## Problem -> Feature

| Problem | Feature |
| --- | --- |
| I need the default composition API | `Builder` |
| I want one decorator for classes and factories | `@component` |
| I want reusable application slices | `module(...)` |
| I need to initialize or wrap a service after construction | `pipeline(...).activate(...)` / `pipeline(...).decorate(...)` |
| I want to verify the graph before runtime | `compile(validate=True)` |
| I need different policies for local dev and production | `StrictMode` / `EnterpriseMode` |
| I have two `dict` services with different meanings | `qualified(...)` and `Inject.qualified(...)` |
| I need lazy or on-demand resolution | `Provider[T]`, `Factory[T]`, `Lazy[T]` |
| I need plugin-style extension points | multibindings |
| I need one generic registration for many concrete types | open generics |
| My factories or cleanup are async | `aresolve`, `ainvoke`, `aclose` |
| I need to inspect or debug the graph | `catalog()`, `validate()`, `explain()` |

## Builder

Use `Builder` as the default composition API. Because it is immutable, you can branch configuration safely for
different environments, tests, or product variants without hidden side effects.

```python
from dixp import Builder


base = Builder()
prod = base.singleton(Clock, SystemClock)
test = base.singleton(Clock, FakeClock)
```

## Components

`@component` is the high-level way to define services. It works for both classes and factory functions, so the
same concept covers constructor-based and factory-based registrations.

```python
from dixp import Lifetime, component


@component(as_=Clock, lifetime=Lifetime.SINGLETON)
class SystemClock:
    ...


@component(as_=Repository, lifetime=Lifetime.SCOPED)
def build_repository(clock: Clock) -> Repository:
    return Repository(clock)
```

## Modules

`module(...)` is a declarative grouping primitive. It is useful when you want a named, reusable composition unit
instead of scattering registrations across imperative setup code.

```python
from dixp import Builder, module


app = module(
    SystemClock,
    build_repository,
)

container = Builder().module(app).build()
```

## Pipelines

Pipelines are for post-construction behavior. Use them when a service needs activation logic, wrapping, tracing,
or other cross-cutting behavior that should stay outside the service constructor.

```python
from dixp import Builder


builder = Builder().module(app)
builder = builder.pipeline(Repository).activate(mark_ready)
builder = builder.pipeline(Repository).decorate(trace_repository)

container = builder.build()
```

You can also target predicates directly:

```python
builder = builder.decorate_where(
    lambda key, lifetime: key is Clock and lifetime is Lifetime.SINGLETON,
    wrap_clock,
)
```

## Compile phase

`compile()` creates a stable, inspectable graph before runtime. This is the right layer for validation, diagnostics,
tooling, and any workflow where you want to fail before serving requests or running business logic.

```python
compiled = Builder().module(app).compile(validate=True)
compiled.validate()
print(compiled.explain(Repository))

container = compiled.build()
```

## Bundles / profiles

Bundles package composition rules into reusable presets. They are useful when teams want consistent policies across
multiple applications or multiple build targets.

```python
from dixp import Builder, EnterpriseMode, StrictMode


strict_builder = Builder().use(StrictMode)
enterprise_builder = Builder().use(EnterpriseMode)
```

- `StrictMode` disables implicit autowiring by default.
- `EnterpriseMode` validates on `build()` / `compile(validate=True)` and rejects bare string keys.

## Typed qualifiers

Qualifiers solve the “same type, different meaning” problem. Use them when you have multiple `dict`, `Clock`,
`Repository`, or similar services that need distinct identities.

```python
from typing import Annotated

from dixp import Builder, Inject, Lifetime


class SettingsConsumer:
    def __init__(self, settings: Annotated[dict, Inject.qualified(dict, "main")]) -> None:
        self.settings = settings


container = (
    Builder()
    .qualify(dict, "main", instance={"env": "prod"}, lifetime=Lifetime.SINGLETON)
    .build()
)

consumer = container.resolve(SettingsConsumer)
assert consumer.settings["env"] == "prod"
```

## Provider, Factory, Lazy

These wrappers defer work. They are useful when a dependency should not be created immediately, should be created on
demand, or should be re-created on each call rather than injected as a ready-made object.

```python
from dixp import Builder, Factory, Lazy, Provider


class Service:
    def __init__(self, clock_provider: Provider[Clock], clock_factory: Factory[Clock], lazy_clock: Lazy[Clock]) -> None:
        self.clock_provider = clock_provider
        self.clock_factory = clock_factory
        self.lazy_clock = lazy_clock


container = Builder().component(SystemClock).build()
service = container.resolve(Service)
```

## Multibindings

Multibindings are for plugin-style extension points. Many implementations can contribute to the same service key and
the container resolves them as `list[T]` or via `resolve_all(T)`.

```python
from typing import Protocol

from dixp import Builder, contribute


class Plugin(Protocol):
    def name(self) -> str: ...


@component(as_=Plugin, multiple=True)
class AlphaPlugin:
    ...


@component(as_=Plugin, multiple=True)
class BetaPlugin:
    ...


container = (
    Builder()
    .add(contribute(Plugin, AlphaPlugin), contribute(Plugin, BetaPlugin))
    .build()
)

plugins = container.resolve(list[Plugin])
```

## Open generics

Open generics let you register a generic pattern once instead of manually binding every closed type. This is useful
for repositories, serializers, handlers, and other generic infrastructure components.

```python
from typing import Generic, Protocol, TypeVar

from dixp import Builder, Lifetime, open_generic

T = TypeVar("T")


class Serializer(Protocol[T]):
    def dump(self, value: T) -> T: ...


class IdentitySerializer(Generic[T]):
    def dump(self, value: T) -> T:
        return value


container = (
    Builder()
    .add(open_generic(Serializer, IdentitySerializer, lifetime=Lifetime.SINGLETON))
    .build()
)

serializer = container.resolve(Serializer[int])
assert serializer.dump(5) == 5
```

## Async example

The async API is for graphs that contain async factories or async cleanup. Use `aresolve`, `ainvoke`, and `aclose`
when service creation or disposal must await I/O.

```python
from dixp import Builder


class Resource:
    async def aclose(self) -> None:
        ...


async def create_resource() -> Resource:
    return Resource()


container = Builder().singleton(Resource, factory=create_resource).build()
resource = await container.aresolve(Resource)
await container.aclose()
```

## Architecture

The package is split by responsibility so composition, runtime resolution, diagnostics, and shared contracts stay
separate instead of collapsing into one large container module.

- `dixp.api`: public ergonomic API.
- `dixp.configuration`: declarative composition and graph compilation.
- `dixp.runtime`: container, scopes, caches, runtime registry.
- `dixp.inspection`: validation and explain diagnostics.
- `dixp.core`: contracts, metadata, graph model, shared errors.
