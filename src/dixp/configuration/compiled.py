from __future__ import annotations

from dataclasses import dataclass

from ..core.models import RegistrationInfo, ServiceKey
from ..configuration.registry import RegistrySnapshot
from ..inspection.graph import DoctorReport, GraphInspector
from ..runtime.container import Container
from ..runtime.registry import RuntimeRegistry


@dataclass(frozen=True, slots=True)
class _InspectionRuntime:
    registry: RuntimeRegistry
    inspector: GraphInspector


@dataclass(frozen=True, slots=True)
class CompiledGraph:
    snapshot: RegistrySnapshot
    validate_on_build: bool = False

    def _new_container(self) -> Container:
        return Container(self.snapshot)

    def _prepare_container(self, container: Container) -> Container:
        if self.validate_on_build:
            container.validate()
        return container

    def _inspection_runtime(self) -> _InspectionRuntime:
        registry = RuntimeRegistry(self.snapshot)
        return _InspectionRuntime(registry=registry, inspector=GraphInspector(registry))

    def build(self, *, warmup: tuple[ServiceKey, ...] = ()) -> Container:
        container = self._prepare_container(self._new_container())
        if warmup:
            container.warmup(*warmup)
        return container

    def create_container(self) -> Container:
        return self._prepare_container(self._new_container())

    async def abuild(self, *, warmup: tuple[ServiceKey, ...] = ()) -> Container:
        container = self._prepare_container(self._new_container())
        if warmup:
            await container.awarmup(*warmup)
        return container

    def validate(self, *roots: ServiceKey) -> None:
        self._inspection_runtime().inspector.validate(*roots)

    def explain(self, key: ServiceKey) -> str:
        return self._inspection_runtime().inspector.explain(key)

    def doctor(self, *roots: ServiceKey) -> DoctorReport:
        return self._inspection_runtime().inspector.doctor(*roots)

    def catalog(self, *, include_dynamic: bool = False) -> tuple[RegistrationInfo, ...]:
        return self._inspection_runtime().registry.catalog(include_dynamic=include_dynamic)
