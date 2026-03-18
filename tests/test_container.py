from __future__ import annotations

import asyncio
import importlib
import types
import unittest
from typing import Annotated, Generic, Protocol, TypeVar

from dixp import (
    AutowirePolicy,
    BuildProfile,
    Builder,
    CircularDependencyError,
    DuplicatePolicy,
    EnterpriseMode,
    Factory,
    ForbidLifetimePolicy,
    Inject,
    Lazy,
    Lifetime,
    LifetimeMismatchError,
    Provider,
    RegistrationError,
    RequireQualifierPolicy,
    ResolutionError,
    StrictMode,
    ValidationError,
    activate,
    component,
    contribute,
    decorate,
    instance,
    module,
    open_generic,
    qualified,
    singleton,
)


class Clock(Protocol):
    def now(self) -> int: ...


@component(as_=Clock, lifetime=Lifetime.SINGLETON)
class SystemClock:
    def now(self) -> int:
        return 42


class Repository:
    def __init__(self, clock: Clock) -> None:
        self.clock = clock


@component(as_=Repository, lifetime=Lifetime.SCOPED)
def build_repository(clock: Clock) -> Repository:
    return Repository(clock)


class Service:
    def __init__(self, repository: Repository) -> None:
        self.repository = repository


class ScopedDependency:
    pass


class SingletonDependsOnScoped:
    def __init__(self, dep: ScopedDependency) -> None:
        self.dep = dep


class NamedConfigConsumer:
    def __init__(self, config: Annotated[dict, Inject("config")]) -> None:
        self.config = config


class QualifiedConfigConsumer:
    def __init__(self, config: Annotated[dict, Inject.qualified(dict, "main")]) -> None:
        self.config = config


class Disposable:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class AsyncDisposable:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class CountingDisposable:
    def __init__(self) -> None:
        self.close_count = 0

    def close(self) -> None:
        self.close_count += 1


class A:
    def __init__(self, b: "B") -> None:
        self.b = b


class B:
    def __init__(self, a: A) -> None:
        self.a = a


class MissingDependency(Protocol):
    def run(self) -> None: ...


class MissingDependencyConsumer:
    def __init__(self, missing: MissingDependency) -> None:
        self.missing = missing


class Plugin(Protocol):
    def name(self) -> str: ...


@component(as_=Plugin, multiple=True)
class AlphaPlugin:
    def name(self) -> str:
        return "alpha"


@component(as_=Plugin, multiple=True)
class BetaPlugin:
    def name(self) -> str:
        return "beta"


class PluginConsumer:
    def __init__(self, plugins: list[Plugin]) -> None:
        self.plugins = plugins


T = TypeVar("T")


class Serializer(Protocol[T]):
    def dump(self, value: T) -> T: ...


class IdentitySerializer(Generic[T]):
    def dump(self, value: T) -> T:
        return value


class GenericRepository(Protocol[T]):
    def save(self, value: T) -> T: ...


class InMemoryRepository(Generic[T]):
    def __init__(self, serializer: Serializer[T]) -> None:
        self.serializer = serializer

    def save(self, value: T) -> T:
        return self.serializer.dump(value)


class NumberService:
    def __init__(self, repository: GenericRepository[int]) -> None:
        self.repository = repository


@component(lifetime=Lifetime.SINGLETON)
class ManagedService:
    def __init__(self) -> None:
        self.value = "managed"


class NeedsManagedService:
    def __init__(self, service: ManagedService) -> None:
        self.service = service


class PlainService:
    pass


class ObservableService:
    def __init__(self) -> None:
        self.events: list[str] = []


class ProviderConsumer:
    def __init__(self, clock_provider: Provider[Clock], repository_factory: Factory[Repository], lazy_clock: Lazy[Clock]) -> None:
        self.clock_provider = clock_provider
        self.repository_factory = repository_factory
        self.lazy_clock = lazy_clock


class TraceableRepository(Repository):
    pass


def app_module() -> object:
    return module(SystemClock, build_repository, instance("config", {"env": "module"}))


def feature_toggle_module(env: str) -> object:
    return module(instance("config", {"env": env}))


class ContainerTests(unittest.TestCase):
    def test_singleton_and_autowiring(self) -> None:
        container = Builder().component(SystemClock).build()

        first = container.resolve(Service)
        second = container.resolve(Service)

        self.assertIsInstance(first.repository.clock, SystemClock)
        self.assertIs(first.repository.clock, second.repository.clock)
        self.assertIsNot(first, second)

    def test_scoped_lifetime_isolated_per_scope(self) -> None:
        container = Builder().component(SystemClock).component(build_repository).build()

        with container.scope() as left, container.scope() as right:
            left_first = left.resolve(Repository)
            left_second = left.resolve(Repository)
            right_instance = right.resolve(Repository)

        self.assertIs(left_first, left_second)
        self.assertIsNot(left_first, right_instance)

    def test_named_dependency_via_annotated_inject(self) -> None:
        container = Builder().instance("config", {"env": "test"}).build()

        consumer = container.resolve(NamedConfigConsumer)

        self.assertEqual({"env": "test"}, consumer.config)

    def test_qualified_bindings_provide_typed_named_keys(self) -> None:
        token = qualified(dict, "main")
        container = Builder().qualify(dict, "main", instance={"env": "typed"}, lifetime=Lifetime.SINGLETON).build()

        consumer = container.resolve(QualifiedConfigConsumer)

        self.assertEqual({"env": "typed"}, consumer.config)
        self.assertEqual({"env": "typed"}, container.resolve(token))

    def test_declarative_module_registration_collects_entries(self) -> None:
        container = Builder().module(app_module()).build()

        consumer = container.resolve(NamedConfigConsumer)

        with container.scope() as left, container.scope() as right:
            left_repository = left.resolve(Repository)
            right_repository = right.resolve(Repository)

        self.assertEqual({"env": "module"}, consumer.config)
        self.assertIsInstance(left_repository.clock, SystemClock)
        self.assertIs(left_repository.clock, right_repository.clock)
        self.assertIsNot(left_repository, right_repository)

    def test_parameterized_module_function_is_supported(self) -> None:
        container = Builder().module(feature_toggle_module("prod")).build()

        self.assertEqual({"env": "prod"}, container.resolve("config"))

    def test_multibindings_resolve_as_collection(self) -> None:
        container = Builder().add(contribute(Plugin, AlphaPlugin), contribute(Plugin, BetaPlugin)).build()

        plugins = container.resolve(list[Plugin])
        all_plugins = container.resolve_all(Plugin)

        self.assertEqual(["alpha", "beta"], [plugin.name() for plugin in plugins])
        self.assertEqual(["alpha", "beta"], [plugin.name() for plugin in all_plugins])

    def test_component_multiple_contributes_to_multibindings(self) -> None:
        container = Builder().module(module(AlphaPlugin, BetaPlugin)).build()

        consumer = container.resolve(PluginConsumer)

        self.assertEqual(["alpha", "beta"], [plugin.name() for plugin in consumer.plugins])

    def test_empty_multibinding_collection_resolves_to_empty_list(self) -> None:
        container = Builder().build()

        self.assertEqual([], container.resolve(list[Plugin]))

    def test_open_generic_registration_specializes_dependencies(self) -> None:
        container = Builder().add(
            open_generic(Serializer, IdentitySerializer, lifetime=Lifetime.SINGLETON),
            open_generic(GenericRepository, InMemoryRepository),
        ).build()

        repository = container.resolve(GenericRepository[int])
        service = container.resolve(NumberService)

        self.assertEqual(5, repository.save(5))
        self.assertEqual(7, service.repository.save(7))

    def test_validate_accepts_closed_generic_root(self) -> None:
        Builder().add(
            open_generic(Serializer, IdentitySerializer, lifetime=Lifetime.SINGLETON),
            open_generic(GenericRepository, InMemoryRepository),
        ).validate(GenericRepository[int])

    def test_builder_supports_single_multi_and_open_generic_bindings(self) -> None:
        container = (
            Builder()
            .component(SystemClock)
            .contribute(Plugin, AlphaPlugin)
            .contribute(Plugin, BetaPlugin)
            .open_generic(Serializer, IdentitySerializer, lifetime=Lifetime.SINGLETON)
            .build()
        )

        self.assertEqual(42, container.resolve(Clock).now())
        self.assertEqual(["alpha", "beta"], [plugin.name() for plugin in container.resolve(list[Plugin])])
        self.assertEqual(3, container.resolve(Serializer[int]).dump(3))

    def test_provider_factory_and_lazy_injection_are_first_class(self) -> None:
        container = Builder().component(SystemClock).build()

        consumer = container.resolve(ProviderConsumer)

        self.assertEqual(42, consumer.clock_provider.get().now())
        self.assertEqual(42, consumer.repository_factory().clock.now())
        self.assertEqual(42, consumer.lazy_clock.value.now())

    def test_provider_factory_and_lazy_can_be_resolved_directly(self) -> None:
        container = Builder().component(SystemClock).build()

        clock_provider = container.resolve(Provider[Clock])
        repository_factory = container.resolve(Factory[Repository])
        lazy_clock = container.resolve(Lazy[Clock])

        self.assertEqual(42, clock_provider.get().now())
        self.assertEqual(42, repository_factory().clock.now())
        self.assertEqual(42, lazy_clock.value.now())

    def test_diagnostics_understand_provider_requests(self) -> None:
        container = Builder().component(SystemClock).build()

        explanation = container.explain(Provider[Clock])
        container.validate(Provider[Clock])

        self.assertIn("Provider", explanation)
        self.assertIn("Clock", explanation)

    def test_component_metadata_controls_lifetime(self) -> None:
        container = Builder().component(ManagedService).build()

        first = container.resolve(ManagedService)
        second = container.resolve(NeedsManagedService).service

        self.assertIs(first, second)

    def test_annotated_autowire_policy_requires_component_metadata(self) -> None:
        container = (
            Builder(autowire_policy=AutowirePolicy.ANNOTATED)
            .component(ManagedService)
            .component(NeedsManagedService)
            .build()
        )

        self.assertEqual("managed", container.resolve(NeedsManagedService).service.value)
        with self.assertRaises(ResolutionError):
            container.resolve(PlainService)

    def test_strict_profile_disables_implicit_autowiring(self) -> None:
        container = Builder().use(StrictMode).component(SystemClock).build()

        with self.assertRaises(ResolutionError):
            container.resolve(Repository)

    def test_enterprise_profile_validates_on_build_by_default(self) -> None:
        builder = Builder().use(EnterpriseMode).component(MissingDependencyConsumer)

        with self.assertRaises(ValidationError):
            builder.build()

    def test_enterprise_profile_rejects_bare_string_keys(self) -> None:
        with self.assertRaises(RegistrationError):
            Builder().use(EnterpriseMode).instance("config", {"env": "prod"}).compile()

    def test_custom_policy_can_forbid_lifetimes(self) -> None:
        with self.assertRaises(RegistrationError):
            Builder().policy(ForbidLifetimePolicy(Lifetime.SINGLETON)).component(SystemClock).compile()

    def test_custom_policy_can_require_qualifiers(self) -> None:
        with self.assertRaises(RegistrationError):
            Builder().policy(RequireQualifierPolicy()).component(SystemClock).compile()

        Builder().policy(RequireQualifierPolicy()).qualify(
            Clock,
            "main",
            implementation=SystemClock,
            lifetime=Lifetime.SINGLETON,
        ).compile()

    def test_interceptor_can_wrap_explicit_registration(self) -> None:
        container = (
            Builder()
            .component(SystemClock)
            .component(build_repository)
            .decorate(Repository, lambda instance, *, key, lifetime: TraceableRepository(instance.clock))
            .build()
        )

        repository = container.resolve(Repository)

        self.assertIsInstance(repository, TraceableRepository)
        self.assertEqual(42, repository.clock.now())

    def test_interceptor_can_wrap_dynamic_autowire_registration(self) -> None:
        container = (
            Builder()
            .component(SystemClock)
            .decorate(Repository, lambda instance, *, key, lifetime: TraceableRepository(instance.clock))
            .build()
        )

        service = container.resolve(Service)

        self.assertIsInstance(service.repository, TraceableRepository)

    def test_interceptor_can_target_by_predicate(self) -> None:
        container = (
            Builder()
            .component(SystemClock)
            .decorate_where(
                lambda key, lifetime: key is Clock and lifetime is Lifetime.SINGLETON,
                lambda instance, *, key, lifetime: type("DecoratedClock", (), {"now": lambda self: instance.now() + 1})(),
            )
            .build()
        )

        self.assertEqual(43, container.resolve(Clock).now())

    def test_activation_hook_is_applied_before_interceptors_even_if_added_later(self) -> None:
        def intercept_instance(instance: ObservableService, *, key, lifetime) -> ObservableService:
            instance.events.append("intercepted")
            return instance

        def activate_instance(instance: ObservableService, *, key, lifetime) -> None:
            instance.events.append("activated")

        container = (
            Builder()
            .component(ObservableService)
            .decorate(ObservableService, intercept_instance)
            .activate(ObservableService, activate_instance)
            .build()
        )

        service = container.resolve(ObservableService)

        self.assertEqual(["activated", "intercepted"], service.events)

    def test_activation_hook_can_wrap_dynamic_autowire_registration(self) -> None:
        def activate_repository(instance: Repository, *, key, lifetime) -> None:
            instance.activated = True

        container = Builder().component(SystemClock).activate(Repository, activate_repository).build()

        service = container.resolve(Service)

        self.assertTrue(service.repository.activated)

    def test_interceptors_follow_declared_order(self) -> None:
        def late(instance: ObservableService, *, key, lifetime) -> ObservableService:
            instance.events.append("late")
            return instance

        def early(instance: ObservableService, *, key, lifetime) -> ObservableService:
            instance.events.append("early")
            return instance

        container = (
            Builder()
            .component(ObservableService)
            .decorate(ObservableService, late, order=20)
            .decorate(ObservableService, early, order=10)
            .build()
        )

        service = container.resolve(ObservableService)

        self.assertEqual(["early", "late"], service.events)

    def test_catalog_and_explain_provide_diagnostics(self) -> None:
        compiled = (
            Builder()
            .component(SystemClock)
            .contribute(Plugin, AlphaPlugin)
            .open_generic(Serializer, IdentitySerializer, lifetime=Lifetime.SINGLETON)
            .compile()
        )

        catalog = compiled.catalog()
        explanation = compiled.explain(list[Plugin])

        self.assertTrue(any(item.kind == "single" and item.key is Clock for item in catalog))
        self.assertTrue(any(item.kind == "multi" and item.key is Plugin for item in catalog))
        self.assertTrue(any(item.kind == "open_generic" and item.key is Serializer for item in catalog))
        self.assertIn("list[test_container.Plugin]", explanation)
        self.assertIn("test_container.Plugin[0]", explanation)

    def test_catalog_can_include_dynamic_runtime_registrations(self) -> None:
        container = Builder().component(SystemClock).open_generic(Serializer, IdentitySerializer, lifetime=Lifetime.SINGLETON).build()

        container.resolve(Repository)
        container.resolve(Serializer[int])
        catalog = container.catalog(include_dynamic=True)

        self.assertTrue(any(item.kind == "autowire" and item.key is Repository for item in catalog))
        self.assertTrue(any(item.kind == "closed_generic" and item.key == Serializer[int] for item in catalog))

    def test_explain_shows_policies_activations_and_interceptors(self) -> None:
        token = qualified(Clock, "main")

        def activate_clock(instance: Clock, *, key, lifetime) -> None:
            return None

        def wrap_clock(instance: Clock, *, key, lifetime) -> Clock:
            return instance

        container = (
            Builder()
            .policy(RequireQualifierPolicy())
            .qualify(Clock, "main", implementation=SystemClock, lifetime=Lifetime.SINGLETON)
            .activate(token, activate_clock)
            .decorate(token, wrap_clock)
            .build()
        )

        explanation = container.explain(token)

        self.assertIn("policies: RequireQualifierPolicy", explanation)
        self.assertIn("activations: activate_clock", explanation)
        self.assertIn("interceptors: wrap_clock", explanation)

    def test_compiled_graph_exposes_immutable_registry_boundary(self) -> None:
        compiled = Builder().component(SystemClock).compile()

        self.assertIsInstance(compiled.snapshot.registrations, types.MappingProxyType)
        with self.assertRaises(TypeError):
            compiled.snapshot.registrations[Clock] = object()

    def test_layered_packages_expose_common_entry_points(self) -> None:
        api = importlib.import_module("dixp.api")
        configuration = importlib.import_module("dixp.configuration")
        runtime = importlib.import_module("dixp.runtime")
        inspection = importlib.import_module("dixp.inspection")
        core = importlib.import_module("dixp.core")

        self.assertIs(api.Builder, Builder)
        self.assertIs(configuration.Builder, Builder)
        self.assertTrue(hasattr(runtime, "RuntimeRegistry"))
        self.assertTrue(hasattr(inspection, "GraphInspector"))
        self.assertTrue(hasattr(core, "RegistryPort"))

    def test_invoke_injects_missing_parameters(self) -> None:
        container = Builder().component(SystemClock).build()

        def handler(repository: Repository, flag: bool = False) -> tuple[int, bool]:
            return repository.clock.now(), flag

        self.assertEqual((42, False), container.invoke(handler))
        self.assertEqual((42, True), container.invoke(handler, flag=True))

    def test_override_is_scoped_and_restores_original_registration(self) -> None:
        container = Builder().component(SystemClock).build()

        fake_clock = type("FakeClock", (), {"now": lambda self: 7})()

        with container.override(Clock, fake_clock):
            overridden = container.resolve(Repository)
            self.assertEqual(7, overridden.clock.now())

        original = container.resolve(Repository)
        self.assertEqual(42, original.clock.now())

    def test_circular_dependency_detected(self) -> None:
        container = Builder().build()

        with self.assertRaises(CircularDependencyError):
            container.resolve(A)

    def test_singleton_cannot_capture_scoped_dependency(self) -> None:
        container = Builder().scoped(ScopedDependency).singleton(SingletonDependsOnScoped).build()

        with self.assertRaises(LifetimeMismatchError):
            container.resolve(SingletonDependsOnScoped)

    def test_try_resolve_returns_default_for_missing_dependency(self) -> None:
        container = Builder().build()

        self.assertEqual("fallback", container.try_resolve("missing", "fallback"))

    def test_close_disposes_cached_instances(self) -> None:
        container = Builder().singleton(Disposable).build()

        instance = container.resolve(Disposable)
        container.close()

        self.assertTrue(instance.closed)

    def test_alias_does_not_double_dispose_shared_singleton(self) -> None:
        shared = CountingDisposable()
        container = (
            Builder()
            .instance(CountingDisposable, shared)
            .alias("shared", CountingDisposable, lifetime=Lifetime.SINGLETON)
            .build()
        )

        self.assertIs(shared, container.resolve(CountingDisposable))
        self.assertIs(shared, container.resolve("shared"))

        container.close()

        self.assertEqual(1, shared.close_count)

    def test_closed_container_rejects_further_usage(self) -> None:
        container = Builder().component(Disposable).build()

        container.resolve(Disposable)
        container.close()

        from dixp import ContainerClosedError

        with self.assertRaises(ContainerClosedError):
            container.resolve(Disposable)
        with self.assertRaises(ContainerClosedError):
            container.scope()

    def test_duplicate_registration_is_rejected_by_default(self) -> None:
        builder = Builder().component(SystemClock)

        with self.assertRaises(RegistrationError):
            builder.component(SystemClock).compile()

    def test_duplicate_registration_can_be_replaced_explicitly(self) -> None:
        class AlternateClock:
            def now(self) -> int:
                return 99

        container = (
            Builder(duplicate_policy=DuplicatePolicy.REPLACE)
            .component(SystemClock)
            .singleton(Clock, AlternateClock)
            .build()
        )

        self.assertEqual(99, container.resolve(Clock).now())

    def test_validate_detects_invalid_graph_before_runtime(self) -> None:
        builder = Builder().component(MissingDependencyConsumer)

        with self.assertRaises(ValidationError) as error:
            builder.compile(validate=True)

        self.assertIn("Missing registration", str(error.exception))

    def test_async_factory_and_async_close(self) -> None:
        async def create_resource(clock: Clock) -> AsyncDisposable:
            self.assertEqual(42, clock.now())
            return AsyncDisposable()

        container = Builder().component(SystemClock).singleton(AsyncDisposable, factory=create_resource).build()

        async def scenario() -> None:
            first = await container.aresolve(AsyncDisposable)
            second = await container.aresolve(AsyncDisposable)
            self.assertIs(first, second)
            await container.aclose()
            self.assertTrue(first.closed)

        asyncio.run(scenario())

    def test_ainvoke_supports_async_handlers(self) -> None:
        container = Builder().component(SystemClock).build()

        async def handler(repository: Repository) -> int:
            await asyncio.sleep(0)
            return repository.clock.now()

        result = asyncio.run(container.ainvoke(handler))

        self.assertEqual(42, result)

    def test_sync_api_rejects_async_provider(self) -> None:
        async def create_resource() -> AsyncDisposable:
            return AsyncDisposable()

        container = Builder().singleton(AsyncDisposable, factory=create_resource).build()

        with self.assertRaises(ResolutionError):
            container.resolve(AsyncDisposable)

    def test_resolution_error_for_untyped_required_parameter(self) -> None:
        class Invalid:
            def __init__(self, dependency) -> None:
                self.dependency = dependency

        container = Builder().build()

        with self.assertRaises(ResolutionError) as error:
            container.resolve(Invalid)

        self.assertIn("no injectable type hint", str(error.exception))


if __name__ == "__main__":
    unittest.main()
