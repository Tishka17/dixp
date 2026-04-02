from __future__ import annotations

import asyncio
from dataclasses import dataclass
import inspect
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Annotated, Generic, Protocol, TypeVar

from dixp import (
    App,
    AutowireError,
    BundleContractValidationError,
    BundleGraphDiff,
    CircularDependencyError,
    Container,
    ContainerClosedError,
    DoctorReport,
    Factory,
    GraphValidationError,
    Inject,
    Lazy,
    Lifetime,
    LifetimeMismatchError,
    MissingRegistrationError,
    OpenGenericResolutionError,
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
    current_resolver,
    from_env,
)
from dixp.configuration.declarative import open_generic
from dixp.doctor import main as doctor_main

MODULE_NAME = __name__
CONTRACT_SHARED_CLOCK_NAME = f"{MODULE_NAME}.ContractSharedClock"
T = TypeVar("T")


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


class GammaPlugin:
    def name(self) -> str:
        return "gamma"


class PluginConsumer:
    def __init__(self, plugins: list[Plugin]) -> None:
        self.plugins = plugins


class SettingsConsumer:
    def __init__(self, settings: Annotated[dict, Inject.named(dict, "main")]) -> None:
        self.settings = settings


@dataclass(frozen=True, slots=True)
class AppSettings:
    debug: bool
    port: int = 8080
    hosts: tuple[str, ...] = ()
    token: str | None = None


class AppSettingsPort(Protocol):
    debug: bool
    port: int


class AppSettingsConsumer:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings


class ProfiledSettingsConsumer:
    def __init__(self, settings: Annotated[AppSettings, Inject.named(AppSettings, "prod")]) -> None:
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


@service
class ContractSecretStore:
    pass


@service
class ContractPublicFacade:
    def __init__(self, secret: ContractSecretStore) -> None:
        self.secret = secret


@service
class ContractForeignConsumer:
    def __init__(self, secret: ContractSecretStore) -> None:
        self.secret = secret


@service
class ContractInternalClient:
    pass


@service
class ContractPublicApi:
    def __init__(self, client: ContractInternalClient) -> None:
        self.client = client


@service
class ContractWebHandler:
    def __init__(self, client: ContractInternalClient) -> None:
        self.client = client


@service
class ContractSharedClock:
    pass


@service
class ContractScheduledJob:
    def __init__(self, clock: ContractSharedClock) -> None:
        self.clock = clock


@service
class ContractWebClockConsumer:
    def __init__(self, clock: ContractSharedClock) -> None:
        self.clock = clock


@service
class ContractJobsClockConsumer:
    def __init__(self, clock: ContractSharedClock) -> None:
        self.clock = clock


@service
class BundleCycleAlphaConfig:
    pass


@service
class BundleCycleBetaApi:
    def __init__(self, config: BundleCycleAlphaConfig) -> None:
        self.config = config


@service
class BundleCycleAlphaApi:
    def __init__(self, beta: BundleCycleBetaApi) -> None:
        self.beta = beta


class RequestId(str):
    pass


@service
class RequestIdConsumer:
    def __init__(self, request_id: RequestId) -> None:
        self.request_id = request_id


CLI_DOCTOR_APP = (
    App()
    .include(bundle(ContractSharedClock, name="core").exports(ContractSharedClock).allow_incoming_from("web"))
    .include(bundle(ContractWebClockConsumer, name="web").requires(ContractSharedClock))
)
CLI_DOCTOR_BLUEPRINT = CLI_DOCTOR_APP.freeze()
CLI_DOCTOR_ROOT = ContractSharedClock
CLI_DOCTOR_FAILING_APP = (
    App()
    .include(bundle(ContractSharedClock, name="core").exports(ContractSharedClock).allow_incoming_from("web"))
    .include(bundle(ContractJobsClockConsumer, name="jobs").requires(ContractSharedClock))
)
CLI_DOCTOR_DRIFT_APP = (
    App()
    .include(
        bundle(ContractSharedClock, name="core")
        .exports(ContractSharedClock)
        .allow_incoming_from("web", "jobs")
    )
    .include(bundle(ContractWebClockConsumer, name="web").requires(ContractSharedClock))
    .include(bundle(ContractJobsClockConsumer, name="jobs").requires(ContractSharedClock))
)


def make_cli_doctor_app() -> App:
    return CLI_DOCTOR_APP


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

    def test_collection_resolution_preserves_declaration_order_across_single_and_many(self) -> None:
        container = (
            App()
            .many(Plugin, AlphaPlugin)
            .singleton(Plugin, GammaPlugin)
            .many(Plugin, BetaPlugin)
            .start()
        )

        self.assertEqual(["alpha", "gamma", "beta"], [plugin.name() for plugin in container.get(list[Plugin])])
        self.assertEqual(["alpha", "gamma", "beta"], [plugin.name() for plugin in container.all(Plugin)])

    def test_collection_resolution_keeps_single_first_only_when_declared_first(self) -> None:
        container = App().singleton(Plugin, GammaPlugin).many(Plugin, AlphaPlugin, BetaPlugin).start()

        self.assertEqual(["gamma", "alpha", "beta"], [plugin.name() for plugin in container.all(Plugin)])

    def test_bind_accepts_string_lifetime_for_more_pythonic_wiring(self) -> None:
        container = App().bind(Clock).to(SystemClock, lifetime="singleton").start()

        self.assertEqual(42, container[Clock].now())

    def test_from_env_loads_typed_dataclass_settings(self) -> None:
        settings = from_env(
            AppSettings,
            prefix="APP_",
            env={
                "APP_DEBUG": "true",
                "APP_PORT": "9000",
                "APP_HOSTS": "alpha,beta",
                "APP_TOKEN": "",
            },
        )

        self.assertEqual(AppSettings(debug=True, port=9000, hosts=("alpha", "beta"), token=None), settings)

    def test_app_env_binds_typed_settings_from_environment(self) -> None:
        container = (
            App()
            .env(
                AppSettings,
                prefix="APP_",
                env={
                    "APP_DEBUG": "false",
                    "APP_PORT": "7000",
                },
            )
            .start()
        )

        settings = container.get(AppSettingsConsumer).settings

        self.assertEqual(AppSettings(debug=False, port=7000), settings)

    def test_binding_builder_env_supports_explicit_settings_type_and_profiles(self) -> None:
        container = (
            App()
            .bind(AppSettingsPort)
            .env(
                AppSettings,
                prefix="APP_",
                profile="prod",
                env={
                    "APP_DEBUG": "false",
                    "APP_PROD_DEBUG": "true",
                    "APP_PROD_PORT": "9100",
                },
            )
            .env(
                AppSettings,
                prefix="APP_",
                profile="prod",
                name="prod",
                env={
                    "APP_DEBUG": "false",
                    "APP_PROD_DEBUG": "true",
                    "APP_PROD_PORT": "9100",
                },
            )
            .start()
        )

        protocol_settings = container.get(AppSettingsPort)
        profiled_settings = container.get(ProfiledSettingsConsumer).settings

        self.assertEqual(True, protocol_settings.debug)
        self.assertEqual(9100, protocol_settings.port)
        self.assertEqual(AppSettings(debug=True, port=9100), profiled_settings)

    def test_app_env_rejects_missing_required_fields(self) -> None:
        with self.assertRaises(RegistrationError) as error:
            App().env(AppSettings, prefix="APP_", env={"APP_PORT": "7000"})

        self.assertIn("Missing environment variable", str(error.exception))
        self.assertEqual("missing_env_variable", error.exception.code)

    def test_app_env_requires_explicit_settings_type_for_non_type_key(self) -> None:
        with self.assertRaises(RegistrationError) as error:
            App().env("settings")

        self.assertEqual("env_binding_requires_settings_type", error.exception.code)
        self.assertIn("explicit dataclass settings_type", str(error.exception))

    def test_duplicate_registration_error_exposes_structured_code(self) -> None:
        with self.assertRaises(RegistrationError) as error:
            App().singleton(Clock, SystemClock).singleton(Clock, SystemClock).freeze()

        self.assertEqual("duplicate_registration", error.exception.code)
        self.assertIn("Duplicate registration for", str(error.exception))

    def test_child_scope_isolated_for_scoped_services(self) -> None:
        container = App().include(SystemClock, make_repository).start()

        with container.child() as left, container.child() as right:
            left_first = left.get(Repository)
            left_second = left.get(Repository)
            right_repository = right.get(Repository)

        self.assertIs(left_first, left_second)
        self.assertIsNot(left_first, right_repository)

    def test_activate_creates_request_local_scope_and_sets_current_resolver(self) -> None:
        container = App().include(RequestIdConsumer).start()

        with self.assertRaises(ResolutionError):
            current_resolver()

        with container.activate((RequestId, RequestId("req-1"))) as active:
            self.assertIs(active, current_resolver())
            self.assertEqual(RequestId("req-1"), current_resolver().get(RequestId))
            self.assertEqual(RequestId("req-1"), active.get(RequestIdConsumer).request_id)

        with self.assertRaises(ResolutionError):
            current_resolver()

    def test_activate_restores_previous_resolver_after_nested_contexts(self) -> None:
        container = App().include(RequestIdConsumer).start()

        with container.activate((RequestId, RequestId("outer"))) as outer:
            self.assertIs(outer, current_resolver())
            with outer.activate((RequestId, RequestId("inner"))) as inner:
                self.assertIs(inner, current_resolver())
                self.assertEqual(RequestId("inner"), current_resolver().get(RequestId))
            self.assertIs(outer, current_resolver())
            self.assertEqual(RequestId("outer"), current_resolver().get(RequestId))

    def test_activate_supports_async_context_and_contextvars_propagation(self) -> None:
        container = App().include(RequestIdConsumer).start()

        async def read_request_id() -> RequestId:
            await asyncio.sleep(0)
            return current_resolver().get(RequestId)

        async def scenario() -> None:
            async with container.activate((RequestId, RequestId("req-async"))) as active:
                self.assertIs(active, current_resolver())
                self.assertEqual(RequestId("req-async"), await read_request_id())
                consumer = await active.aget(RequestIdConsumer)
                self.assertEqual(RequestId("req-async"), consumer.request_id)

        asyncio.run(scenario())

        with self.assertRaises(ResolutionError):
            current_resolver()

    def test_activate_without_bindings_still_creates_an_isolated_scope(self) -> None:
        container = App().include(SystemClock, make_repository).start()

        root_repository = container.get(Repository)

        with container.activate() as first:
            self.assertIs(first, current_resolver())
            first_repository = first.get(Repository)
            self.assertIs(first_repository, first.get(Repository))
            self.assertIsNot(root_repository, first_repository)

        with container.activate() as second:
            second_repository = second.get(Repository)

        self.assertIsNot(root_repository, second_repository)
        self.assertIsNot(first_repository, second_repository)

    def test_provider_factory_and_lazy_work_in_new_runtime_api(self) -> None:
        container = App().include(SystemClock, make_repository).start()

        consumer = container.get(ProviderConsumer)

        self.assertEqual(42, consumer.clock_provider.get().now())
        self.assertEqual(42, consumer.repository_factory().clock.now())
        self.assertEqual(42, consumer.lazy_clock.value.now())

    def test_warmup_primes_singletons_before_first_use(self) -> None:
        created = 0

        def build_disposable(clock: Clock) -> Disposable:
            nonlocal created
            self.assertEqual(42, clock.now())
            created += 1
            return Disposable()

        container = App().include(SystemClock).bind(Disposable).factory(build_disposable, lifetime=Lifetime.SINGLETON).start()

        warmed = container.warmup(Disposable)

        self.assertIs(container, warmed)
        self.assertEqual(1, created)
        first = container.get(Disposable)
        second = container.get(Disposable)
        self.assertIs(first, second)
        self.assertEqual(1, created)

    def test_start_supports_sync_warmup(self) -> None:
        created = 0

        def build_disposable(clock: Clock) -> Disposable:
            nonlocal created
            self.assertEqual(42, clock.now())
            created += 1
            return Disposable()

        container = (
            App()
            .include(SystemClock)
            .bind(Disposable)
            .factory(build_disposable, lifetime=Lifetime.SINGLETON)
            .start(warmup=(Disposable,))
        )

        self.assertEqual(1, created)
        self.assertIs(container.get(Disposable), container.get(Disposable))

    def test_awarmup_primes_async_singletons_before_first_use(self) -> None:
        created = 0

        async def build_resource(clock: Clock) -> AsyncDisposable:
            nonlocal created
            self.assertEqual(42, clock.now())
            created += 1
            return AsyncDisposable()

        async def scenario() -> None:
            container = App().include(SystemClock).bind(AsyncDisposable).factory(
                build_resource,
                lifetime=Lifetime.SINGLETON,
            ).start()
            warmed = await container.awarmup(AsyncDisposable)
            self.assertIs(container, warmed)
            self.assertEqual(1, created)
            first = await container.aget(AsyncDisposable)
            second = await container.aget(AsyncDisposable)
            self.assertIs(first, second)
            self.assertEqual(1, created)
            await container.aclose()

        asyncio.run(scenario())

    def test_astart_supports_async_warmup(self) -> None:
        created = 0

        async def build_resource(clock: Clock) -> AsyncDisposable:
            nonlocal created
            self.assertEqual(42, clock.now())
            created += 1
            return AsyncDisposable()

        async def scenario() -> None:
            container = await (
                App()
                .include(SystemClock)
                .bind(AsyncDisposable)
                .factory(build_resource, lifetime=Lifetime.SINGLETON)
                .astart(warmup=(AsyncDisposable,))
            )
            self.assertEqual(1, created)
            self.assertIs(await container.aget(AsyncDisposable), await container.aget(AsyncDisposable))
            await container.aclose()

        asyncio.run(scenario())

    def test_call_and_maybe_are_shortcuts_for_runtime_usage(self) -> None:
        container = App().include(SystemClock, make_repository).start()

        def handler(repository: Repository, flag: bool = False) -> tuple[int, bool]:
            return repository.clock.now(), flag

        self.assertEqual((42, False), container.call(handler))
        self.assertEqual((42, True), container.call(handler, flag=True))
        self.assertEqual("fallback", container.maybe("missing", "fallback"))
        self.assertTrue(container.has(Clock))
        self.assertIn(Clock, container)

    def test_call_preserves_user_typeerror_from_handler_body(self) -> None:
        container = App().include(SystemClock).start()

        def handler(clock: Clock) -> int:
            raise TypeError("handler bug")

        with self.assertRaises(TypeError) as error:
            container.call(handler)

        self.assertEqual("handler bug", str(error.exception))

    def test_call_reports_signature_errors_as_resolution_errors(self) -> None:
        container = App().include(SystemClock).start()

        def handler(clock: Clock) -> int:
            return clock.now()

        with self.assertRaises(ResolutionError) as error:
            container.call(handler, unexpected=True)

        self.assertIn("Failed to prepare", str(error.exception))

    def test_factory_preserves_user_typeerror_from_factory_body(self) -> None:
        def build_label(clock: Clock) -> str:
            raise TypeError("factory bug")

        container = App().include(SystemClock).factory(str, build_label).start()

        with self.assertRaises(TypeError) as error:
            container.get(str)

        self.assertEqual("factory bug", str(error.exception))

    def test_acall_preserves_user_typeerror_from_handler_body(self) -> None:
        container = App().include(SystemClock).start()

        async def handler(clock: Clock) -> int:
            raise TypeError("async handler bug")

        async def scenario() -> None:
            with self.assertRaises(TypeError) as error:
                await container.acall(handler)
            self.assertEqual("async handler bug", str(error.exception))

        asyncio.run(scenario())

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

    def test_compiled_graph_can_create_container_directly(self) -> None:
        blueprint = App().include(SystemClock).freeze()

        container = blueprint._compiled.create_container()

        self.assertIsInstance(container, Container)
        self.assertEqual(42, container.get(Clock).now())

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
        self.assertIn("missing_registration", report.error_codes)

    def test_safe_mode_validates_on_start(self) -> None:
        app = App().use(SafeMode).include(MissingDependencyConsumer)

        with self.assertRaises(ValidationError):
            app.start()

    def test_safe_mode_validation_error_exposes_error_codes(self) -> None:
        app = App().use(SafeMode).include(MissingDependencyConsumer)

        with self.assertRaises(GraphValidationError) as error:
            app.start()

        self.assertIn("missing_registration", error.exception.details["error_codes"])

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

    def test_override_respects_registered_wrappers(self) -> None:
        def wrap(instance: Clock, *, key, lifetime) -> Clock:
            return type("DecoratedClock", (), {"now": lambda self: instance.now() + 1})()

        container = App().include(SystemClock).on(Clock).wrap(wrap).start()
        fake_clock = type("FakeClock", (), {"now": lambda self: 7})()

        self.assertEqual(43, container.get(Clock).now())

        with container.override(Clock, fake_clock):
            self.assertEqual(8, container.get(Clock).now())

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
        with self.assertRaises(RegistrationError) as error:
            App().use(SafeMode).bind("config").instance({"env": "prod"}).freeze()

        self.assertEqual("typed_service_key_required", error.exception.code)

    def test_missing_service_error_suggests_next_steps(self) -> None:
        with self.assertRaises(MissingRegistrationError) as error:
            App().start().get(Clock)

        message = str(error.exception)
        self.assertIn("No service for", message)
        self.assertIn("@service", message)
        self.assertIn("app.bind", message)
        self.assertEqual("missing_registration", error.exception.code)

    def test_structured_errors_format_messages_from_details(self) -> None:
        error = MissingRegistrationError(
            details={
                "key": "Clock",
                "suggestions": ("register an implementation", "bind a concrete value"),
            }
        )

        self.assertIn("No service for Clock", str(error))
        self.assertIn("register an implementation", str(error))
        self.assertIn("bind a concrete value", str(error))

    def test_autowire_failure_exposes_structured_error(self) -> None:
        class UntypedDependencyConsumer:
            def __init__(self, dep) -> None:
                self.dep = dep

        with self.assertRaises(AutowireError) as error:
            App().start().get(UntypedDependencyConsumer)

        self.assertEqual("autowire_failure", error.exception.code)
        self.assertIn("Cannot compile", str(error.exception))

    def test_open_generic_failure_exposes_structured_error(self) -> None:
        class GenericPort(Protocol, Generic[T]):
            def value(self) -> T: ...

        class BrokenGenericAdapter(Generic[T]):
            def __init__(self, dep) -> None:
                self.dep = dep

            def value(self) -> T:
                return self.dep

        container = App().include(open_generic(GenericPort, BrokenGenericAdapter)).start()

        with self.assertRaises(OpenGenericResolutionError) as error:
            container.get(GenericPort[int])

        self.assertEqual("open_generic_resolution", error.exception.code)
        self.assertIn("Cannot compile", str(error.exception))

    def test_graph_validation_error_formats_from_structured_details(self) -> None:
        error = GraphValidationError(details={"errors": ("first issue", "second issue")})

        self.assertEqual(
            "Dependency graph validation failed:\n- first issue\n- second issue",
            str(error),
        )

    def test_bundle_contract_error_formats_from_structured_details(self) -> None:
        error = BundleContractValidationError(
            details={
                "reason": "targets private service",
                "source_bundle": "web",
                "target_bundle": "core",
                "key": "SecretStore",
            }
        )

        self.assertEqual(
            "Bundle web depends on private service SecretStore from bundle core",
            str(error),
        )

    def test_bundle_contract_rejects_private_cross_bundle_dependency(self) -> None:
        report = (
            App()
            .include(
                bundle(ContractSecretStore, ContractPublicFacade, name="core")
                .exports(ContractPublicFacade)
                .private(ContractSecretStore)
            )
            .include(bundle(ContractForeignConsumer, name="web"))
            .doctor()
        )

        self.assertFalse(report.ok)
        self.assertTrue(any("private service" in error for error in report.errors))
        self.assertIn("bundle_contract_violation", report.error_codes)

    def test_bundle_contract_validation_uses_structured_error_code(self) -> None:
        app = (
            App()
            .include(
                bundle(ContractSecretStore, ContractPublicFacade, name="core")
                .exports(ContractPublicFacade)
                .private(ContractSecretStore)
            )
            .include(bundle(ContractForeignConsumer, name="web"))
        )

        report = app.doctor()

        self.assertIn("bundle_contract_violation", report.bundle_graph_dict()["error_codes"])
        with self.assertRaises(GraphValidationError) as error:
            app.freeze(validate=False).validate()
        self.assertIn("bundle_contract_violation", error.exception.details["error_codes"])

    def test_bundle_contract_rejects_non_exported_dependency(self) -> None:
        report = (
            App()
            .include(bundle(ContractInternalClient, ContractPublicApi, name="core").exports(ContractPublicApi))
            .include(bundle(ContractWebHandler, name="web").requires(ContractInternalClient))
            .doctor()
        )

        self.assertFalse(report.ok)
        self.assertTrue(any("non-exported service" in error for error in report.errors))

    def test_bundle_contract_requires_explicit_external_dependencies(self) -> None:
        report = (
            App()
            .include(bundle(ContractSharedClock, name="core").exports(ContractSharedClock))
            .include(bundle(ContractScheduledJob, name="jobs").requires())
            .doctor()
        )

        self.assertFalse(report.ok)
        self.assertTrue(any("does not declare it in requires(...)" in error for error in report.errors))

    def test_bundle_metadata_is_visible_in_catalog_and_explain(self) -> None:
        @service
        class TaggedService:
            pass

        blueprint = App().include(bundle(TaggedService, name="core").layer("application").tagged("infra")).freeze()

        info = next(item for item in blueprint.catalog() if item.key is TaggedService)
        explanation = blueprint.explain(TaggedService)

        self.assertEqual("core", info.bundle)
        self.assertIn("{bundle: core; layer: application; tags: infra}", explanation)

    def test_catalog_and_explain_include_registration_source_metadata(self) -> None:
        blueprint = App().include(SystemClock, make_repository).freeze()

        clock_info = next(item for item in blueprint.catalog() if item.key is Clock)
        repository_info = next(item for item in blueprint.catalog() if item.key is Repository)
        explanation = blueprint.explain(Repository)

        clock_location = f"{inspect.getsourcefile(SystemClock)}:{inspect.getsourcelines(SystemClock)[1]}"
        repository_location = f"{inspect.getsourcefile(make_repository)}:{inspect.getsourcelines(make_repository)[1]}"

        self.assertEqual(f"{SystemClock.__module__}.{SystemClock.__qualname__}", clock_info.source)
        self.assertEqual(clock_location, clock_info.source_location)
        self.assertEqual(f"{make_repository.__module__}.{make_repository.__qualname__}", repository_info.source)
        self.assertEqual(repository_location, repository_info.source_location)
        self.assertIn(f"source: {repository_info.source}", explanation)
        self.assertIn(f"defined at: {repository_info.source_location}", explanation)

    def test_bundle_policy_allows_selected_incoming_bundles(self) -> None:
        report = (
            App()
            .include(bundle(ContractSharedClock, name="core").exports(ContractSharedClock).allow_incoming_from("web"))
            .include(bundle(ContractWebClockConsumer, name="web").requires(ContractSharedClock))
            .doctor()
        )

        self.assertTrue(report.ok)
        self.assertIn("incoming/outgoing dependency policies", str(report))
        self.assertEqual(1, len(report.bundle_edges))
        self.assertEqual("web", report.bundle_edges[0].source_bundle)
        self.assertEqual("core", report.bundle_edges[0].target_bundle)
        self.assertIs(ContractSharedClock, report.bundle_edges[0].key)
        self.assertIn("bundle graph:", str(report))
        self.assertIn("web -> core via", str(report))
        payload = json.loads(report.bundle_graph_json())
        self.assertTrue(payload["ok"])
        self.assertEqual(
            {"bundle": "web", "label": "web"},
            next(node for node in payload["nodes"] if node["bundle"] == "web"),
        )
        self.assertEqual(CONTRACT_SHARED_CLOCK_NAME, payload["edges"][0]["key"])
        mermaid = report.bundle_graph_mermaid()
        self.assertIn("flowchart LR", mermaid)
        self.assertIn('bundle_0["core"]', mermaid)
        self.assertIn(f'-->|"{CONTRACT_SHARED_CLOCK_NAME}"|', mermaid)

    def test_bundle_policy_allows_selected_incoming_tags(self) -> None:
        report = (
            App()
            .include(
                bundle(ContractSharedClock, name="core")
                .exports(ContractSharedClock)
                .allow_incoming_from_tags("http")
            )
            .include(bundle(ContractWebClockConsumer, name="web").tagged("http").requires(ContractSharedClock))
            .doctor()
        )

        self.assertTrue(report.ok)
        self.assertEqual(1, len(report.bundle_edges))
        self.assertEqual(0, len(report.bundle_violations))

    def test_bundle_policy_rejects_forbidden_outgoing_dependency(self) -> None:
        report = (
            App()
            .include(bundle(ContractSharedClock, name="core").exports(ContractSharedClock))
            .include(
                bundle(ContractWebClockConsumer, name="web")
                .requires(ContractSharedClock)
                .forbid_outgoing_to("core")
            )
            .doctor()
        )

        self.assertFalse(report.ok)
        self.assertTrue(any("forbids outgoing dependencies" in error for error in report.errors))
        self.assertEqual(1, len(report.bundle_violations))
        self.assertEqual("forbidden by source bundle policy", report.bundle_violations[0].reason)
        self.assertIn("bundle violations:", str(report))
        self.assertIn('-. "violation: forbidden by source bundle policy', report.bundle_graph_mermaid())

    def test_bundle_policy_rejects_forbidden_outgoing_tag_dependency(self) -> None:
        report = (
            App()
            .include(bundle(ContractSharedClock, name="core").exports(ContractSharedClock).tagged("infra"))
            .include(
                bundle(ContractWebClockConsumer, name="web")
                .requires(ContractSharedClock)
                .forbid_outgoing_to_tags("infra")
            )
            .doctor()
        )

        self.assertFalse(report.ok)
        self.assertTrue(any("forbids outgoing dependencies to tags" in error for error in report.errors))
        self.assertEqual("target bundle matches forbidden tags(infra)", report.bundle_violations[0].reason)

    def test_bundle_policy_rejects_forbidden_outgoing_layer_dependency(self) -> None:
        report = (
            App()
            .include(bundle(ContractSharedClock, name="core").exports(ContractSharedClock).layer("infra"))
            .include(
                bundle(ContractWebClockConsumer, name="web")
                .layer("presentation")
                .requires(ContractSharedClock)
                .forbid_outgoing_to_layers("infra")
            )
            .doctor()
        )

        self.assertFalse(report.ok)
        self.assertTrue(any("forbids outgoing dependencies to layer infra" in error for error in report.errors))
        self.assertEqual("target layer is in forbid_outgoing_to_layers(infra)", report.bundle_violations[0].reason)

    def test_bundle_policy_rejects_disallowed_incoming_bundle(self) -> None:
        report = (
            App()
            .include(bundle(ContractSharedClock, name="core").exports(ContractSharedClock).allow_incoming_from("web"))
            .include(bundle(ContractWebClockConsumer, name="web").requires(ContractSharedClock))
            .include(bundle(ContractJobsClockConsumer, name="jobs").requires(ContractSharedClock))
            .doctor()
        )

        self.assertFalse(report.ok)
        self.assertTrue(any("allowed incoming bundles: web" in error for error in report.errors))
        self.assertEqual(2, len(report.bundle_edges))
        self.assertEqual(1, len(report.bundle_violations))
        self.assertEqual("jobs", report.bundle_violations[0].source_bundle)
        self.assertEqual("source bundle is not in allow_incoming_from(web)", report.bundle_violations[0].reason)

    def test_bundle_policy_rejects_disallowed_incoming_tags(self) -> None:
        report = (
            App()
            .include(
                bundle(ContractSharedClock, name="core")
                .exports(ContractSharedClock)
                .allow_incoming_from_tags("http")
            )
            .include(bundle(ContractWebClockConsumer, name="web").tagged("http").requires(ContractSharedClock))
            .include(bundle(ContractJobsClockConsumer, name="jobs").tagged("worker").requires(ContractSharedClock))
            .doctor()
        )

        self.assertFalse(report.ok)
        self.assertTrue(any("allowed incoming tags: http" in error for error in report.errors))
        self.assertEqual(2, len(report.bundle_edges))
        self.assertEqual(1, len(report.bundle_violations))
        self.assertEqual("jobs", report.bundle_violations[0].source_bundle)
        self.assertEqual("source tags do not match allow_incoming_from_tags(http)", report.bundle_violations[0].reason)

    def test_bundle_cycle_detection_reports_cross_bundle_cycles(self) -> None:
        report = (
            App()
            .include(
                bundle(BundleCycleAlphaConfig, BundleCycleAlphaApi, name="alpha")
                .exports(BundleCycleAlphaConfig, BundleCycleAlphaApi)
                .requires(BundleCycleBetaApi)
            )
            .include(
                bundle(BundleCycleBetaApi, name="beta")
                .exports(BundleCycleBetaApi)
                .requires(BundleCycleAlphaConfig)
            )
            .doctor()
        )

        payload = json.loads(report.bundle_graph_json())
        mermaid = report.bundle_graph_mermaid()

        self.assertFalse(report.ok)
        self.assertTrue(any("Bundle dependency cycle detected: alpha -> beta -> alpha" in error for error in report.errors))
        self.assertEqual(1, len(report.bundle_cycles))
        self.assertEqual(("alpha", "beta"), report.bundle_cycles[0].bundles)
        self.assertIn("bundle cycles:", str(report))
        self.assertIn("alpha -> beta -> alpha", str(report))
        self.assertEqual(["alpha", "beta"], payload["cycles"][0]["bundles"])
        self.assertEqual("alpha -> beta -> alpha", payload["cycles"][0]["path"])
        self.assertIn("%% bundle cycle: alpha -> beta -> alpha", mermaid)

    def test_bundle_graph_diff_reports_architectural_drift(self) -> None:
        baseline = CLI_DOCTOR_APP.doctor()
        report = CLI_DOCTOR_DRIFT_APP.doctor()

        diff = report.diff_bundle_graph(baseline)

        self.assertIsInstance(diff, BundleGraphDiff)
        self.assertTrue(diff.drift)
        self.assertEqual(("jobs",), diff.added_nodes)
        self.assertEqual(1, len(diff.added_edges))
        self.assertEqual("jobs", diff.added_edges[0].source_bundle)
        self.assertEqual("core", diff.added_edges[0].target_bundle)
        self.assertEqual(CONTRACT_SHARED_CLOCK_NAME, diff.added_edges[0].key)
        self.assertEqual((), diff.removed_edges)
        self.assertEqual((), diff.added_violations)
        self.assertEqual((), diff.removed_violations)
        self.assertTrue(diff.to_dict()["drift"])
        self.assertIn("bundle graph drift: detected", diff.format())
        self.assertIn("added bundle edges:", diff.format())

    def test_bundle_graph_diff_accepts_json_baseline_and_tracks_removed_violations(self) -> None:
        baseline = CLI_DOCTOR_FAILING_APP.doctor().bundle_graph_json()
        report = CLI_DOCTOR_APP.doctor()

        diff = report.diff_bundle_graph(baseline)

        self.assertTrue(diff.drift)
        self.assertEqual(1, len(diff.removed_violations))
        self.assertEqual("jobs", diff.removed_violations[0].source_bundle)
        self.assertEqual("core", diff.removed_violations[0].target_bundle)
        self.assertEqual("source bundle is not in allow_incoming_from(web)", diff.removed_violations[0].reason)

    def test_doctor_cli_prints_text_report_for_app_reference(self) -> None:
        stream = StringIO()
        with redirect_stdout(stream):
            code = doctor_main([f"{MODULE_NAME}:CLI_DOCTOR_APP"])

        output = stream.getvalue()

        self.assertEqual(0, code)
        self.assertIn("dixp doctor", output)
        self.assertIn("bundle graph:", output)
        self.assertIn(f"web -> core via {CONTRACT_SHARED_CLOCK_NAME}", output)

    def test_doctor_cli_supports_factory_root_and_export_files(self) -> None:
        stream = StringIO()
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = os.path.join(tmpdir, "bundle-graph.json")
            mermaid_path = os.path.join(tmpdir, "bundle-graph.mmd")
            with redirect_stdout(stream):
                code = doctor_main(
                    [
                        f"{MODULE_NAME}:make_cli_doctor_app",
                        "--root",
                        f"{MODULE_NAME}:CLI_DOCTOR_ROOT",
                        "--format",
                        "json",
                        "--json-out",
                        json_path,
                        "--mermaid-out",
                        mermaid_path,
                    ]
                )

            payload = json.loads(stream.getvalue())
            json_payload = json.loads(Path(json_path).read_text(encoding="utf-8"))
            mermaid = Path(mermaid_path).read_text(encoding="utf-8")

        self.assertEqual(0, code)
        self.assertTrue(payload["ok"])
        self.assertEqual([CONTRACT_SHARED_CLOCK_NAME], payload["roots"])
        self.assertEqual(json_payload, payload)
        self.assertIn("flowchart LR", mermaid)
        self.assertIn('bundle_0["core"]', mermaid)

    def test_doctor_cli_supports_blueprint_reference(self) -> None:
        stream = StringIO()
        with redirect_stdout(stream):
            code = doctor_main([f"{MODULE_NAME}:CLI_DOCTOR_BLUEPRINT", "--format", "text"])

        self.assertEqual(0, code)
        self.assertIn("dixp doctor", stream.getvalue())

    def test_doctor_cli_returns_nonzero_for_failed_report(self) -> None:
        stream = StringIO()
        with redirect_stdout(stream):
            code = doctor_main([f"{MODULE_NAME}:CLI_DOCTOR_FAILING_APP", "--format", "mermaid"])

        output = stream.getvalue()

        self.assertEqual(1, code)
        self.assertIn("flowchart LR", output)

    def test_doctor_cli_includes_diff_in_json_output(self) -> None:
        stream = StringIO()
        with tempfile.TemporaryDirectory() as tmpdir:
            baseline_path = os.path.join(tmpdir, "baseline.json")
            Path(baseline_path).write_text(CLI_DOCTOR_APP.doctor().bundle_graph_json(), encoding="utf-8")
            with redirect_stdout(stream):
                code = doctor_main(
                    [
                        f"{MODULE_NAME}:CLI_DOCTOR_DRIFT_APP",
                        "--baseline-json",
                        baseline_path,
                        "--format",
                        "json",
                    ]
                )

        payload = json.loads(stream.getvalue())

        self.assertEqual(0, code)
        self.assertTrue(payload["report"]["ok"])
        self.assertTrue(payload["diff"]["drift"])
        self.assertEqual("jobs", payload["diff"]["added_nodes"][0]["bundle"])
        self.assertEqual("jobs", payload["diff"]["added_edges"][0]["source"])

    def test_doctor_cli_can_fail_on_bundle_graph_drift(self) -> None:
        stream = StringIO()
        with tempfile.TemporaryDirectory() as tmpdir:
            baseline_path = os.path.join(tmpdir, "baseline.json")
            Path(baseline_path).write_text(CLI_DOCTOR_APP.doctor().bundle_graph_json(), encoding="utf-8")
            with redirect_stdout(stream):
                code = doctor_main(
                    [
                        f"{MODULE_NAME}:CLI_DOCTOR_DRIFT_APP",
                        "--baseline-json",
                        baseline_path,
                        "--fail-on-drift",
                    ]
                )

        output = stream.getvalue()

        self.assertEqual(1, code)
        self.assertIn("bundle graph drift: detected", output)
        self.assertIn("added bundle edges:", output)
        self.assertIn(f"jobs -> core via {CONTRACT_SHARED_CLOCK_NAME}", output)


if __name__ == "__main__":
    unittest.main()
