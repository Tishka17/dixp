from __future__ import annotations

import asyncio
import unittest
from typing import Annotated, Protocol

from dixp import (
    App,
    CircularDependencyError,
    ContainerClosedError,
    DoctorReport,
    Factory,
    Inject,
    Lazy,
    Lifetime,
    LifetimeMismatchError,
    Provider,
    RegistrationError,
    ResolutionError,
    SafeMode,
    StrictMode,
    TestApp,
    ValidationError,
    bundle,
    scoped,
    service,
    singleton,
    stub,
)


class Clock(Protocol):
    def now(self) -> int: ...


@service(provides=Clock, lifetime="singleton")
class SystemClock:
    def now(self) -> int:
        return 42


class Repository:
    def __init__(self, clock: Clock) -> None:
        self.clock = clock


@service(provides=Repository, lifetime="scoped")
def make_repository(clock: Clock) -> Repository:
    return Repository(clock)


class Service:
    def __init__(self, repository: Repository) -> None:
        self.repository = repository


class Plugin(Protocol):
    def name(self) -> str: ...


class AlphaPlugin:
    def name(self) -> str:
        return "alpha"


class BetaPlugin:
    def name(self) -> str:
        return "beta"


class PluginConsumer:
    def __init__(self, plugins: list[Plugin]) -> None:
        self.plugins = plugins


class SettingsConsumer:
    def __init__(self, settings: Annotated[dict, Inject.named(dict, "main")]) -> None:
        self.settings = settings


class ProviderConsumer:
    def __init__(self, clock_provider: Provider[Clock], repository_factory: Factory[Repository], lazy_clock: Lazy[Clock]) -> None:
        self.clock_provider = clock_provider
        self.repository_factory = repository_factory
        self.lazy_clock = lazy_clock


@service
class ObservableService:
    def __init__(self) -> None:
        self.events: list[str] = []


class TraceableRepository(Repository):
    pass


class ScopedDependency:
    pass


class SingletonDependsOnScoped:
    def __init__(self, dep: ScopedDependency) -> None:
        self.dep = dep


class MissingDependency(Protocol):
    def run(self) -> None: ...


@service
class MissingDependencyConsumer:
    def __init__(self, missing: MissingDependency) -> None:
        self.missing = missing


class AsyncDisposable:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class Disposable:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class A:
    def __init__(self, b: "B") -> None:
        self.b = b


class B:
    def __init__(self, a: A) -> None:
        self.a = a


class AppApiTests(unittest.TestCase):
    def test_app_uses_service_bundle_and_get(self) -> None:
        app = App().include(bundle(SystemClock, make_repository))
        container = app.start()

        repository = container[Repository]

        self.assertIsInstance(repository.clock, SystemClock)
        self.assertEqual(42, container[Clock].now())

    def test_bind_supports_class_factory_and_instance(self) -> None:
        class MessageBuilder:
            def __init__(self, clock: Clock) -> None:
                self.clock = clock

        def make_label(clock: Clock) -> str:
            return f"t={clock.now()}"

        app = (
            App()
            .bind(Clock).singleton(SystemClock)
            .bind(MessageBuilder).to(MessageBuilder)
            .bind(str).factory(make_label)
            .bind(dict).value({"env": "test"})
        )
        container = app.start()

        self.assertEqual(42, container.get(MessageBuilder).clock.now())
        self.assertEqual("t=42", container.get(str))
        self.assertEqual({"env": "test"}, container.get(dict))

    def test_top_level_wiring_helpers_cover_common_cases(self) -> None:
        def make_label(clock: Clock) -> str:
            return f"t={clock.now()}"

        app = (
            App()
            .singleton(Clock, SystemClock)
            .factory(str, make_label)
            .value(dict, {"env": "test"})
            .many(Plugin, AlphaPlugin, BetaPlugin)
        )
        container = app.start()

        self.assertEqual(42, container[Clock].now())
        self.assertEqual("t=42", container[str])
        self.assertEqual({"env": "test"}, container[dict])
        self.assertEqual(["alpha", "beta"], [plugin.name() for plugin in container.all(Plugin)])

    def test_named_bindings_are_first_class(self) -> None:
        container = App().value(dict, {"env": "prod"}, name="main").start()

        consumer = container.get(SettingsConsumer)

        self.assertEqual({"env": "prod"}, consumer.settings)

    def test_many_bindings_resolve_as_list_and_tuple(self) -> None:
        container = App().bind(Plugin).many(AlphaPlugin, BetaPlugin).start()

        plugins = container.get(list[Plugin])
        all_plugins = container.all(Plugin)

        self.assertEqual(["alpha", "beta"], [plugin.name() for plugin in plugins])
        self.assertEqual(["alpha", "beta"], [plugin.name() for plugin in all_plugins])

    def test_bind_accepts_string_lifetime_for_more_pythonic_wiring(self) -> None:
        container = App().bind(Clock).to(SystemClock, lifetime="singleton").start()

        self.assertEqual(42, container[Clock].now())

    def test_child_scope_isolated_for_scoped_services(self) -> None:
        container = App().include(SystemClock, make_repository).start()

        with container.child() as left, container.child() as right:
            left_first = left.get(Repository)
            left_second = left.get(Repository)
            right_repository = right.get(Repository)

        self.assertIs(left_first, left_second)
        self.assertIsNot(left_first, right_repository)

    def test_provider_factory_and_lazy_work_in_new_runtime_api(self) -> None:
        container = App().include(SystemClock, make_repository).start()

        consumer = container.get(ProviderConsumer)

        self.assertEqual(42, consumer.clock_provider.get().now())
        self.assertEqual(42, consumer.repository_factory().clock.now())
        self.assertEqual(42, consumer.lazy_clock.value.now())

    def test_call_and_maybe_are_shortcuts_for_runtime_usage(self) -> None:
        container = App().include(SystemClock, make_repository).start()

        def handler(repository: Repository, flag: bool = False) -> tuple[int, bool]:
            return repository.clock.now(), flag

        self.assertEqual((42, False), container.call(handler))
        self.assertEqual((42, True), container.call(handler, flag=True))
        self.assertEqual("fallback", container.maybe("missing", "fallback"))
        self.assertTrue(container.has(Clock))
        self.assertIn(Clock, container)

    def test_hooks_are_readable_and_apply_in_order(self) -> None:
        def activate(instance: ObservableService, *, key, lifetime) -> None:
            instance.events.append("activated")

        def wrap(instance: ObservableService, *, key, lifetime) -> ObservableService:
            instance.events.append("wrapped")
            return instance

        container = App().include(ObservableService).on(ObservableService).wrap(wrap).on(ObservableService).init(activate).start()

        self.assertEqual(["activated", "wrapped"], container.get(ObservableService).events)

    def test_predicate_hooks_work_for_cross_cutting_rules(self) -> None:
        container = (
            App()
            .include(SystemClock)
            .when(lambda key, lifetime: key is Clock and lifetime is Lifetime.SINGLETON)
            .wrap(lambda instance, *, key, lifetime: type("DecoratedClock", (), {"now": lambda self: instance.now() + 1})())
            .start()
        )

        self.assertEqual(43, container.get(Clock).now())

    def test_blueprint_is_the_inspection_boundary(self) -> None:
        blueprint = App().include(SystemClock).bind(Plugin).many(AlphaPlugin).freeze()

        catalog = blueprint.catalog()
        explanation = blueprint.explain(list[Plugin])

        self.assertTrue(any(item.key is Clock for item in catalog))
        self.assertTrue(any(item.key is Plugin for item in catalog))
        self.assertIn("Plugin", explanation)

    def test_doctor_produces_readable_health_report(self) -> None:
        report = App().include(SystemClock, make_repository).doctor()

        self.assertIsInstance(report, DoctorReport)
        self.assertTrue(report.ok)
        self.assertTrue(report)
        self.assertIn("dixp doctor", str(report))
        self.assertIn("validation passed", str(report))

    def test_doctor_collects_validation_errors(self) -> None:
        report = App().use(SafeMode).include(MissingDependencyConsumer).doctor()

        self.assertFalse(report.ok)
        self.assertTrue(report.errors)
        self.assertIn("Missing registration", report.errors[0])

    def test_safe_mode_validates_on_start(self) -> None:
        app = App().use(SafeMode).include(MissingDependencyConsumer)

        with self.assertRaises(ValidationError):
            app.start()

    def test_strict_mode_disables_implicit_autowiring(self) -> None:
        container = App().use(StrictMode).include(SystemClock).start()

        with self.assertRaises(ResolutionError):
            container.get(Repository)

    def test_override_restores_original_binding(self) -> None:
        container = App().include(SystemClock).start()
        fake_clock = type("FakeClock", (), {"now": lambda self: 7})()

        with container.override(Clock, fake_clock):
            self.assertEqual(7, container.get(Clock).now())

        self.assertEqual(42, container.get(Clock).now())

    def test_test_app_can_replace_services_with_instances(self) -> None:
        fake_clock = stub(name="FakeClock", now=lambda: 7)
        test_app = App().include(SystemClock, make_repository).test().with_instance(Clock, fake_clock)

        self.assertIsInstance(test_app, TestApp)
        self.assertEqual(7, test_app.start().get(Clock).now())

    def test_test_app_can_replace_services_with_stubs(self) -> None:
        container = App().include(SystemClock, make_repository).test().with_stub(Clock, now=lambda: 9).start()

        self.assertEqual(9, container.get(Clock).now())
        self.assertEqual(9, container.get(Repository).clock.now())

    def test_test_app_can_override_named_services(self) -> None:
        container = App().value(dict, {"env": "prod"}, name="main").test().with_instance(
            dict,
            {"env": "test"},
            name="main",
        ).start()

        self.assertEqual({"env": "test"}, container.get(SettingsConsumer).settings)

    def test_stub_supports_attributes_and_zero_arg_methods(self) -> None:
        fake = stub(name="ClockStub", now=lambda: 123, label="dev")

        self.assertEqual(123, fake.now())
        self.assertEqual("dev", fake.label)
        self.assertEqual("<ClockStub>", repr(fake))

    def test_stub_supports_methods_with_arguments(self) -> None:
        fake = stub(name="GreeterStub", greet=lambda name: f"hi {name}")

        self.assertEqual("hi dixp", fake.greet("dixp"))

    def test_decorator_shortcuts_read_naturally(self) -> None:
        class Token(Protocol):
            def value(self) -> str: ...

        @singleton(provides=Token)
        class DefaultToken:
            def value(self) -> str:
                return "singleton"

        @scoped(provides=Repository)
        def build_scoped_repository(clock: Clock) -> Repository:
            return Repository(clock)

        container = App().include(SystemClock, DefaultToken, build_scoped_repository).start()

        self.assertEqual("singleton", container[Token].value())
        with container.child() as left, container.child() as right:
            self.assertIsNot(left[Repository], right[Repository])

    def test_async_runtime_methods_work_with_new_names(self) -> None:
        async def build_resource(clock: Clock) -> AsyncDisposable:
            self.assertEqual(42, clock.now())
            return AsyncDisposable()

        container = App().include(SystemClock).bind(AsyncDisposable).factory(build_resource, lifetime=Lifetime.SINGLETON).start()

        async def scenario() -> None:
            first = await container.aget(AsyncDisposable)
            second = await container.aget(AsyncDisposable)
            self.assertIs(first, second)
            await container.aclose()
            self.assertTrue(first.closed)

        asyncio.run(scenario())

    def test_close_still_closes_runtime_and_rejects_further_usage(self) -> None:
        container = App().bind(Disposable).to(Disposable, lifetime=Lifetime.SINGLETON).start()

        instance = container.get(Disposable)
        container.close()

        self.assertTrue(instance.closed)
        with self.assertRaises(ContainerClosedError):
            container.get(Disposable)

    def test_graph_errors_are_unchanged_under_new_api(self) -> None:
        with self.assertRaises(CircularDependencyError):
            App().start().get(A)

        with self.assertRaises(LifetimeMismatchError):
            App().bind(ScopedDependency).to(ScopedDependency, lifetime=Lifetime.SCOPED).bind(
                SingletonDependsOnScoped
            ).to(SingletonDependsOnScoped, lifetime=Lifetime.SINGLETON).start().get(SingletonDependsOnScoped)

    def test_safe_mode_rejects_bare_string_keys(self) -> None:
        with self.assertRaises(RegistrationError):
            App().use(SafeMode).bind("config").instance({"env": "prod"}).freeze()

    def test_missing_service_error_suggests_next_steps(self) -> None:
        with self.assertRaises(ResolutionError) as error:
            App().start().get(Clock)

        message = str(error.exception)
        self.assertIn("No service for", message)
        self.assertIn("@service", message)
        self.assertIn("app.bind", message)


if __name__ == "__main__":
    unittest.main()
