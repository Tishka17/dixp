# dixp

`dixp` is a typed dependency injection toolkit for Python with a small public API:
`App`, `@service` or `@singleton`, `bundle(...)`, a few wiring helpers like `singleton(...)` / `value(...)`, and a runtime container with `get()` / `call()`.

The goal is to make composition feel like application design, not container plumbing.

## Quick Start

```python
from typing import Protocol

from dixp import App, bundle, singleton


class Clock(Protocol):
    def now(self) -> int: ...


@singleton(provides=Clock)
class SystemClock:
    def now(self) -> int:
        return 42


app = App().include(bundle(SystemClock))
container = app.start()

clock = container[Clock]
assert clock.now() == 42
```

## The Main Flow

`dixp` is designed around one happy path:

1. Mark reusable services with `@service` or a shortcut like `@singleton`.
2. Group related entries with `bundle(...)`.
3. Compose the app with `App()`.
4. Use `singleton(...)`, `scoped(...)`, `value(...)`, or `bind(...)` for explicit wiring.
5. Use `on(...)` for lifecycle hooks and wrappers.
6. Start the container with `start()` or freeze it first with `freeze()`.

## Public API

### `App`

`App` is immutable. Every composition step returns a new app.

```python
from dixp import App


base = App()
prod = base.value(Config, {"env": "prod"})
test = base.value(Config, {"env": "test"})
```

### `@service`, `@singleton`, `@scoped`

`@service` is the generic decorator. If you already know the lifetime, the shortcuts read better.

```python
from dixp import scoped, singleton


@singleton(provides=Clock)
class SystemClock:
    ...


@scoped(provides=Repository)
def make_repository(clock: Clock) -> Repository:
    return Repository(clock)
```

### Wiring Helpers

Use the top-level helpers for the most common cases.

```python
app = (
    App()
    .singleton(Clock, SystemClock)
    .value(Settings, Settings(debug=True))
    .many(Plugin, AlphaPlugin, BetaPlugin)
)
```

Use `bind(...)` when you want a slightly more fluent chain:

```python
app = App().bind(Clock).singleton(SystemClock)
```

### `bundle(...)`

Bundles are reusable slices of composition.

```python
core = bundle(SystemClock, make_repository)
app = App().include(core)
```

### `named(...)` and `Inject.named(...)`

Use named bindings when two services share the same base type.

```python
from typing import Annotated

from dixp import App, Inject, Lifetime


class SettingsConsumer:
    def __init__(self, settings: Annotated[dict, Inject.named(dict, "main")]) -> None:
        self.settings = settings


app = App().value(dict, {"env": "prod"}, name="main")
container = app.start()
```

### Hooks

Use `on(...)` when you want post-construction behavior without bloating constructors.

```python
app = (
    App()
    .include(SystemClock, make_repository)
    .on(Repository).init(mark_ready)
    .on(Repository).wrap(trace_repository)
)
```

Predicate hooks are available through `when(...)`:

```python
app = app.when(lambda key, lifetime: lifetime is Lifetime.SINGLETON).wrap(trace_singletons)
```

### Freeze / Start

`freeze()` gives you an inspectable blueprint. `start()` builds a runtime container.

```python
blueprint = App().include(SystemClock).freeze(validate=True)
print(blueprint.explain(Clock))

container = blueprint.start()
```

## Runtime API

The runtime container exposes short, task-shaped methods:

- `get()` / `aget()`
- `all()` / `aall()`
- `maybe()` / `has()`
- `call()` / `acall()`
- `child()` for scoped resolution
- `override(...)` for test and request-local replacements
- `explain()` / `catalog()` / `validate()` / `doctor()` for diagnostics

```python
container = app.start()

clock = container[Clock]
plugins = container.all(Plugin)
result = container.call(handle_request, user_id="42")
```

## Doctor

Use `doctor()` when you want a one-shot health check with a readable report.

```python
report = App().include(SystemClock).doctor()

print(report.ok)
print(report)
```

Because `DoctorReport` is truthy on success, this also works:

```python
if App().include(SystemClock).doctor():
    print("ready")
```

## Testing

Use `app.test()` when you want fast overrides without rewriting your whole graph.

```python
from dixp import App


test_app = (
    App()
    .include(SystemClock, make_repository)
    .test()
    .with_stub(Clock, now=lambda: 7)
)

container = test_app.start()
assert container[Clock].now() == 7
```

If you need a quick fake object, `stub(...)` builds one without a custom class:

```python
from dixp import stub


fake_clock = stub(name="FakeClock", now=lambda: 123)
```

## Modes

Use `StrictMode` when you want explicit registration only.
Use `SafeMode` when you want stronger validation and typed keys.

```python
from dixp import App, SafeMode


app = App().use(SafeMode)
```

## Advanced API

The root package is intentionally small.

If you need lower-level composition primitives, open generics, or policy internals,
they still live in the package internals, but they are not the recommended entry point.
