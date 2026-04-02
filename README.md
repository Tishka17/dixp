# dixp

`dixp` is a typed dependency injection toolkit for Python with a small public API:
`App`, `@service` or `@singleton`, `bundle(...)`, a few wiring helpers like `singleton(...)` / `value(...)` / `env(...)`, and a runtime container with `get()` / `call()`.

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
4. Use `singleton(...)`, `scoped(...)`, `value(...)`, `env(...)`, or `bind(...)` for explicit wiring.
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

### `env(...)` and `from_env(...)`

Use dataclass settings when configuration should stay typed and explicit.

```python
from dataclasses import dataclass

from dixp import App, from_env


@dataclass(frozen=True, slots=True)
class Settings:
    debug: bool
    port: int = 8080


settings = from_env(Settings, prefix="APP_", profile="prod")
app = App().env(Settings, prefix="APP_", profile="prod")
```

Profile lookups try the profile-specific variable first and then the shared fallback. With `prefix="APP_"` and `profile="prod"`, field `debug` resolves from `APP_PROD_DEBUG` and then `APP_DEBUG`.

Because `env(...)` is just a typed value binding, multiple profiles compose cleanly with `named(...)`:

```python
app = (
    App()
    .env(Settings, prefix="APP_", profile="dev", name="dev")
    .env(Settings, prefix="APP_", profile="prod", name="prod")
)
```

### `bundle(...)`

Bundles are reusable slices of composition.

```python
core = bundle(SystemClock, make_repository)
app = App().include(core)
```

When you want bundle boundaries to become explicit architecture rules, add a contract:

```python
payments = (
    bundle(StripeClient, PaymentService, name="payments")
    .exports(PaymentService)
    .requires(Clock, PaymentSettings)
    .private(StripeClient)
    .layer("infra")
    .forbid_outgoing_to("web")
    .forbid_outgoing_to_layers("presentation")
    .allow_incoming_from_tags("http")
    .allow_incoming_from("api")
    .tagged("infra", "payments")
)
```

Contract bundles stay fully reusable, but `doctor()` and `validate()` will now catch:

- undeclared external dependencies
- access to non-exported services
- leaks of private services across bundle boundaries
- bundle-to-bundle policy violations declared with `forbid_outgoing_to(...)`
- restricted consumers for bundles that declare `allow_incoming_from(...)`
- layer-based policies declared with `layer(...)`, `forbid_outgoing_to_layers(...)`, and `allow_incoming_from_layers(...)`
- tag-based policies declared with `forbid_outgoing_to_tags(...)` and `allow_incoming_from_tags(...)`
- bundle dependency cycles between modules

`doctor()` also prints a bundle graph section, so architectural drift shows up as changed edges between bundles instead of opaque resolution failures.

If you want to publish the graph in CI, the report can export it directly:

```python
report = app.doctor()

mermaid = report.bundle_graph_mermaid()
payload = report.bundle_graph_json()
```

You can also compare the current graph against a saved baseline to detect architectural drift in CI:

```python
baseline = Path("build/bundle-graph.json").read_text(encoding="utf-8")
diff = report.diff_bundle_graph(baseline)

if diff.drift:
    raise SystemExit(diff.format())
```

For a zero-setup CI runner, point `python -m dixp.doctor` at an importable `App`, `Blueprint`, or zero-arg factory:

```bash
python -m dixp.doctor your_project.bootstrap:app
python -m dixp.doctor your_project.bootstrap:build_app --format json --json-out build/bundle-graph.json
python -m dixp.doctor your_project.bootstrap:blueprint --format mermaid --mermaid-out build/bundle-graph.mmd
python -m dixp.doctor your_project.bootstrap:app --baseline-json ci/bundle-graph-baseline.json --fail-on-drift
```

The command exits with `0` when the report is healthy and `1` when doctor finds graph or bundle violations.

If the package is installed, the same runner is also available as:

```bash
dixp-doctor your_project.bootstrap:app
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
- `warmup()` / `awarmup()` for fail-fast startup of critical services
- `child()` for scoped resolution
- `activate(...)` + `current_resolver()` for ambient request/job context
- `override(...)` for test and request-local replacements
- `explain()` / `catalog()` / `validate()` / `doctor()` for diagnostics

```python
container = app.start()

clock = container[Clock]
plugins = container.all(Plugin)
result = container.call(handle_request, user_id="42")
```

For request-local values that should follow async execution through `contextvars`, activate a scope:

```python
from dixp import current_resolver


with container.activate((RequestId, RequestId("req-42"))) as scope:
    consumer = current_resolver().get(RequestIdConsumer)
```

For fail-fast boot of critical services, warm them up explicitly:

```python
container = app.start(warmup=(Clock, Repository))

# for async singletons/resources
await container.awarmup(AsyncDisposable)
```

`catalog()` and `explain()` also carry source attribution, so you can see which implementation or factory introduced a service:

```python
blueprint = App().include(SystemClock, make_repository).freeze()

info = next(item for item in blueprint.catalog() if item.key is Repository)
print(info.source)
print(info.source_location)
print(blueprint.explain(Repository))
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
