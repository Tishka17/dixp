from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from ..core.errors import (
    BundleContractValidationError,
    GraphValidationError,
    MissingRegistrationValidationError,
    ResolutionError,
    ValidationError,
)
from ..core.error_formatting import format_error_message
from ..core.graph import Registration, collection_spec, describe_key, request_wrapper_spec
from ..core.models import RegistrationInfo, Lifetime, ServiceKey
from ..core.ports import InspectorPort, RegistryPort
from ..core.resolution import ResolutionContext, format_path


@dataclass(frozen=True, slots=True)
class BundleEdge:
    source_bundle: str | None
    target_bundle: str | None
    key: ServiceKey


@dataclass(frozen=True, slots=True)
class BundleViolation:
    source_bundle: str | None
    target_bundle: str | None
    key: ServiceKey
    reason: str


@dataclass(frozen=True, slots=True)
class BundleCycle:
    bundles: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BundleGraphEdgeRecord:
    source_bundle: str | None
    target_bundle: str | None
    key: str


@dataclass(frozen=True, slots=True)
class BundleGraphViolationRecord:
    source_bundle: str | None
    target_bundle: str | None
    key: str
    reason: str


@dataclass(frozen=True, slots=True)
class BundleGraphDiff:
    added_nodes: tuple[str | None, ...] = ()
    removed_nodes: tuple[str | None, ...] = ()
    added_edges: tuple[BundleGraphEdgeRecord, ...] = ()
    removed_edges: tuple[BundleGraphEdgeRecord, ...] = ()
    added_violations: tuple[BundleGraphViolationRecord, ...] = ()
    removed_violations: tuple[BundleGraphViolationRecord, ...] = ()

    @staticmethod
    def _bundle_label(bundle: str | None) -> str:
        return bundle or "<app>"

    @property
    def drift(self) -> bool:
        return any(
            (
                self.added_nodes,
                self.removed_nodes,
                self.added_edges,
                self.removed_edges,
                self.added_violations,
                self.removed_violations,
            )
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "drift": self.drift,
            "added_nodes": [
                {
                    "bundle": bundle,
                    "label": self._bundle_label(bundle),
                }
                for bundle in self.added_nodes
            ],
            "removed_nodes": [
                {
                    "bundle": bundle,
                    "label": self._bundle_label(bundle),
                }
                for bundle in self.removed_nodes
            ],
            "added_edges": [
                {
                    "source": edge.source_bundle,
                    "target": edge.target_bundle,
                    "key": edge.key,
                }
                for edge in self.added_edges
            ],
            "removed_edges": [
                {
                    "source": edge.source_bundle,
                    "target": edge.target_bundle,
                    "key": edge.key,
                }
                for edge in self.removed_edges
            ],
            "added_violations": [
                {
                    "source": violation.source_bundle,
                    "target": violation.target_bundle,
                    "key": violation.key,
                    "reason": violation.reason,
                }
                for violation in self.added_violations
            ],
            "removed_violations": [
                {
                    "source": violation.source_bundle,
                    "target": violation.target_bundle,
                    "key": violation.key,
                    "reason": violation.reason,
                }
                for violation in self.removed_violations
            ],
        }

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @classmethod
    def _format_edges(
        cls,
        title: str,
        edges: tuple[BundleGraphEdgeRecord, ...],
    ) -> tuple[str, ...]:
        if not edges:
            return ()
        return (title,) + tuple(
            f"- {cls._bundle_label(edge.source_bundle)} -> {cls._bundle_label(edge.target_bundle)} via {edge.key}"
            for edge in edges
        )

    @classmethod
    def _format_violations(
        cls,
        title: str,
        violations: tuple[BundleGraphViolationRecord, ...],
    ) -> tuple[str, ...]:
        if not violations:
            return ()
        return (title,) + tuple(
            f"- {cls._bundle_label(violation.source_bundle)} -> {cls._bundle_label(violation.target_bundle)} "
            f"via {violation.key}: {violation.reason}"
            for violation in violations
        )

    def format(self) -> str:
        lines = [f"bundle graph drift: {'detected' if self.drift else 'none'}"]
        if self.added_nodes:
            lines.append("added bundles:")
            lines.extend(f"- {self._bundle_label(bundle)}" for bundle in self.added_nodes)
        if self.removed_nodes:
            lines.append("removed bundles:")
            lines.extend(f"- {self._bundle_label(bundle)}" for bundle in self.removed_nodes)
        lines.extend(self._format_edges("added bundle edges:", self.added_edges))
        lines.extend(self._format_edges("removed bundle edges:", self.removed_edges))
        lines.extend(self._format_violations("added bundle violations:", self.added_violations))
        lines.extend(self._format_violations("removed bundle violations:", self.removed_violations))
        return "\n".join(lines)

    def __str__(self) -> str:
        return self.format()

    def __bool__(self) -> bool:
        return self.drift


@dataclass(frozen=True, slots=True)
class DiagnosticIssue:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class DoctorReport:
    ok: bool
    roots: tuple[ServiceKey, ...]
    registrations: tuple[RegistrationInfo, ...]
    errors: tuple[str, ...]
    error_codes: tuple[str, ...]
    notes: tuple[str, ...]
    bundle_edges: tuple[BundleEdge, ...] = ()
    bundle_violations: tuple[BundleViolation, ...] = ()
    bundle_cycles: tuple[BundleCycle, ...] = ()

    @staticmethod
    def _bundle_label(bundle: str | None) -> str:
        return bundle or "<app>"

    @classmethod
    def _format_bundle_graph(cls, edges: tuple[BundleEdge, ...]) -> tuple[str, ...]:
        grouped: dict[tuple[str | None, str | None], list[ServiceKey]] = {}
        for edge in edges:
            grouped.setdefault((edge.source_bundle, edge.target_bundle), []).append(edge.key)
        lines: list[str] = []
        for source_bundle, target_bundle in sorted(grouped, key=lambda item: (repr(item[0]), repr(item[1]))):
            keys = ", ".join(sorted(describe_key(key) for key in grouped[(source_bundle, target_bundle)]))
            lines.append(
                f"- {cls._bundle_label(source_bundle)} -> {cls._bundle_label(target_bundle)} via {keys}"
            )
        return tuple(lines)

    @classmethod
    def _format_bundle_violations(cls, violations: tuple[BundleViolation, ...]) -> tuple[str, ...]:
        return tuple(
            f"- {cls._bundle_label(item.source_bundle)} -> {cls._bundle_label(item.target_bundle)} "
            f"via {describe_key(item.key)}: {item.reason}"
            for item in sorted(
                violations,
                key=lambda item: (
                    repr(item.source_bundle),
                    repr(item.target_bundle),
                    describe_key(item.key),
                    item.reason,
                ),
            )
        )

    @classmethod
    def _format_bundle_cycles(cls, cycles: tuple[BundleCycle, ...]) -> tuple[str, ...]:
        return tuple(
            "- " + " -> ".join((*cycle.bundles, cycle.bundles[0]))
            for cycle in sorted(cycles, key=lambda item: item.bundles)
        )

    @classmethod
    def _bundle_nodes_from_payload(
        cls,
        registrations: tuple[RegistrationInfo, ...],
        edges: tuple[BundleEdge, ...],
        violations: tuple[BundleViolation, ...],
    ) -> tuple[str | None, ...]:
        bundles = {item.bundle for item in registrations if item.bundle is not None}
        for edge in edges:
            if edge.source_bundle is not None:
                bundles.add(edge.source_bundle)
            if edge.target_bundle is not None:
                bundles.add(edge.target_bundle)
        for violation in violations:
            if violation.source_bundle is not None:
                bundles.add(violation.source_bundle)
            if violation.target_bundle is not None:
                bundles.add(violation.target_bundle)
        if any(edge.source_bundle is None or edge.target_bundle is None for edge in edges) or any(
            violation.source_bundle is None or violation.target_bundle is None for violation in violations
        ):
            bundles.add(None)
        return tuple(sorted(bundles, key=repr))

    @classmethod
    def _group_mermaid_edges(
        cls,
        edges: tuple[BundleEdge, ...],
    ) -> tuple[tuple[str | None, str | None, tuple[str, ...]], ...]:
        grouped: dict[tuple[str | None, str | None], set[str]] = {}
        for edge in edges:
            grouped.setdefault((edge.source_bundle, edge.target_bundle), set()).add(describe_key(edge.key))
        return tuple(
            (
                source_bundle,
                target_bundle,
                tuple(sorted(keys)),
            )
            for (source_bundle, target_bundle), keys in sorted(grouped.items(), key=lambda item: (repr(item[0][0]), repr(item[0][1])))
        )

    @classmethod
    def _group_mermaid_violations(
        cls,
        violations: tuple[BundleViolation, ...],
    ) -> tuple[tuple[str | None, str | None, str, tuple[str, ...]], ...]:
        grouped: dict[tuple[str | None, str | None, str], set[str]] = {}
        for violation in violations:
            grouped.setdefault(
                (violation.source_bundle, violation.target_bundle, violation.reason),
                set(),
            ).add(describe_key(violation.key))
        return tuple(
            (
                source_bundle,
                target_bundle,
                reason,
                tuple(sorted(keys)),
            )
            for (source_bundle, target_bundle, reason), keys in sorted(
                grouped.items(),
                key=lambda item: (repr(item[0][0]), repr(item[0][1]), item[0][2]),
            )
        )

    @staticmethod
    def _mermaid_label(text: str) -> str:
        return text.replace('"', '\\"').replace("\n", "<br/>")

    @classmethod
    def _edge_record(cls, edge: BundleEdge) -> BundleGraphEdgeRecord:
        return BundleGraphEdgeRecord(
            source_bundle=edge.source_bundle,
            target_bundle=edge.target_bundle,
            key=describe_key(edge.key),
        )

    @classmethod
    def _violation_record(cls, violation: BundleViolation) -> BundleGraphViolationRecord:
        return BundleGraphViolationRecord(
            source_bundle=violation.source_bundle,
            target_bundle=violation.target_bundle,
            key=describe_key(violation.key),
            reason=violation.reason,
        )

    @staticmethod
    def _coerce_optional_bundle(value: Any, *, field: str) -> str | None:
        if value is None or isinstance(value, str):
            return value
        raise ValueError(f"Bundle graph baseline field {field!r} must be a string or null")

    @classmethod
    def _coerce_graph_payload(cls, baseline: "DoctorReport | Mapping[str, Any] | str") -> Mapping[str, Any]:
        if isinstance(baseline, DoctorReport):
            return baseline.bundle_graph_dict()
        if isinstance(baseline, str):
            try:
                payload = json.loads(baseline)
            except json.JSONDecodeError as exc:
                raise ValueError("Bundle graph baseline JSON is invalid") from exc
            if not isinstance(payload, Mapping):
                raise ValueError("Bundle graph baseline JSON must decode to an object")
            return payload
        if isinstance(baseline, Mapping):
            return baseline
        raise TypeError("Bundle graph baseline must be a DoctorReport, mapping, or JSON string")

    @classmethod
    def _coerce_baseline_nodes(cls, payload: Mapping[str, Any]) -> tuple[str | None, ...]:
        raw_nodes = payload.get("nodes", ())
        if not isinstance(raw_nodes, list):
            raise ValueError("Bundle graph baseline field 'nodes' must be a list")
        nodes: set[str | None] = set()
        for index, item in enumerate(raw_nodes):
            if not isinstance(item, Mapping):
                raise ValueError(f"Bundle graph baseline node {index} must be an object")
            if "bundle" not in item:
                raise ValueError(f"Bundle graph baseline node {index} must define 'bundle'")
            nodes.add(cls._coerce_optional_bundle(item["bundle"], field="bundle"))
        return tuple(sorted(nodes, key=repr))

    @classmethod
    def _coerce_baseline_edges(cls, payload: Mapping[str, Any]) -> tuple[BundleGraphEdgeRecord, ...]:
        raw_edges = payload.get("edges", ())
        if not isinstance(raw_edges, list):
            raise ValueError("Bundle graph baseline field 'edges' must be a list")
        edges: set[BundleGraphEdgeRecord] = set()
        for index, item in enumerate(raw_edges):
            if not isinstance(item, Mapping):
                raise ValueError(f"Bundle graph baseline edge {index} must be an object")
            key = item.get("key")
            if not isinstance(key, str):
                raise ValueError(f"Bundle graph baseline edge {index} must define string field 'key'")
            edges.add(
                BundleGraphEdgeRecord(
                    source_bundle=cls._coerce_optional_bundle(item.get("source"), field="source"),
                    target_bundle=cls._coerce_optional_bundle(item.get("target"), field="target"),
                    key=key,
                )
            )
        return tuple(
            sorted(edges, key=lambda item: (repr(item.source_bundle), repr(item.target_bundle), item.key))
        )

    @classmethod
    def _coerce_baseline_violations(
        cls,
        payload: Mapping[str, Any],
    ) -> tuple[BundleGraphViolationRecord, ...]:
        raw_violations = payload.get("violations", ())
        if not isinstance(raw_violations, list):
            raise ValueError("Bundle graph baseline field 'violations' must be a list")
        violations: set[BundleGraphViolationRecord] = set()
        for index, item in enumerate(raw_violations):
            if not isinstance(item, Mapping):
                raise ValueError(f"Bundle graph baseline violation {index} must be an object")
            key = item.get("key")
            reason = item.get("reason")
            if not isinstance(key, str):
                raise ValueError(
                    f"Bundle graph baseline violation {index} must define string field 'key'"
                )
            if not isinstance(reason, str):
                raise ValueError(
                    f"Bundle graph baseline violation {index} must define string field 'reason'"
                )
            violations.add(
                BundleGraphViolationRecord(
                    source_bundle=cls._coerce_optional_bundle(item.get("source"), field="source"),
                    target_bundle=cls._coerce_optional_bundle(item.get("target"), field="target"),
                    key=key,
                    reason=reason,
                )
            )
        return tuple(
            sorted(
                violations,
                key=lambda item: (
                    repr(item.source_bundle),
                    repr(item.target_bundle),
                    item.key,
                    item.reason,
                ),
            )
        )

    def bundle_graph_dict(self) -> dict[str, Any]:
        nodes = self._bundle_nodes_from_payload(self.registrations, self.bundle_edges, self.bundle_violations)
        return {
            "ok": self.ok,
            "roots": [describe_key(key) for key in self.roots],
            "errors": list(self.errors),
            "error_codes": list(self.error_codes),
            "nodes": [
                {
                    "bundle": bundle,
                    "label": self._bundle_label(bundle),
                }
                for bundle in nodes
            ],
            "edges": [
                {
                    "source": edge.source_bundle,
                    "target": edge.target_bundle,
                    "key": describe_key(edge.key),
                }
                for edge in self.bundle_edges
            ],
            "violations": [
                {
                    "source": violation.source_bundle,
                    "target": violation.target_bundle,
                    "key": describe_key(violation.key),
                    "reason": violation.reason,
                }
                for violation in self.bundle_violations
            ],
            "cycles": [
                {
                    "bundles": list(cycle.bundles),
                    "path": " -> ".join((*cycle.bundles, cycle.bundles[0])),
                }
                for cycle in self.bundle_cycles
            ],
        }

    def bundle_graph_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.bundle_graph_dict(), indent=indent, sort_keys=True)

    def diff_bundle_graph(self, baseline: "DoctorReport | Mapping[str, Any] | str") -> BundleGraphDiff:
        baseline_payload = self._coerce_graph_payload(baseline)
        baseline_nodes = set(self._coerce_baseline_nodes(baseline_payload))
        baseline_edges = set(self._coerce_baseline_edges(baseline_payload))
        baseline_violations = set(self._coerce_baseline_violations(baseline_payload))

        current_nodes = set(self._bundle_nodes_from_payload(self.registrations, self.bundle_edges, self.bundle_violations))
        current_edges = {self._edge_record(edge) for edge in self.bundle_edges}
        current_violations = {self._violation_record(violation) for violation in self.bundle_violations}

        return BundleGraphDiff(
            added_nodes=tuple(sorted(current_nodes - baseline_nodes, key=repr)),
            removed_nodes=tuple(sorted(baseline_nodes - current_nodes, key=repr)),
            added_edges=tuple(
                sorted(
                    current_edges - baseline_edges,
                    key=lambda item: (repr(item.source_bundle), repr(item.target_bundle), item.key),
                )
            ),
            removed_edges=tuple(
                sorted(
                    baseline_edges - current_edges,
                    key=lambda item: (repr(item.source_bundle), repr(item.target_bundle), item.key),
                )
            ),
            added_violations=tuple(
                sorted(
                    current_violations - baseline_violations,
                    key=lambda item: (
                        repr(item.source_bundle),
                        repr(item.target_bundle),
                        item.key,
                        item.reason,
                    ),
                )
            ),
            removed_violations=tuple(
                sorted(
                    baseline_violations - current_violations,
                    key=lambda item: (
                        repr(item.source_bundle),
                        repr(item.target_bundle),
                        item.key,
                        item.reason,
                    ),
                )
            ),
        )

    def bundle_graph_mermaid(self) -> str:
        nodes = self._bundle_nodes_from_payload(self.registrations, self.bundle_edges, self.bundle_violations)
        node_ids = {bundle: f"bundle_{index}" for index, bundle in enumerate(nodes)}
        lines = ["flowchart LR"]
        for bundle in nodes:
            node_id = node_ids[bundle]
            label = self._mermaid_label(self._bundle_label(bundle))
            lines.append(f'    {node_id}["{label}"]')
        for source_bundle, target_bundle, keys in self._group_mermaid_edges(self.bundle_edges):
            source_id = node_ids[source_bundle]
            target_id = node_ids[target_bundle]
            label = self._mermaid_label(", ".join(keys))
            lines.append(f'    {source_id} -->|"{label}"| {target_id}')
        for source_bundle, target_bundle, reason, keys in self._group_mermaid_violations(self.bundle_violations):
            source_id = node_ids[source_bundle]
            target_id = node_ids[target_bundle]
            label = self._mermaid_label(f"violation: {reason}<br/>{', '.join(keys)}")
            lines.append(f'    {source_id} -. "{label}" .-> {target_id}')
        for cycle in self.bundle_cycles:
            lines.append(f"    %% bundle cycle: {' -> '.join((*cycle.bundles, cycle.bundles[0]))}")
        return "\n".join(lines)

    def format(self) -> str:
        lines = [
            "dixp doctor",
            f"status: {'ok' if self.ok else 'failed'}",
            f"services: {len(self.registrations)}",
        ]
        if self.roots:
            lines.append("roots: " + ", ".join(describe_key(key) for key in self.roots))
        if self.notes:
            lines.append("notes:")
            lines.extend(f"- {note}" for note in self.notes)
        if self.bundle_edges:
            lines.append("bundle graph:")
            lines.extend(self._format_bundle_graph(self.bundle_edges))
        if self.bundle_violations:
            lines.append("bundle violations:")
            lines.extend(self._format_bundle_violations(self.bundle_violations))
        if self.bundle_cycles:
            lines.append("bundle cycles:")
            lines.extend(self._format_bundle_cycles(self.bundle_cycles))
        if self.errors:
            lines.append("errors:")
            lines.extend(f"- {error}" for error in self.errors)
        if self.error_codes:
            lines.append("error codes:")
            lines.extend(f"- {code}" for code in self.error_codes)
        return "\n".join(lines)

    def __str__(self) -> str:
        return self.format()

    def __bool__(self) -> bool:
        return self.ok


class GraphInspector(InspectorPort):
    def __init__(self, registry: RegistryPort) -> None:
        self._registry = registry

    def _bundle_label(self, bundle: str | None) -> str:
        return bundle or "<app>"

    def _surface_key(self, key: ServiceKey) -> ServiceKey:
        collection = collection_spec(key)
        if collection is None:
            return key
        _, item_key = collection
        return item_key

    def _bundle_suffix(self, registration: Registration) -> str:
        if registration.bundle is None:
            return ""
        contract = self._registry.bundle_contract(registration.bundle)
        if contract is None:
            return f" {{bundle: {registration.bundle}}}"
        parts = [f"bundle: {registration.bundle}"]
        if contract.layer is not None:
            parts.append(f"layer: {contract.layer}")
        if contract.tags:
            parts.append(f"tags: {', '.join(contract.tags)}")
        return " {" + "; ".join(parts) + "}"

    @staticmethod
    def _join_labels(values: tuple[str, ...]) -> str:
        return ", ".join(values) or "<none>"

    def _source_lines(self, registration: Registration, prefix: str) -> tuple[str, ...]:
        lines: list[str] = []
        if registration.source is not None:
            lines.append(f"{prefix}source: {registration.source}")
        if registration.source_location is not None:
            lines.append(f"{prefix}defined at: {registration.source_location}")
        return tuple(lines)

    def _bundle_edge_violation(
        self,
        source: Registration,
        target: Registration,
        *,
        surface_key: ServiceKey,
    ) -> tuple[str, dict[str, Any]] | None:
        if source.bundle == target.bundle:
            return None
        source_contract = self._registry.bundle_contract(source.bundle) if source.bundle is not None else None
        target_contract = self._registry.bundle_contract(target.bundle) if target.bundle is not None else None
        source_tags = source_contract.tags if source_contract is not None else ()
        target_tags = target_contract.tags if target_contract is not None else ()
        source_layer = source_contract.layer if source_contract is not None else None
        target_layer = target_contract.layer if target_contract is not None else None
        detail_key = describe_key(surface_key)

        def details(reason: str, **extra: Any) -> dict[str, Any]:
            return {
                "reason": reason,
                "source_bundle": source.bundle,
                "target_bundle": target.bundle,
                "key": detail_key,
                **extra,
            }

        if source_contract is not None and target.bundle is not None and target.bundle in source_contract.forbid_outgoing_to:
            return ("forbidden by source bundle policy", details("forbidden by source bundle policy"))

        if (
            source_contract is not None
            and target_layer is not None
            and target_layer in source_contract.forbid_outgoing_to_layers
        ):
            return (
                f"target layer is in forbid_outgoing_to_layers({self._join_labels(source_contract.forbid_outgoing_to_layers)})",
                details(
                    "target layer is in forbid_outgoing_to_layers",
                    target_layer=target_layer,
                    forbidden=source_contract.forbid_outgoing_to_layers,
                ),
            )

        if source_contract is not None and source_contract.forbid_outgoing_to_tags:
            matched_tags = tuple(tag for tag in source_contract.forbid_outgoing_to_tags if tag in target_tags)
            if matched_tags:
                return (
                    f"target bundle matches forbidden tags({self._join_labels(source_contract.forbid_outgoing_to_tags)})",
                    details(
                        "target bundle matches forbidden tags",
                        forbidden=source_contract.forbid_outgoing_to_tags,
                        matched=matched_tags,
                    ),
                )

        if target_contract is not None and target_contract.allow_incoming_from is not None:
            if source.bundle not in target_contract.allow_incoming_from:
                return (
                    f"source bundle is not in allow_incoming_from({', '.join(target_contract.allow_incoming_from) or '<none>'})",
                    details(
                        "source bundle is not in allow_incoming_from",
                        allowed=target_contract.allow_incoming_from,
                    ),
                )

        if target_contract is not None and target_contract.allow_incoming_from_layers is not None:
            if source_layer not in target_contract.allow_incoming_from_layers:
                return (
                    f"source layer is not in allow_incoming_from_layers({self._join_labels(target_contract.allow_incoming_from_layers)})",
                    details(
                        "source layer is not in allow_incoming_from_layers",
                        source_layer=source_layer or "<none>",
                        allowed=target_contract.allow_incoming_from_layers,
                    ),
                )

        if target_contract is not None and target_contract.allow_incoming_from_tags is not None:
            matched_tags = tuple(tag for tag in source_tags if tag in target_contract.allow_incoming_from_tags)
            if not matched_tags:
                return (
                    f"source tags do not match allow_incoming_from_tags({self._join_labels(target_contract.allow_incoming_from_tags)})",
                    details(
                        "source tags do not match allow_incoming_from_tags",
                        source_tags=source_tags,
                        allowed=target_contract.allow_incoming_from_tags,
                    ),
                )

        if target_contract is not None:
            if surface_key in target_contract.private:
                return (
                    "targets private service",
                    details("targets private service"),
                )
            if target_contract.exports is not None and surface_key not in target_contract.exports:
                return (
                    "targets non-exported service",
                    details("targets non-exported service"),
                )

        if source_contract is not None and source_contract.requires is not None and surface_key not in source_contract.requires:
            return (
                "missing requires(...) declaration",
                details("missing requires(...) declaration"),
            )
        return None

    def _walk_bundle_edge(
        self,
        source: Registration,
        target: Registration,
        *,
        requested_key: ServiceKey,
        edges: list[BundleEdge] | None = None,
        edge_markers: set[tuple[str | None, str | None, ServiceKey]] | None = None,
        violations: list[BundleViolation] | None = None,
        violation_markers: set[tuple[str | None, str | None, ServiceKey, str]] | None = None,
    ) -> None:
        if source.bundle == target.bundle:
            return
        surface_key = self._surface_key(requested_key)
        if edges is not None and edge_markers is not None:
            edge_marker = (source.bundle, target.bundle, surface_key)
            if edge_marker not in edge_markers:
                edge_markers.add(edge_marker)
                edges.append(BundleEdge(source.bundle, target.bundle, surface_key))
        violation = self._bundle_edge_violation(source, target, surface_key=surface_key)
        if violation is None:
            return
        reason, details = violation
        if violations is not None and violation_markers is not None:
            violation_marker = (source.bundle, target.bundle, surface_key, reason)
            if violation_marker not in violation_markers:
                violation_markers.add(violation_marker)
                violations.append(BundleViolation(source.bundle, target.bundle, surface_key, reason))
        raise BundleContractValidationError(details=details)

    def _representative_bundle_cycle(
        self,
        component: tuple[str, ...],
        adjacency: Mapping[str, tuple[str, ...]],
    ) -> BundleCycle:
        component_set = set(component)
        start = min(component)

        def walk(current: str, path: tuple[str, ...], seen: set[str]) -> tuple[str, ...] | None:
            for candidate in adjacency.get(current, ()):
                if candidate not in component_set:
                    continue
                if candidate == start and len(path) > 1:
                    return path
                if candidate in seen:
                    continue
                found = walk(candidate, path + (candidate,), seen | {candidate})
                if found is not None:
                    return found
            return None

        found = walk(start, (start,), {start})
        if found is not None:
            return BundleCycle(found)
        return BundleCycle(tuple(sorted(component)))

    def _bundle_cycles(self, edges: tuple[BundleEdge, ...]) -> tuple[BundleCycle, ...]:
        adjacency_sets: dict[str, set[str]] = {}
        for edge in edges:
            if edge.source_bundle is None or edge.target_bundle is None:
                continue
            if edge.source_bundle == edge.target_bundle:
                continue
            adjacency_sets.setdefault(edge.source_bundle, set()).add(edge.target_bundle)
            adjacency_sets.setdefault(edge.target_bundle, set())
        if not adjacency_sets:
            return ()

        adjacency = {
            bundle: tuple(sorted(targets))
            for bundle, targets in sorted(adjacency_sets.items(), key=lambda item: item[0])
        }

        index = 0
        stack: list[str] = []
        on_stack: set[str] = set()
        indices: dict[str, int] = {}
        lowlinks: dict[str, int] = {}
        cycles: list[BundleCycle] = []

        def strongconnect(bundle: str) -> None:
            nonlocal index
            indices[bundle] = index
            lowlinks[bundle] = index
            index += 1
            stack.append(bundle)
            on_stack.add(bundle)

            for target in adjacency.get(bundle, ()):
                if target not in indices:
                    strongconnect(target)
                    lowlinks[bundle] = min(lowlinks[bundle], lowlinks[target])
                elif target in on_stack:
                    lowlinks[bundle] = min(lowlinks[bundle], indices[target])

            if lowlinks[bundle] != indices[bundle]:
                return

            component: list[str] = []
            while stack:
                target = stack.pop()
                on_stack.remove(target)
                component.append(target)
                if target == bundle:
                    break
            if len(component) > 1:
                cycles.append(self._representative_bundle_cycle(tuple(sorted(component)), adjacency))

        for bundle in adjacency:
            if bundle not in indices:
                strongconnect(bundle)
        return tuple(sorted(cycles, key=lambda item: item.bundles))

    def _analyze_graph(
        self,
        *roots: ServiceKey,
    ) -> tuple[tuple[DiagnosticIssue, ...], tuple[BundleEdge, ...], tuple[BundleViolation, ...], tuple[BundleCycle, ...]]:
        targets = tuple(dict.fromkeys(roots)) if roots else self._registry.root_keys()
        issues: list[DiagnosticIssue] = []
        edges: list[BundleEdge] = []
        violations: list[BundleViolation] = []
        cycles: tuple[BundleCycle, ...] = ()
        edge_markers: set[tuple[str | None, str | None, ServiceKey]] = set()
        violation_markers: set[tuple[str | None, str | None, ServiceKey, str]] = set()
        seen_issues: set[tuple[str, str]] = set()

        def add_issue(code: str, message: str) -> None:
            marker = (code, message)
            if marker not in seen_issues:
                seen_issues.add(marker)
                issues.append(DiagnosticIssue(code=code, message=message))

        def validate_key(key: ServiceKey, context: ResolutionContext, *, source: Registration | None = None) -> None:
            try:
                request = request_wrapper_spec(key)
                if request is not None:
                    validate_key(
                        request.key,
                        context.enter(key, Lifetime.TRANSIENT, display=describe_key(key)),
                        source=source,
                    )
                    return
                collection = collection_spec(key)
                if collection is not None:
                    _, item_key = collection
                    nested_context = context.enter(key, Lifetime.TRANSIENT)
                    for registration in self._registry.registrations_for_collection(
                        item_key,
                        suppress_autowire_errors=False,
                    ):
                        if source is not None:
                            self._walk_bundle_edge(
                                source,
                                registration,
                                requested_key=key,
                                edges=edges,
                                edge_markers=edge_markers,
                                violations=violations,
                                violation_markers=violation_markers,
                            )
                        contributor_context = nested_context.enter(
                            registration.graph_key,
                            registration.lifetime,
                            display=registration.display,
                        )
                        for dependency in registration.dependencies:
                            if dependency.has_default and not self._registry.can_resolve(dependency.key):
                                continue
                            validate_key(dependency.key, contributor_context, source=registration)
                    return

                registration = self._registry.registration_for(key, suppress_autowire_errors=False)
                if registration is None:
                    registrations = self._registry.registrations_for_collection(key, suppress_autowire_errors=False)
                    if registrations:
                        nested_context = context.enter(key, Lifetime.TRANSIENT, display=f"{describe_key(key)}[]")
                        for item_registration in registrations:
                            if source is not None:
                                self._walk_bundle_edge(
                                    source,
                                    item_registration,
                                    requested_key=key,
                                    edges=edges,
                                    edge_markers=edge_markers,
                                    violations=violations,
                                    violation_markers=violation_markers,
                                )
                            contributor_context = nested_context.enter(
                                item_registration.graph_key,
                                item_registration.lifetime,
                                display=item_registration.display,
                            )
                            for dependency in item_registration.dependencies:
                                if dependency.has_default and not self._registry.can_resolve(dependency.key):
                                    continue
                                validate_key(dependency.key, contributor_context, source=item_registration)
                        return
                    if context.frames:
                        path = format_path(context.frames, tail=key)
                        raise MissingRegistrationValidationError(details={"key": describe_key(key), "path": path})
                    raise MissingRegistrationValidationError(details={"key": describe_key(key)})
                if source is not None:
                    self._walk_bundle_edge(
                        source,
                        registration,
                        requested_key=key,
                        edges=edges,
                        edge_markers=edge_markers,
                        violations=violations,
                        violation_markers=violation_markers,
                    )
                nested_context = context.enter(
                    registration.graph_key,
                    registration.lifetime,
                    display=registration.display,
                )
                for dependency in registration.dependencies:
                    if dependency.has_default and not self._registry.can_resolve(dependency.key):
                        continue
                    validate_key(dependency.key, nested_context, source=registration)
            except (ResolutionError, ValidationError) as exc:
                add_issue(getattr(exc, "code", "validation_error"), str(exc))

        for key in targets:
            validate_key(key, ResolutionContext())

        cycles = self._bundle_cycles(tuple(edges))
        for cycle in cycles:
            message = format_error_message("bundle_cycle", {"bundles": cycle.bundles})
            add_issue("bundle_cycle", message)

        return tuple(issues), tuple(edges), tuple(violations), cycles

    def validate(self, *roots: ServiceKey) -> None:
        issues, _, _, _ = self._analyze_graph(*roots)
        if issues:
            raise GraphValidationError(
                details={
                    "errors": tuple(issue.message for issue in issues),
                    "error_codes": tuple(issue.code for issue in issues),
                },
            )

    def explain(self, key: ServiceKey) -> str:
        lines: list[str] = []

        def line(prefix: str, text: str) -> None:
            lines.append(f"{prefix}{text}")

        def walk(service_key: ServiceKey, prefix: str, path: tuple[ServiceKey, ...]) -> None:
            request = request_wrapper_spec(service_key)
            if request is not None:
                line(prefix, f"{describe_key(service_key)}")
                walk(request.key, prefix + "  ", path)
                return
            collection = collection_spec(service_key)
            if collection is not None:
                _, item_key = collection
                line(prefix, f"{describe_key(service_key)}")
                registrations = self._registry.registrations_for_collection(item_key, suppress_autowire_errors=False)
                if not registrations:
                    line(prefix + "  ", "<empty>")
                    return
                for registration in registrations:
                    walk_registration(registration, prefix + "  ", path)
                return

            registration = self._registry.registration_for(service_key, suppress_autowire_errors=False)
            if registration is None:
                line(prefix, f"{describe_key(service_key)} [missing]")
                return
            walk_registration(registration, prefix, path)

        def walk_registration(registration: Registration, prefix: str, path: tuple[ServiceKey, ...]) -> None:
            line(
                prefix,
                f"{registration.display} [{registration.lifetime.value}]{self._bundle_suffix(registration)}",
            )
            lines.extend(self._source_lines(registration, prefix + "  "))
            if registration.activation_hooks:
                line(prefix + "  ", f"activations: {', '.join(registration.activation_hooks)}")
            if registration.interceptors:
                line(prefix + "  ", f"interceptors: {', '.join(registration.interceptors)}")
            if registration.graph_key in path:
                line(prefix + "  ", "<cycle>")
                return
            next_path = path + (registration.graph_key,)
            if not registration.dependencies:
                line(prefix + "  ", "<leaf>")
                return
            for dependency in registration.dependencies:
                marker = "optional " if dependency.has_default else ""
                line(prefix + "  ", f"{marker}{describe_key(dependency.key)}")
                walk(dependency.key, prefix + "    ", next_path)

        walk(key, "", ())
        return "\n".join(lines)

    def doctor(self, *roots: ServiceKey) -> DoctorReport:
        registrations = self._registry.catalog(include_dynamic=False)
        notes: list[str] = []
        errors: tuple[str, ...] = ()
        error_codes: tuple[str, ...] = ()
        bundle_edges: tuple[BundleEdge, ...] = ()
        bundle_violations: tuple[BundleViolation, ...] = ()
        bundle_cycles: tuple[BundleCycle, ...] = ()

        singles = sum(1 for item in registrations if item.kind == "single")
        multis = sum(1 for item in registrations if item.kind == "multi")
        generics = sum(1 for item in registrations if item.kind == "open_generic")
        bundles = sorted({item.bundle for item in registrations if item.bundle is not None})
        guarded = sorted(
            {
                bundle
                for bundle in bundles
                if (
                    (contract := self._registry.bundle_contract(bundle)) is not None
                    and (
                        contract.forbid_outgoing_to
                        or contract.allow_incoming_from is not None
                        or contract.forbid_outgoing_to_layers
                        or contract.allow_incoming_from_layers is not None
                        or contract.forbid_outgoing_to_tags
                        or contract.allow_incoming_from_tags is not None
                    )
                )
            }
        )

        if registrations:
            notes.append(f"{singles} single, {multis} multi, {generics} generic registrations")
        else:
            notes.append("no explicit registrations yet; runtime resolution will rely on autowiring only")
        if bundles:
            notes.append(f"{len(bundles)} named bundles in the graph")
        if guarded:
            notes.append(f"{len(guarded)} bundles have incoming/outgoing dependency policies")

        issues, bundle_edges, bundle_violations, bundle_cycles = self._analyze_graph(*roots)
        errors = tuple(issue.message for issue in issues)
        error_codes = tuple(dict.fromkeys(issue.code for issue in issues))
        if not issues:
            notes.append("graph validation passed")
            if bundles:
                notes.append("bundle contract validation passed")
            ok = True
        else:
            ok = False

        if roots:
            notes.append("focused validation on selected roots")
        elif registrations:
            notes.append("validated all registered roots")

        return DoctorReport(
            ok=ok,
            roots=tuple(dict.fromkeys(roots)),
            registrations=registrations,
            errors=errors,
            error_codes=error_codes,
            notes=tuple(notes),
            bundle_edges=bundle_edges,
            bundle_violations=bundle_violations,
            bundle_cycles=bundle_cycles,
        )
