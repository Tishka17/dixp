from __future__ import annotations

from dataclasses import dataclass

from ..core.models import RegistrationInfo, ServiceKey
from ..configuration.registry import RegistrySnapshot
from ..inspection.graph import DoctorReport, GraphInspector
from ..runtime.container import Container
from ..runtime.registry import RuntimeRegistry


@dataclass(frozen=True, slots=True)
class CompiledGraph:
    snapshot: RegistrySnapshot
    validate_on_build: bool = False

    def build(self) -> Container:
        container = Container(self.snapshot)
        if self.validate_on_build:
            container.validate()
        return container

    def create_container(self) -> Container:
        return self.build()

    def validate(self, *roots: ServiceKey) -> None:
        inspector = GraphInspector(RuntimeRegistry(self.snapshot))
        inspector.validate(*roots)

    def explain(self, key: ServiceKey) -> str:
        inspector = GraphInspector(RuntimeRegistry(self.snapshot))
        return inspector.explain(key)

    def doctor(self, *roots: ServiceKey) -> DoctorReport:
        inspector = GraphInspector(RuntimeRegistry(self.snapshot))
        return inspector.doctor(*roots)

    def catalog(self, *, include_dynamic: bool = False) -> tuple[RegistrationInfo, ...]:
        registry = RuntimeRegistry(self.snapshot)
        return registry.catalog(include_dynamic=include_dynamic)
