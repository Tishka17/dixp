from __future__ import annotations

import argparse
from contextlib import contextmanager, nullcontext
import importlib
import importlib.util
import inspect
import json
import statistics
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Protocol, runtime_checkable

ROOT = Path(__file__).resolve().parents[1]


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


@dataclass(frozen=True, slots=True)
class PluginBundle:
    items: tuple[Plugin, ...]


def benchmark_handler(service: Service, repository: Repository, plugins: list[Plugin]) -> int:
    return service.repository.clock.now() + repository.clock.now() + len(plugins)


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


def _call_maybe(obj: Any, *method_names: str) -> Any:
    for name in method_names:
        method = getattr(obj, name, None)
        if callable(method):
            return method()
    return None


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
        check_dependencies = getattr(container, "check_dependencies", None)
        if callable(check_dependencies):
            check_dependencies()
        container.clock()
        container.service()
        container.plugins()

    def _close(self, container: Any) -> None:
        _call_maybe(container, "shutdown_resources")

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

    def _build_module(self) -> tuple[Any, type[Any], Callable[[Callable[..., Any]], Callable[..., Any]]]:
        from injector import Binder, InstanceProvider, Module, Scope, ScopeDecorator, inject, provider, singleton

        class RequestScope(Scope):
            def __init__(self, injector: Any) -> None:
                self.injector = injector
                self._cache: dict[Any, Any] | None = None

            def enter(self) -> None:
                self._cache = {}

            def exit(self) -> None:
                self._cache = None

            def get(self, key: Any, provider: Any) -> Any:
                if self._cache is None:
                    raise RuntimeError("RequestScope is not active")
                if key not in self._cache:
                    self._cache[key] = provider.get(self.injector)
                return InstanceProvider(self._cache[key])

        request_scope = ScopeDecorator(RequestScope)

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
            @request_scope
            def provide_repository(self, clock: Clock, settings: Settings) -> Repository:
                return Repository(clock, settings)

            @provider
            def provide_service(self, repository: Repository) -> Service:
                return Service(repository)

        return BenchModule(), RequestScope, inject

    def _injector(self) -> tuple[Any, type[Any], Callable[[Callable[..., Any]], Callable[..., Any]]]:
        from injector import Injector

        module, request_scope, inject = self._build_module()
        return Injector([module], auto_bind=False), request_scope, inject

    @contextmanager
    def _request_context(self, state: tuple[Any, type[Any], Callable[[Callable[..., Any]], Callable[..., Any]]]):
        injector, request_scope, _inject = state
        scope = injector.get(request_scope)
        scope.enter()
        try:
            yield injector
        finally:
            scope.exit()

    def _validate(self, state: tuple[Any, type[Any], Callable[[Callable[..., Any]], Callable[..., Any]]]) -> None:
        injector, _request_scope, _inject = state
        injector.get(Clock)
        injector.get(list[Plugin])
        with self._request_context(state):
            injector.get(Repository)
            injector.get(Service)

    def _scoped_get(self, state: tuple[Any, type[Any], Callable[[Callable[..., Any]], Callable[..., Any]]]) -> Any:
        with self._request_context(state) as injector:
            return injector.get(Repository)

    def _call(self, state: tuple[Any, type[Any], Callable[[Callable[..., Any]], Callable[..., Any]]]) -> int:
        injector, _request_scope, inject = state

        @inject
        def handler(service: Service, repository: Repository, plugins: list[Plugin]) -> int:
            return benchmark_handler(service, repository, plugins)

        with self._request_context(state):
            return injector.call_with_injection(handler)

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
                operation=lambda _module: self._injector(),
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
                operation=lambda state: state[0].get(Clock),
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
                operation=lambda state: state[0].get(list[Plugin]),
            ),
            benchmark_metric(
                "call",
                "seconds/op",
                iterations=iterations * 100,
                repeat=repeat,
                setup=self._injector,
                operation=self._call,
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
            PluginBundle: lambda _container: PluginBundle((AlphaPlugin(), BetaPlugin(), GammaPlugin())),
        }

    def _container(self) -> Any:
        lagom = importlib.import_module("lagom")
        container = lagom.Container()
        for key, definition in self._definitions().items():
            container[key] = definition
        return container

    def _validate(self, container: Any) -> None:
        container[Clock]
        container[Repository]
        container[Service]
        container[PluginBundle]

    def _call(self, container: Any) -> int:
        magic_partial = getattr(container, "magic_partial", None)
        if callable(magic_partial):
            def handler(service: Service, repository: Repository, plugins: PluginBundle) -> int:
                return benchmark_handler(service, repository, list(plugins.items))

            return magic_partial(handler)()
        bundle = container[PluginBundle]
        return benchmark_handler(container[Service], container[Repository], list(bundle.items))

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
                setup=lambda: None,
                operation=lambda _state: self._container(),
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
                operation=lambda container: container[PluginBundle].items,
            ),
            benchmark_metric(
                "call",
                "seconds/op",
                iterations=iterations * 100,
                repeat=repeat,
                setup=self._container,
                operation=self._call,
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

    def _container(self) -> Any:
        punq = importlib.import_module("punq")
        container = punq.Container()
        container.register(Settings, instance=Settings(debug=True, region="eu-west"))
        container.register(Clock, SystemClock, scope=punq.Scope.singleton)
        container.register(Repository, Repository, scope=punq.Scope.transient)
        container.register(Service, Service, scope=punq.Scope.transient)
        container.register(Plugin, AlphaPlugin)
        container.register(Plugin, BetaPlugin)
        container.register(Plugin, GammaPlugin)
        return container

    def _validate(self, container: Any) -> None:
        container.resolve(Clock)
        container.resolve(Repository)
        container.resolve(Service)
        container.resolve_all(Plugin)

    def _call(self, container: Any) -> int:
        return benchmark_handler(
            container.resolve(Service),
            container.resolve(Repository),
            list(container.resolve_all(Plugin)),
        )

    def _run(self, *, repeat: int, iterations: int) -> LibraryResult:
        metrics = [
            benchmark_metric(
                "freeze",
                "seconds/op",
                iterations=iterations,
                repeat=repeat,
                setup=lambda: None,
                operation=lambda _state: (
                    (Settings, "instance"),
                    (Clock, SystemClock),
                    (Repository, Repository),
                    (Service, Service),
                    (Plugin, AlphaPlugin),
                    (Plugin, BetaPlugin),
                    (Plugin, GammaPlugin),
                ),
            ),
            benchmark_metric(
                "start",
                "seconds/op",
                iterations=iterations,
                repeat=repeat,
                setup=lambda: None,
                operation=lambda _state: self._container(),
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
        Provider = dishka.Provider
        Scope = dishka.Scope
        provide = dishka.provide

        class BenchProvider(Provider):
            @provide(scope=Scope.APP)
            def clock(self) -> Clock:
                return SystemClock()

            @provide(scope=Scope.APP)
            def settings(self) -> Settings:
                return Settings(debug=True, region="eu-west")

            @provide(scope=Scope.REQUEST)
            def repository(self, clock: Clock, settings: Settings) -> Repository:
                return Repository(clock, settings)

            @provide(scope=Scope.REQUEST)
            def service(self, repository: Repository) -> Service:
                return Service(repository)

            @provide(scope=Scope.APP)
            def plugins(self) -> PluginBundle:
                return PluginBundle((AlphaPlugin(), BetaPlugin(), GammaPlugin()))

        return BenchProvider()

    def _container(self) -> Any:
        dishka = importlib.import_module("dishka")
        return dishka.make_container(self._provider())

    def _validate(self, container: Any) -> None:
        container.get(Clock)
        container.get(PluginBundle)
        with container() as request_container:
            request_container.get(Repository)
            request_container.get(Service)

    def _scoped_get(self, container: Any) -> Any:
        with container() as request_container:
            return request_container.get(Repository)

    def _call(self, container: Any) -> int:
        with container() as request_container:
            bundle = request_container.get(PluginBundle)
            return benchmark_handler(
                request_container.get(Service),
                request_container.get(Repository),
                list(bundle.items),
            )

    def _close(self, container: Any) -> None:
        _call_maybe(container, "close")

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
                operation=lambda provider: importlib.import_module("dishka").make_container(provider),
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
                operation=lambda container: container.get(PluginBundle).items,
                cleanup=lambda container, _value: self._close(container),
            ),
            benchmark_metric(
                "call",
                "seconds/op",
                iterations=iterations * 100,
                repeat=repeat,
                setup=self._container,
                operation=self._call,
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

    def _service_decorator(self, wireup: Any) -> Callable[..., Any]:
        decorator = getattr(wireup, "injectable", None) or getattr(wireup, "service", None)
        if decorator is None:
            raise RuntimeError("Wireup service decorator is not available")
        return decorator

    def _apply_service(self, decorator: Callable[..., Any], target: Any, *, as_type: Any | None = None, lifetime: str | None = None) -> Any:
        kwargs: dict[str, Any] = {}
        parameters = inspect.signature(decorator).parameters
        if as_type is not None:
            if "as_type" in parameters:
                kwargs["as_type"] = as_type
            elif "provides" in parameters:
                kwargs["provides"] = as_type
        if lifetime is not None and "lifetime" in parameters:
            kwargs["lifetime"] = lifetime
        try:
            return decorator(target, **kwargs)
        except TypeError:
            return decorator(**kwargs)(target)

    def _entries(self) -> list[Any]:
        wireup = importlib.import_module("wireup")
        decorate = self._service_decorator(wireup)

        class WireClock(SystemClock):
            pass

        class WireRepository(Repository):
            pass

        class WireService(Service):
            pass

        def build_settings() -> Settings:
            return Settings(debug=True, region="eu-west")

        def build_plugins(alpha: AlphaPlugin, beta: BetaPlugin, gamma: GammaPlugin) -> PluginBundle:
            return PluginBundle((alpha, beta, gamma))

        return [
            self._apply_service(decorate, WireClock, as_type=Clock, lifetime="singleton"),
            self._apply_service(decorate, build_settings, as_type=Settings, lifetime="singleton"),
            self._apply_service(decorate, WireRepository, as_type=Repository, lifetime="scoped"),
            self._apply_service(decorate, WireService, as_type=Service, lifetime="transient"),
            self._apply_service(decorate, AlphaPlugin, lifetime="singleton"),
            self._apply_service(decorate, BetaPlugin, lifetime="singleton"),
            self._apply_service(decorate, GammaPlugin, lifetime="singleton"),
            self._apply_service(decorate, build_plugins, as_type=PluginBundle, lifetime="singleton"),
        ]

    def _container(self) -> Any:
        wireup = importlib.import_module("wireup")
        factory = getattr(wireup, "create_sync_container", None)
        if factory is None:
            raise RuntimeError("wireup.create_sync_container is not available")
        parameters = inspect.signature(factory).parameters
        if "injectables" in parameters:
            return factory(injectables=self._entries())
        if "services" in parameters:
            return factory(services=self._entries())
        return factory(self._entries())

    @contextmanager
    def _scope(self, container: Any):
        enter_scope = getattr(container, "enter_scope", None)
        if callable(enter_scope):
            with enter_scope() as scoped:
                yield scoped
            return
        with nullcontext(container) as scoped:
            yield scoped

    def _validate(self, container: Any) -> None:
        container.get(Clock)
        container.get(PluginBundle)
        with self._scope(container) as scoped:
            scoped.get(Repository)
            scoped.get(Service)

    def _scoped_get(self, container: Any) -> Any:
        with self._scope(container) as scoped:
            return scoped.get(Repository)

    def _call(self, container: Any) -> int:
        with self._scope(container) as scoped:
            bundle = scoped.get(PluginBundle)
            return benchmark_handler(scoped.get(Service), scoped.get(Repository), list(bundle.items))

    def _close(self, container: Any) -> None:
        _call_maybe(container, "close", "shutdown")

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
                setup=lambda: None,
                operation=lambda _state: self._container(),
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
                operation=lambda container: container.get(PluginBundle).items,
                cleanup=lambda container, _value: self._close(container),
            ),
            benchmark_metric(
                "call",
                "seconds/op",
                iterations=iterations * 100,
                repeat=repeat,
                setup=self._container,
                operation=self._call,
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
