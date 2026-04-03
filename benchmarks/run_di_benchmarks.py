from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import statistics
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Protocol, runtime_checkable

ROOT = Path(__file__).resolve().parents[1]

try:
    import wireup as _wireup
except ImportError:
    _wireup = None

try:
    from dishka.integrations.base import FromDishka as _dishka_from_dishka
except ImportError:
    _dishka_from_dishka = None


class _AnnotationFallback:
    def __class_getitem__(cls, item: Any) -> Any:
        return item


WireupInjected = _wireup.Injected if _wireup is not None else _AnnotationFallback
DishkaInjected = _dishka_from_dishka if _dishka_from_dishka is not None else _AnnotationFallback


@runtime_checkable
class Clock(Protocol):
    def now(self) -> int: ...


class SystemClock:
    def now(self) -> int:
        return 42


@dataclass(frozen=True, slots=True)
class Settings:
    debug: bool
    region: str


class Repository:
    def __init__(self, clock: Clock, settings: Settings) -> None:
        self.clock = clock
        self.settings = settings


class Service:
    def __init__(self, repository: Repository) -> None:
        self.repository = repository


@runtime_checkable
class Plugin(Protocol):
    def name(self) -> str: ...


class AlphaPlugin:
    def name(self) -> str:
        return "alpha"


class BetaPlugin:
    def name(self) -> str:
        return "beta"


class GammaPlugin:
    def name(self) -> str:
        return "gamma"


def benchmark_handler(service: Service, repository: Repository, plugins: list[Plugin]) -> int:
    return service.repository.clock.now() + repository.clock.now() + len(plugins)


def wireup_benchmark_handler(
    service: WireupInjected[Service],
    repository: WireupInjected[Repository],
    plugins: WireupInjected[list[Plugin]],
) -> int:
    return benchmark_handler(service, repository, plugins)


def dishka_benchmark_handler(
    service: DishkaInjected[Service],
    repository: DishkaInjected[Repository],
    plugins: DishkaInjected[list[Plugin]],
) -> int:
    return benchmark_handler(service, repository, plugins)


@dataclass(frozen=True, slots=True)
class MetricSummary:
    name: str
    unit: str
    iterations: int
    repeat: int
    best: float
    median: float
    mean: float
    stdev: float


@dataclass(frozen=True, slots=True)
class LibraryResult:
    library: str
    package: str
    supported: bool
    available: bool
    metrics: tuple[MetricSummary, ...]
    skip_reason: str | None = None


class BenchmarkAdapter(Protocol):
    library: str
    package: str

    def is_available(self) -> bool: ...
    def run(self, *, repeat: int, iterations: int) -> LibraryResult: ...


def benchmark_metric(
    name: str,
    unit: str,
    iterations: int,
    repeat: int,
    setup: Callable[[], Any],
    operation: Callable[[Any], Any],
    cleanup: Callable[[Any, Any], None] | None = None,
) -> MetricSummary:
    samples: list[float] = []
    for _ in range(repeat):
        state = setup()
        started = time.perf_counter()
        last_value: Any = None
        for _ in range(iterations):
            last_value = operation(state)
        elapsed = time.perf_counter() - started
        if cleanup is not None:
            cleanup(state, last_value)
        samples.append(elapsed / iterations)

    return MetricSummary(
        name=name,
        unit=unit,
        iterations=iterations,
        repeat=repeat,
        best=min(samples),
        median=statistics.median(samples),
        mean=statistics.fmean(samples),
        stdev=statistics.stdev(samples) if len(samples) > 1 else 0.0,
    )


def format_seconds(value: float) -> str:
    if value < 1e-6:
        return f"{value * 1e9:.1f} ns"
    if value < 1e-3:
        return f"{value * 1e6:.1f} us"
    if value < 1:
        return f"{value * 1e3:.3f} ms"
    return f"{value:.3f} s"


class DixpAdapter:
    library = "dixp"
    package = "dixp"

    def is_available(self) -> bool:
        return True

    def _build_app(self):
        from dixp import App

        return (
            App()
            .singleton(Clock, SystemClock)
            .value(Settings, Settings(debug=True, region="eu-west"))
            .scoped(Repository, Repository)
            .transient(Service, Service)
            .many(Plugin, AlphaPlugin, BetaPlugin, GammaPlugin)
        )

    def _container(self):
        return self._build_app().start()

    @staticmethod
    def _start_ready(app: Any):
        container = app.start(validate=False)
        container.get(Clock)
        container.all(Plugin)
        with container.child() as scope:
            scope.get(Repository)
            scope.get(Service)
        return container

    @staticmethod
    def _request_cycle(container: Any) -> int:
        with container.child() as scope:
            return benchmark_handler(scope.get(Service), scope.get(Repository), scope.all(Plugin))

    def run(self, *, repeat: int, iterations: int) -> LibraryResult:
        metrics = [
            benchmark_metric(
                "freeze",
                "seconds/op",
                iterations=iterations,
                repeat=repeat,
                setup=self._build_app,
                operation=lambda app: app.freeze(validate=False),
            ),
            benchmark_metric(
                "start",
                "seconds/op",
                iterations=iterations,
                repeat=repeat,
                setup=self._build_app,
                operation=lambda app: app.start(validate=False),
                cleanup=lambda _app, container: container.close(),
            ),
            benchmark_metric(
                "start_ready",
                "seconds/op",
                iterations=iterations,
                repeat=repeat,
                setup=self._build_app,
                operation=self._start_ready,
                cleanup=lambda _app, container: container.close(),
            ),
            benchmark_metric(
                "validate",
                "seconds/op",
                iterations=iterations,
                repeat=repeat,
                setup=lambda: self._build_app().freeze(validate=False),
                operation=lambda blueprint: blueprint.validate(),
            ),
            benchmark_metric(
                "singleton_get",
                "seconds/op",
                iterations=iterations * 200,
                repeat=repeat,
                setup=self._container,
                operation=lambda container: container.get(Clock),
                cleanup=lambda container, _value: container.close(),
            ),
            benchmark_metric(
                "scoped_get",
                "seconds/op",
                iterations=iterations * 100,
                repeat=repeat,
                setup=self._container,
                operation=self._scoped_get,
                cleanup=lambda container, _value: container.close(),
            ),
            benchmark_metric(
                "collection_all",
                "seconds/op",
                iterations=iterations * 100,
                repeat=repeat,
                setup=self._container,
                operation=lambda container: container.all(Plugin),
                cleanup=lambda container, _value: container.close(),
            ),
            benchmark_metric(
                "call",
                "seconds/op",
                iterations=iterations * 100,
                repeat=repeat,
                setup=self._container,
                operation=lambda container: container.call(benchmark_handler),
                cleanup=lambda container, _value: container.close(),
            ),
            benchmark_metric(
                "request_cycle",
                "seconds/op",
                iterations=iterations * 100,
                repeat=repeat,
                setup=self._container,
                operation=self._request_cycle,
                cleanup=lambda container, _value: container.close(),
            ),
        ]
        return LibraryResult(
            library=self.library,
            package=self.package,
            supported=True,
            available=True,
            metrics=tuple(metrics),
        )

    @staticmethod
    def _scoped_get(container: Any) -> None:
        with container.child() as scope:
            scope.get(Repository)

def _package_available(package: str) -> bool:
    return importlib.util.find_spec(package) is not None


class ExternalAdapter:
    def __init__(self, library: str, package: str) -> None:
        self.library = library
        self.package = package

    def is_available(self) -> bool:
        return _package_available(self.package)

    def run(self, *, repeat: int, iterations: int) -> LibraryResult:
        if not self.is_available():
            return LibraryResult(
                library=self.library,
                package=self.package,
                supported=True,
                available=False,
                metrics=(),
                skip_reason=f"Package {self.package!r} is not installed in the current environment.",
            )
        try:
            return self._run(repeat=repeat, iterations=iterations)
        except Exception as exc:
            return LibraryResult(
                library=self.library,
                package=self.package,
                supported=True,
                available=True,
                metrics=(),
                skip_reason=f"Adapter failed: {exc.__class__.__name__}: {exc}",
            )

    def _run(self, *, repeat: int, iterations: int) -> LibraryResult:
        raise NotImplementedError


class DependencyInjectorAdapter(ExternalAdapter):
    def __init__(self) -> None:
        super().__init__("dependency-injector", "dependency_injector")

    def _build_container_class(self) -> type[Any]:
        from dependency_injector import containers, providers

        class BenchContainer(containers.DeclarativeContainer):
            settings = providers.Object(Settings(debug=True, region="eu-west"))
            clock = providers.Singleton(SystemClock)
            repository = providers.Factory(Repository, clock=clock, settings=settings)
            service = providers.Factory(Service, repository=repository)
            alpha_plugin = providers.Factory(AlphaPlugin)
            beta_plugin = providers.Factory(BetaPlugin)
            gamma_plugin = providers.Factory(GammaPlugin)
            plugins = providers.List(alpha_plugin, beta_plugin, gamma_plugin)
            handler = providers.Callable(
                benchmark_handler,
                service=service,
                repository=repository,
                plugins=plugins,
            )

        return BenchContainer

    def _container(self) -> Any:
        return self._build_container_class()()

    def _validate(self, container: Any) -> None:
        container.check_dependencies()
        container.clock()
        container.service()
        container.plugins()

    def _start_ready(self, container_cls: type[Any]) -> Any:
        container = container_cls()
        container.clock()
        container.plugins()
        container.repository()
        container.service()
        return container

    def _request_cycle(self, container: Any) -> int:
        return benchmark_handler(container.service(), container.repository(), container.plugins())

    def _close(self, container: Any) -> None:
        container.shutdown_resources()

    def _run(self, *, repeat: int, iterations: int) -> LibraryResult:
        metrics = [
            benchmark_metric(
                "freeze",
                "seconds/op",
                iterations=iterations,
                repeat=repeat,
                setup=lambda: None,
                operation=lambda _state: self._build_container_class(),
            ),
            benchmark_metric(
                "start",
                "seconds/op",
                iterations=iterations,
                repeat=repeat,
                setup=self._build_container_class,
                operation=lambda container_cls: container_cls(),
                cleanup=lambda _state, container: self._close(container),
            ),
            benchmark_metric(
                "start_ready",
                "seconds/op",
                iterations=iterations,
                repeat=repeat,
                setup=self._build_container_class,
                operation=self._start_ready,
                cleanup=lambda _state, container: self._close(container),
            ),
            benchmark_metric(
                "validate",
                "seconds/op",
                iterations=iterations,
                repeat=repeat,
                setup=self._container,
                operation=self._validate,
                cleanup=lambda container, _value: self._close(container),
            ),
            benchmark_metric(
                "singleton_get",
                "seconds/op",
                iterations=iterations * 200,
                repeat=repeat,
                setup=self._container,
                operation=lambda container: container.clock(),
                cleanup=lambda container, _value: self._close(container),
            ),
            benchmark_metric(
                "scoped_get",
                "seconds/op",
                iterations=iterations * 100,
                repeat=repeat,
                setup=self._container,
                operation=lambda container: container.repository(),
                cleanup=lambda container, _value: self._close(container),
            ),
            benchmark_metric(
                "collection_all",
                "seconds/op",
                iterations=iterations * 100,
                repeat=repeat,
                setup=self._container,
                operation=lambda container: container.plugins(),
                cleanup=lambda container, _value: self._close(container),
            ),
            benchmark_metric(
                "call",
                "seconds/op",
                iterations=iterations * 100,
                repeat=repeat,
                setup=self._container,
                operation=lambda container: container.handler(),
                cleanup=lambda container, _value: self._close(container),
            ),
            benchmark_metric(
                "request_cycle",
                "seconds/op",
                iterations=iterations * 100,
                repeat=repeat,
                setup=self._container,
                operation=self._request_cycle,
                cleanup=lambda container, _value: self._close(container),
            ),
        ]
        return LibraryResult(
            library=self.library,
            package=self.package,
            supported=True,
            available=True,
            metrics=tuple(metrics),
        )


class InjectorAdapter(ExternalAdapter):
    def __init__(self) -> None:
        super().__init__("injector", "injector")
        self._cached_handler: Callable[..., int] | None = None

    def _build_module(self) -> Any:
        from injector import Binder, Module, provider, singleton, threadlocal

        class BenchModule(Module):
            def configure(self, binder: Binder) -> None:
                binder.multibind(list[Plugin], to=[AlphaPlugin(), BetaPlugin(), GammaPlugin()])

            @provider
            @singleton
            def provide_settings(self) -> Settings:
                return Settings(debug=True, region="eu-west")

            @provider
            @singleton
            def provide_clock(self) -> Clock:
                return SystemClock()

            @provider
            @threadlocal
            def provide_repository(self, clock: Clock, settings: Settings) -> Repository:
                return Repository(clock, settings)

            @provider
            def provide_service(self, repository: Repository) -> Service:
                return Service(repository)

        return BenchModule()

    def _injector(self, module_state: Any | None = None) -> Any:
        from injector import Injector

        module = module_state or self._build_module()
        return Injector([module], auto_bind=False)

    def _validate(self, injector: Any) -> None:
        injector.get(Clock)
        injector.get(list[Plugin])
        injector.get(Repository)
        injector.get(Service)

    def _start_ready(self, module: Any) -> Any:
        injector = self._injector(module)
        injector.get(Clock)
        injector.get(list[Plugin])
        injector.get(Repository)
        injector.get(Service)
        return injector

    def _scoped_get(self, injector: Any) -> Any:
        return injector.get(Repository)

    def _injected_handler(self) -> Callable[..., int]:
        if self._cached_handler is not None:
            return self._cached_handler
        inject = importlib.import_module("injector").inject

        @inject
        def handler(service: Service, repository: Repository, plugins: list[Plugin]) -> int:
            return benchmark_handler(service, repository, plugins)

        self._cached_handler = handler
        return handler

    def _call(self, injector: Any) -> int:
        return injector.call_with_injection(self._injected_handler())

    def _request_cycle(self, injector: Any) -> int:
        return benchmark_handler(injector.get(Service), injector.get(Repository), injector.get(list[Plugin]))

    def _run(self, *, repeat: int, iterations: int) -> LibraryResult:
        metrics = [
            benchmark_metric(
                "freeze",
                "seconds/op",
                iterations=iterations,
                repeat=repeat,
                setup=lambda: None,
                operation=lambda _state: self._build_module(),
            ),
            benchmark_metric(
                "start",
                "seconds/op",
                iterations=iterations,
                repeat=repeat,
                setup=self._build_module,
                operation=self._injector,
            ),
            benchmark_metric(
                "start_ready",
                "seconds/op",
                iterations=iterations,
                repeat=repeat,
                setup=self._build_module,
                operation=self._start_ready,
            ),
            benchmark_metric(
                "validate",
                "seconds/op",
                iterations=iterations,
                repeat=repeat,
                setup=self._injector,
                operation=self._validate,
            ),
            benchmark_metric(
                "singleton_get",
                "seconds/op",
                iterations=iterations * 200,
                repeat=repeat,
                setup=self._injector,
                operation=lambda injector: injector.get(Clock),
            ),
            benchmark_metric(
                "scoped_get",
                "seconds/op",
                iterations=iterations * 100,
                repeat=repeat,
                setup=self._injector,
                operation=self._scoped_get,
            ),
            benchmark_metric(
                "collection_all",
                "seconds/op",
                iterations=iterations * 100,
                repeat=repeat,
                setup=self._injector,
                operation=lambda injector: injector.get(list[Plugin]),
            ),
            benchmark_metric(
                "call",
                "seconds/op",
                iterations=iterations * 100,
                repeat=repeat,
                setup=self._injector,
                operation=self._call,
            ),
            benchmark_metric(
                "request_cycle",
                "seconds/op",
                iterations=iterations * 100,
                repeat=repeat,
                setup=self._injector,
                operation=self._request_cycle,
            ),
        ]
        return LibraryResult(
            library=self.library,
            package=self.package,
            supported=True,
            available=True,
            metrics=tuple(metrics),
        )


class LagomAdapter(ExternalAdapter):
    def __init__(self) -> None:
        super().__init__("lagom", "lagom")

    def _definitions(self) -> dict[Any, Any]:
        return {
            Clock: SystemClock(),
            Settings: Settings(debug=True, region="eu-west"),
            Repository: lambda container: Repository(container[Clock], container[Settings]),
            Service: lambda container: Service(container[Repository]),
            list[Plugin]: [AlphaPlugin(), BetaPlugin(), GammaPlugin()],
        }

    def _container(self, definitions: dict[Any, Any] | None = None) -> Any:
        lagom = importlib.import_module("lagom")
        container = lagom.Container()
        for key, definition in (definitions or self._definitions()).items():
            container[key] = definition
        return container

    def _validate(self, container: Any) -> None:
        container[Clock]
        container[Repository]
        container[Service]
        container[list[Plugin]]

    def _start_ready(self, definitions: dict[Any, Any]) -> Any:
        container = self._container(definitions)
        container[Clock]
        container[list[Plugin]]
        container[Repository]
        container[Service]
        return container

    def _call_state(self) -> tuple[Any, Callable[[], int]]:
        container = self._container()

        def handler(service: Service, repository: Repository, plugins: list[Plugin]) -> int:
            return benchmark_handler(service, repository, plugins)

        return container, container.magic_partial(handler, shared=[Repository])

    def _request_cycle(self, container: Any) -> int:
        return benchmark_handler(container[Service], container[Repository], container[list[Plugin]])

    def _run(self, *, repeat: int, iterations: int) -> LibraryResult:
        metrics = [
            benchmark_metric(
                "freeze",
                "seconds/op",
                iterations=iterations,
                repeat=repeat,
                setup=lambda: None,
                operation=lambda _state: self._definitions(),
            ),
            benchmark_metric(
                "start",
                "seconds/op",
                iterations=iterations,
                repeat=repeat,
                setup=self._definitions,
                operation=self._container,
            ),
            benchmark_metric(
                "start_ready",
                "seconds/op",
                iterations=iterations,
                repeat=repeat,
                setup=self._definitions,
                operation=self._start_ready,
            ),
            benchmark_metric(
                "validate",
                "seconds/op",
                iterations=iterations,
                repeat=repeat,
                setup=self._container,
                operation=self._validate,
            ),
            benchmark_metric(
                "singleton_get",
                "seconds/op",
                iterations=iterations * 200,
                repeat=repeat,
                setup=self._container,
                operation=lambda container: container[Clock],
            ),
            benchmark_metric(
                "scoped_get",
                "seconds/op",
                iterations=iterations * 100,
                repeat=repeat,
                setup=self._container,
                operation=lambda container: container[Repository],
            ),
            benchmark_metric(
                "collection_all",
                "seconds/op",
                iterations=iterations * 100,
                repeat=repeat,
                setup=self._container,
                operation=lambda container: container[list[Plugin]],
            ),
            benchmark_metric(
                "call",
                "seconds/op",
                iterations=iterations * 100,
                repeat=repeat,
                setup=self._call_state,
                operation=lambda state: state[1](),
            ),
            benchmark_metric(
                "request_cycle",
                "seconds/op",
                iterations=iterations * 100,
                repeat=repeat,
                setup=self._container,
                operation=self._request_cycle,
            ),
        ]
        return LibraryResult(
            library=self.library,
            package=self.package,
            supported=True,
            available=True,
            metrics=tuple(metrics),
        )


class PunqAdapter(ExternalAdapter):
    def __init__(self) -> None:
        super().__init__("punq", "punq")

    def _registrations(self) -> tuple[tuple[Any, tuple[Any, ...], dict[str, Any]], ...]:
        return (
            (Settings, (), {"instance": Settings(debug=True, region="eu-west")}),
            (Clock, (), {"instance": SystemClock()}),
            (Repository, (), {}),
            (Service, (), {}),
            (Plugin, (AlphaPlugin,), {}),
            (Plugin, (BetaPlugin,), {}),
            (Plugin, (GammaPlugin,), {}),
        )

    def _container(self, registrations: tuple[tuple[Any, tuple[Any, ...], dict[str, Any]], ...] | None = None) -> Any:
        punq = importlib.import_module("punq")
        container = punq.Container()
        for service, args, kwargs in registrations or self._registrations():
            container.register(service, *args, **kwargs)
        return container

    def _validate(self, container: Any) -> None:
        container.resolve(Clock)
        container.resolve(Repository)
        container.resolve(Service)
        container.resolve_all(Plugin)

    def _start_ready(self, registrations: tuple[tuple[Any, tuple[Any, ...], dict[str, Any]], ...]) -> Any:
        container = self._container(registrations)
        container.resolve(Clock)
        container.resolve(list[Plugin])
        container.resolve(Repository)
        container.resolve(Service)
        return container

    def _call(self, container: Any) -> int:
        return benchmark_handler(
            container.resolve(Service),
            container.resolve(Repository),
            list(container.resolve_all(Plugin)),
        )

    def _request_cycle(self, container: Any) -> int:
        return benchmark_handler(
            container.resolve(Service),
            container.resolve(Repository),
            container.resolve(list[Plugin]),
        )

    def _run(self, *, repeat: int, iterations: int) -> LibraryResult:
        metrics = [
            benchmark_metric(
                "freeze",
                "seconds/op",
                iterations=iterations,
                repeat=repeat,
                setup=lambda: None,
                operation=lambda _state: self._registrations(),
            ),
            benchmark_metric(
                "start",
                "seconds/op",
                iterations=iterations,
                repeat=repeat,
                setup=self._registrations,
                operation=self._container,
            ),
            benchmark_metric(
                "start_ready",
                "seconds/op",
                iterations=iterations,
                repeat=repeat,
                setup=self._registrations,
                operation=self._start_ready,
            ),
            benchmark_metric(
                "validate",
                "seconds/op",
                iterations=iterations,
                repeat=repeat,
                setup=self._container,
                operation=self._validate,
            ),
            benchmark_metric(
                "singleton_get",
                "seconds/op",
                iterations=iterations * 200,
                repeat=repeat,
                setup=self._container,
                operation=lambda container: container.resolve(Clock),
            ),
            benchmark_metric(
                "scoped_get",
                "seconds/op",
                iterations=iterations * 100,
                repeat=repeat,
                setup=self._container,
                operation=lambda container: container.resolve(Repository),
            ),
            benchmark_metric(
                "collection_all",
                "seconds/op",
                iterations=iterations * 100,
                repeat=repeat,
                setup=self._container,
                operation=lambda container: container.resolve_all(Plugin),
            ),
            benchmark_metric(
                "call",
                "seconds/op",
                iterations=iterations * 100,
                repeat=repeat,
                setup=self._container,
                operation=self._call,
            ),
            benchmark_metric(
                "request_cycle",
                "seconds/op",
                iterations=iterations * 100,
                repeat=repeat,
                setup=self._container,
                operation=self._request_cycle,
            ),
        ]
        return LibraryResult(
            library=self.library,
            package=self.package,
            supported=True,
            available=True,
            metrics=tuple(metrics),
        )


class DishkaAdapter(ExternalAdapter):
    def __init__(self) -> None:
        super().__init__("dishka", "dishka")

    def _provider(self) -> Any:
        dishka = importlib.import_module("dishka")
        collect = dishka.collect
        from_context = dishka.from_context
        Provider = dishka.Provider
        Scope = dishka.Scope
        provide = dishka.provide

        class BenchProvider(Provider):
            scope = Scope.APP
            clock = provide(source=SystemClock, provides=Clock)
            settings = from_context(provides=Settings)
            repository = provide(Repository, scope=Scope.REQUEST)
            service = provide(Service, scope=Scope.REQUEST)
            alpha = provide(AlphaPlugin, provides=Plugin)
            beta = provide(BetaPlugin, provides=Plugin)
            gamma = provide(GammaPlugin, provides=Plugin)
            plugins = collect(Plugin)

        return BenchProvider()

    def _container(self) -> Any:
        dishka = importlib.import_module("dishka")
        return dishka.make_container(
            self._provider(),
            context={Settings: Settings(debug=True, region="eu-west")},
        )

    def _validate(self, container: Any) -> None:
        container.get(Clock)
        container.get(list[Plugin])
        with container() as request_container:
            request_container.get(Repository)
            request_container.get(Service)

    def _start_ready(self, provider: Any) -> Any:
        container = importlib.import_module("dishka").make_container(
            provider,
            context={Settings: Settings(debug=True, region="eu-west")},
        )
        container.get(Clock)
        container.get(list[Plugin])
        with container() as request_container:
            request_container.get(Repository)
            request_container.get(Service)
        return container

    def _scoped_get(self, container: Any) -> Any:
        with container() as request_container:
            return request_container.get(Repository)

    def _close(self, container: Any) -> None:
        container.close()

    def _call_state(self) -> tuple[Any, Callable[[], int]]:
        dishka = importlib.import_module("dishka")
        base = importlib.import_module("dishka.integrations.base")
        container = self._container()
        wrap_injection = base.wrap_injection

        wrapped = wrap_injection(
            func=dishka_benchmark_handler,
            container_getter=lambda _args, _kwargs: container,
            is_async=False,
            manage_scope=True,
            scope=dishka.Scope.REQUEST,
        )
        return container, wrapped

    def _request_cycle(self, container: Any) -> int:
        plugins = container.get(list[Plugin])
        with container() as request_container:
            return benchmark_handler(request_container.get(Service), request_container.get(Repository), plugins)

    def _run(self, *, repeat: int, iterations: int) -> LibraryResult:
        metrics = [
            benchmark_metric(
                "freeze",
                "seconds/op",
                iterations=iterations,
                repeat=repeat,
                setup=lambda: None,
                operation=lambda _state: self._provider(),
            ),
            benchmark_metric(
                "start",
                "seconds/op",
                iterations=iterations,
                repeat=repeat,
                setup=self._provider,
                operation=lambda provider: importlib.import_module("dishka").make_container(
                    provider,
                    context={Settings: Settings(debug=True, region="eu-west")},
                ),
                cleanup=lambda _provider, container: self._close(container),
            ),
            benchmark_metric(
                "start_ready",
                "seconds/op",
                iterations=iterations,
                repeat=repeat,
                setup=self._provider,
                operation=self._start_ready,
                cleanup=lambda _provider, container: self._close(container),
            ),
            benchmark_metric(
                "validate",
                "seconds/op",
                iterations=iterations,
                repeat=repeat,
                setup=self._container,
                operation=self._validate,
                cleanup=lambda container, _value: self._close(container),
            ),
            benchmark_metric(
                "singleton_get",
                "seconds/op",
                iterations=iterations * 200,
                repeat=repeat,
                setup=self._container,
                operation=lambda container: container.get(Clock),
                cleanup=lambda container, _value: self._close(container),
            ),
            benchmark_metric(
                "scoped_get",
                "seconds/op",
                iterations=iterations * 100,
                repeat=repeat,
                setup=self._container,
                operation=self._scoped_get,
                cleanup=lambda container, _value: self._close(container),
            ),
            benchmark_metric(
                "collection_all",
                "seconds/op",
                iterations=iterations * 100,
                repeat=repeat,
                setup=self._container,
                operation=lambda container: container.get(list[Plugin]),
                cleanup=lambda container, _value: self._close(container),
            ),
            benchmark_metric(
                "call",
                "seconds/op",
                iterations=iterations * 100,
                repeat=repeat,
                setup=self._call_state,
                operation=lambda state: state[1](),
                cleanup=lambda state, _value: self._close(state[0]),
            ),
            benchmark_metric(
                "request_cycle",
                "seconds/op",
                iterations=iterations * 100,
                repeat=repeat,
                setup=self._container,
                operation=self._request_cycle,
                cleanup=lambda container, _value: self._close(container),
            ),
        ]
        return LibraryResult(
            library=self.library,
            package=self.package,
            supported=True,
            available=True,
            metrics=tuple(metrics),
        )


class WireupAdapter(ExternalAdapter):
    def __init__(self) -> None:
        super().__init__("wireup", "wireup")

    def _entries(self) -> list[Any]:
        wireup = importlib.import_module("wireup")
        decorate = wireup.injectable

        class WireClock(SystemClock):
            pass

        class WireRepository(Repository):
            pass

        class WireService(Service):
            pass

        def build_settings() -> Settings:
            return Settings(debug=True, region="eu-west")

        def build_plugins(alpha: AlphaPlugin, beta: BetaPlugin, gamma: GammaPlugin) -> list[Plugin]:
            return [alpha, beta, gamma]

        return [
            decorate(WireClock, as_type=Clock, lifetime="singleton"),
            decorate(build_settings, as_type=Settings, lifetime="singleton"),
            decorate(WireRepository, as_type=Repository, lifetime="scoped"),
            decorate(WireService, as_type=Service, lifetime="transient"),
            decorate(AlphaPlugin, lifetime="singleton"),
            decorate(BetaPlugin, lifetime="singleton"),
            decorate(GammaPlugin, lifetime="singleton"),
            decorate(build_plugins, as_type=list[Plugin], lifetime="singleton"),
        ]

    def _container(self, entries: list[Any] | None = None) -> Any:
        wireup = importlib.import_module("wireup")
        return wireup.create_sync_container(injectables=entries or self._entries())

    def _validate(self, container: Any) -> None:
        container.get(Clock)
        container.get(list[Plugin])
        with container.enter_scope() as scoped:
            scoped.get(Repository)
            scoped.get(Service)

    def _start_ready(self, entries: list[Any]) -> Any:
        container = self._container(entries)
        container.get(Clock)
        container.get(list[Plugin])
        with container.enter_scope() as scoped:
            scoped.get(Repository)
            scoped.get(Service)
        return container

    def _scoped_get(self, container: Any) -> Any:
        with container.enter_scope() as scoped:
            return scoped.get(Repository)

    def _call_state(self) -> tuple[Any, Callable[[], int]]:
        wireup = importlib.import_module("wireup")
        container = self._container()
        return container, wireup.inject_from_container(container)(wireup_benchmark_handler)

    def _request_cycle(self, container: Any) -> int:
        plugins = container.get(list[Plugin])
        with container.enter_scope() as scoped:
            return benchmark_handler(scoped.get(Service), scoped.get(Repository), plugins)

    def _close(self, container: Any) -> None:
        container.close()

    def _run(self, *, repeat: int, iterations: int) -> LibraryResult:
        metrics = [
            benchmark_metric(
                "freeze",
                "seconds/op",
                iterations=iterations,
                repeat=repeat,
                setup=lambda: None,
                operation=lambda _state: self._entries(),
            ),
            benchmark_metric(
                "start",
                "seconds/op",
                iterations=iterations,
                repeat=repeat,
                setup=self._entries,
                operation=self._container,
                cleanup=lambda _entries, container: self._close(container),
            ),
            benchmark_metric(
                "start_ready",
                "seconds/op",
                iterations=iterations,
                repeat=repeat,
                setup=self._entries,
                operation=self._start_ready,
                cleanup=lambda _entries, container: self._close(container),
            ),
            benchmark_metric(
                "validate",
                "seconds/op",
                iterations=iterations,
                repeat=repeat,
                setup=self._container,
                operation=self._validate,
                cleanup=lambda container, _value: self._close(container),
            ),
            benchmark_metric(
                "singleton_get",
                "seconds/op",
                iterations=iterations * 200,
                repeat=repeat,
                setup=self._container,
                operation=lambda container: container.get(Clock),
                cleanup=lambda container, _value: self._close(container),
            ),
            benchmark_metric(
                "scoped_get",
                "seconds/op",
                iterations=iterations * 100,
                repeat=repeat,
                setup=self._container,
                operation=self._scoped_get,
                cleanup=lambda container, _value: self._close(container),
            ),
            benchmark_metric(
                "collection_all",
                "seconds/op",
                iterations=iterations * 100,
                repeat=repeat,
                setup=self._container,
                operation=lambda container: container.get(list[Plugin]),
                cleanup=lambda container, _value: self._close(container),
            ),
            benchmark_metric(
                "call",
                "seconds/op",
                iterations=iterations * 100,
                repeat=repeat,
                setup=self._call_state,
                operation=lambda state: state[1](),
                cleanup=lambda state, _value: self._close(state[0]),
            ),
            benchmark_metric(
                "request_cycle",
                "seconds/op",
                iterations=iterations * 100,
                repeat=repeat,
                setup=self._container,
                operation=self._request_cycle,
                cleanup=lambda container, _value: self._close(container),
            ),
        ]
        return LibraryResult(
            library=self.library,
            package=self.package,
            supported=True,
            available=True,
            metrics=tuple(metrics),
        )


def available_adapters() -> dict[str, BenchmarkAdapter]:
    return {
        "dixp": DixpAdapter(),
        "dependency-injector": DependencyInjectorAdapter(),
        "injector": InjectorAdapter(),
        "lagom": LagomAdapter(),
        "punq": PunqAdapter(),
        "dishka": DishkaAdapter(),
        "wireup": WireupAdapter(),
    }


def format_table(results: list[LibraryResult]) -> str:
    lines = [f"DI benchmark results in {ROOT}", ""]
    for result in results:
        lines.append(f"[{result.library}]")
        if result.skip_reason is not None:
            lines.append(f"status: skipped")
            lines.append(f"reason: {result.skip_reason}")
            lines.append("")
            continue
        lines.append("status: measured")
        lines.append("metric           best         median       mean         stdev")
        for metric in result.metrics:
            lines.append(
                f"{metric.name:<16} "
                f"{format_seconds(metric.best):<12} "
                f"{format_seconds(metric.median):<12} "
                f"{format_seconds(metric.mean):<12} "
                f"{format_seconds(metric.stdev):<12}"
            )
        lines.append("")
    return "\n".join(lines).rstrip()


def format_json(results: list[LibraryResult]) -> str:
    payload = {
        "root": str(ROOT),
        "results": [
            {
                **asdict(result),
                "metrics": [asdict(metric) for metric in result.metrics],
            }
            for result in results
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local DI benchmarks for dixp and optional competitors.")
    parser.add_argument(
        "--libraries",
        nargs="+",
        default=["dixp", "dependency-injector", "injector", "lagom", "punq", "dishka", "wireup"],
        help="Libraries to benchmark.",
    )
    parser.add_argument("--repeat", type=int, default=5, help="Number of repeated samples per metric.")
    parser.add_argument(
        "--iterations",
        type=int,
        default=50,
        help="Base iteration count. Hot-path metrics multiply this internally.",
    )
    parser.add_argument(
        "--format",
        choices=("table", "json"),
        default="table",
        help="Output format.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    adapters = available_adapters()
    unknown = [name for name in args.libraries if name not in adapters]
    if unknown:
        raise SystemExit(f"Unknown benchmark library names: {', '.join(sorted(unknown))}")

    results = [
        adapters[name].run(repeat=args.repeat, iterations=args.iterations)
        for name in args.libraries
    ]
    if args.format == "json":
        print(format_json(results))
    else:
        print(format_table(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
