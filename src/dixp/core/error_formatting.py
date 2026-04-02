from __future__ import annotations

from typing import Any, Callable, Mapping


def _text(value: Any, default: str = "<unknown>") -> str:
    if value is None:
        return default
    return str(value)


def _labels(value: Any) -> str:
    if value is None:
        return "<none>"
    if isinstance(value, str):
        return value or "<none>"
    if isinstance(value, (tuple, list, set, frozenset)):
        labels = [str(item) for item in value]
        return ", ".join(labels) or "<none>"
    return str(value)


def _lines(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (tuple, list, set, frozenset)):
        return tuple(str(item) for item in value)
    return (str(value),)


def _bundle_label(bundle: Any) -> str:
    return "<app>" if bundle is None else str(bundle)


def _format_no_active_resolver(details: Mapping[str, Any]) -> str:
    hint = _text(
        details.get("hint"),
        "Use `with container.activate(...):` or `with scope.activate():`.",
    )
    return f"No active dixp resolver. {hint}"


def _format_unsupported_composition_entry(details: Mapping[str, Any]) -> str:
    return f"Unsupported composition entry: {_text(details.get('entry'))}"


def _format_conflicting_bundle_contract(details: Mapping[str, Any]) -> str:
    return f"Conflicting contract metadata for bundle {_text(details.get('bundle'))}"


def _format_missing_factory_return_type(details: Mapping[str, Any]) -> str:
    return (
        "Factory registration without a key needs a return type hint. "
        "Add `-> ServiceType` to the factory or bind it explicitly with "
        "`app.bind(ServiceType).factory(...)`."
    )


def _format_invalid_factory_return_key(details: Mapping[str, Any]) -> str:
    return (
        "Factory return annotation is not a valid service key. "
        "Use a concrete type, protocol, or named key."
    )


def _format_missing_service_key_or_target(details: Mapping[str, Any]) -> str:
    return "Registration requires a service key or an inferable target"


def _format_typed_service_key_required(details: Mapping[str, Any]) -> str:
    return (
        "Safe mode requires typed service keys. "
        "Use a class/protocol key, `named(Type, 'name')`, or a dedicated token object."
    )


def _format_duplicate_registration(details: Mapping[str, Any]) -> str:
    return f"Duplicate registration for {_text(details.get('key'))}"


def _format_multiple_binding_sources(details: Mapping[str, Any]) -> str:
    return "Choose only one of implementation, factory, or instance"


def _format_missing_binding_target(details: Mapping[str, Any]) -> str:
    key = _text(details.get("key"))
    return (
        f"Registration for {key} needs an implementation, factory, or instance. "
        f"Try `app.bind({key}).to(...)`, `.factory(...)`, or `.instance(...)`."
    )


def _format_incompatible_implementation(details: Mapping[str, Any]) -> str:
    implementation = _text(details.get("implementation"))
    key = _text(details.get("key"))
    return (
        f"{implementation} is not compatible with service {key}. "
        "Bind an implementation that matches the requested interface or change the service key."
    )


def _format_factory_return_mismatch(details: Mapping[str, Any]) -> str:
    factory = _text(details.get("factory"))
    returned = _text(details.get("returned"))
    key = _text(details.get("key"))
    return (
        f"Factory {factory} returns {returned}, expected {key}. "
        "Either fix the return annotation or bind the factory under the returned service key."
    )


def _format_open_generic_missing_parameters(details: Mapping[str, Any]) -> str:
    return f"Open generic service {_text(details.get('key'))} must declare type parameters"


def _format_open_generic_parameters_mismatch(details: Mapping[str, Any]) -> str:
    implementation = _text(details.get("implementation"))
    key = _text(details.get("key"))
    return f"Open generic {implementation} must declare the same type parameters as {key}"


def _format_open_generic_missing_parts(details: Mapping[str, Any]) -> str:
    return "Open generic binding requires key and implementation"


def _format_duplicate_open_generic_registration(details: Mapping[str, Any]) -> str:
    return f"Duplicate open generic registration for {_text(details.get('key'))}"


def _format_env_binding_requires_settings_type(details: Mapping[str, Any]) -> str:
    return (
        f"Env-backed binding for {_text(details.get('key'))} requires an explicit dataclass settings_type. "
        "Use App.env(key, SettingsType, ...) or bind(key).env(SettingsType, ...)."
    )


def _format_invalid_env_bool(details: Mapping[str, Any]) -> str:
    return (
        f"Environment variable {_text(details.get('env_name'))} for field {_text(details.get('field_name'))} "
        f"must be one of: {_text(details.get('allowed'))}"
    )


def _format_invalid_env_int(details: Mapping[str, Any]) -> str:
    return (
        f"Environment variable {_text(details.get('env_name'))} for field {_text(details.get('field_name'))} "
        "must be an integer"
    )


def _format_invalid_env_float(details: Mapping[str, Any]) -> str:
    return (
        f"Environment variable {_text(details.get('env_name'))} for field {_text(details.get('field_name'))} "
        "must be a float"
    )


def _format_invalid_env_enum(details: Mapping[str, Any]) -> str:
    return (
        f"Environment variable {_text(details.get('env_name'))} for field {_text(details.get('field_name'))} "
        f"must match enum {_text(details.get('enum_name'))} by name or value. "
        f"Allowed names: {_text(details.get('allowed'))}"
    )


def _format_unsupported_env_type(details: Mapping[str, Any]) -> str:
    return (
        f"Unsupported env config type for field {_text(details.get('field_name'))}: "
        f"{_text(details.get('annotation'))}. "
        "Use str/int/float/bool/Path/Enum/Optional/list/tuple or bind the value explicitly."
    )


def _format_invalid_env_settings_type(details: Mapping[str, Any]) -> str:
    return (
        f"from_env(...) requires a dataclass type, got {_text(details.get('settings_type'))}. "
        "Define settings as a dataclass or load the value yourself."
    )


def _format_missing_env_variable(details: Mapping[str, Any]) -> str:
    return (
        f"Missing environment variable for settings field {_text(details.get('field_name'))}. "
        f"Tried: {_text(details.get('candidates'))}"
    )


def _format_missing_registration(details: Mapping[str, Any]) -> str:
    key = _text(details.get("key"))
    suggestions = _lines(details.get("suggestions"))
    if suggestions:
        return f"No service for {key}. Try one of these fixes:\n- " + "\n- ".join(suggestions)
    path = details.get("path")
    if path is not None:
        return f"Missing registration for {key}: {path}"
    return f"Missing registration for {key}"


def _format_autowire_failure(details: Mapping[str, Any]) -> str | None:
    reason = details.get("reason")
    key = details.get("key")
    if reason is not None and key is not None:
        return f"Failed to autowire {key}: {reason}"
    if reason is not None:
        return str(reason)
    if key is not None:
        return f"Failed to autowire {key}"
    return None


def _format_open_generic_resolution(details: Mapping[str, Any]) -> str | None:
    key = details.get("key")
    if details.get("needs_closed_key") and key is not None:
        return f"Open generic resolution requires a closed generic key: {key}"
    reason = details.get("reason")
    if reason is not None and key is not None:
        return f"Failed to specialize open generic {key}: {reason}"
    if reason is not None:
        return str(reason)
    if key is not None:
        return f"Failed to specialize open generic {key}"
    return None


def _format_invocation_preparation(details: Mapping[str, Any]) -> str:
    description = _text(details.get("description"))
    reason = _text(details.get("reason"))
    return f"Failed to prepare {description}: {reason}"


def _format_invocation_signature(details: Mapping[str, Any]) -> str:
    description = _text(details.get("description"))
    reason = _text(details.get("reason"))
    return f"Failed to invoke {description}: {reason}"


def _format_async_api_required(details: Mapping[str, Any]) -> str:
    description = details.get("description")
    if description is not None:
        if details.get("operation") == "invoke":
            return f"{description} is async; use the async API"
        return f"{description} is async and cannot be resolved through the synchronous API"
    scope = details.get("scope")
    api = _text(details.get("api"), "the async API")
    if scope is not None:
        return f"Async {scope} provider requires {api}"
    return f"This provider requires {api}"


def _format_invalid_override(details: Mapping[str, Any]) -> str:
    key = _text(details.get("key"))
    return f"Override for {key} requires value, implementation, or factory"


def _format_circular_dependency(details: Mapping[str, Any]) -> str:
    return f"Circular dependency detected: {_text(details.get('path'))}"


def _format_lifetime_mismatch(details: Mapping[str, Any]) -> str:
    key = _text(details.get("key"))
    path = _text(details.get("path"))
    return f"Scoped dependency {key} cannot be captured by a singleton: {path}"


def _format_container_closed(details: Mapping[str, Any]) -> str:
    target = _text(details.get("target"), "container")
    if target in {"container", "scope"}:
        return f"{target.capitalize()} is closed"
    return f"{target} is closed"


def _format_graph_validation(details: Mapping[str, Any]) -> str:
    errors = _lines(details.get("errors"))
    if errors:
        return "Dependency graph validation failed:\n" + "\n".join(f"- {error}" for error in errors)
    return "Dependency graph validation failed"


def _format_bundle_contract_violation(details: Mapping[str, Any]) -> str | None:
    reason = details.get("reason")
    source = _bundle_label(details.get("source_bundle"))
    target = _bundle_label(details.get("target_bundle"))
    key = _text(details.get("key"))
    if reason == "forbidden by source bundle policy":
        return f"Bundle {source} forbids outgoing dependencies to bundle {target}"
    if reason == "target layer is in forbid_outgoing_to_layers":
        return (
            f"Bundle {source} forbids outgoing dependencies to layer "
            f"{_text(details.get('target_layer'))} but depends on bundle {target}"
        )
    if reason == "target bundle matches forbidden tags":
        forbidden = _labels(details.get("forbidden"))
        matched = _labels(details.get("matched"))
        return (
            f"Bundle {source} forbids outgoing dependencies to tags {forbidden} "
            f"and depends on bundle {target} with matching tags {matched}"
        )
    if reason == "source bundle is not in allow_incoming_from":
        allowed = _labels(details.get("allowed"))
        return (
            f"Bundle {source} is not allowed to depend on bundle {target}; "
            f"allowed incoming bundles: {allowed}"
        )
    if reason == "source layer is not in allow_incoming_from_layers":
        allowed = _labels(details.get("allowed"))
        source_layer = _text(details.get("source_layer"), "<none>")
        return (
            f"Bundle {source} has layer {source_layer} and is not allowed to depend on bundle "
            f"{target}; allowed incoming layers: {allowed}"
        )
    if reason == "source tags do not match allow_incoming_from_tags":
        allowed = _labels(details.get("allowed"))
        source_tags = _labels(details.get("source_tags"))
        return (
            f"Bundle {source} has tags {source_tags} and is not allowed to depend on bundle "
            f"{target}; allowed incoming tags: {allowed}"
        )
    if reason == "targets private service":
        return f"Bundle {source} depends on private service {key} from bundle {target}"
    if reason == "targets non-exported service":
        return f"Bundle {source} depends on non-exported service {key} from bundle {target}"
    if reason == "missing requires(...) declaration":
        return f"Bundle {source} depends on {key} from bundle {target} but does not declare it in requires(...)"
    return None


def _format_bundle_cycle(details: Mapping[str, Any]) -> str | None:
    bundles = details.get("bundles")
    if not isinstance(bundles, (tuple, list)) or not bundles:
        return None
    labels = tuple(str(bundle) for bundle in bundles)
    return f"Bundle dependency cycle detected: {' -> '.join((*labels, labels[0]))}"


_FORMATTERS: dict[str, Callable[[Mapping[str, Any]], str | None]] = {
    "no_active_resolver": _format_no_active_resolver,
    "unsupported_composition_entry": _format_unsupported_composition_entry,
    "conflicting_bundle_contract": _format_conflicting_bundle_contract,
    "missing_factory_return_type": _format_missing_factory_return_type,
    "invalid_factory_return_key": _format_invalid_factory_return_key,
    "missing_service_key_or_target": _format_missing_service_key_or_target,
    "typed_service_key_required": _format_typed_service_key_required,
    "duplicate_registration": _format_duplicate_registration,
    "multiple_binding_sources": _format_multiple_binding_sources,
    "missing_binding_target": _format_missing_binding_target,
    "incompatible_implementation": _format_incompatible_implementation,
    "factory_return_mismatch": _format_factory_return_mismatch,
    "open_generic_missing_parameters": _format_open_generic_missing_parameters,
    "open_generic_parameters_mismatch": _format_open_generic_parameters_mismatch,
    "open_generic_missing_parts": _format_open_generic_missing_parts,
    "duplicate_open_generic_registration": _format_duplicate_open_generic_registration,
    "env_binding_requires_settings_type": _format_env_binding_requires_settings_type,
    "invalid_env_bool": _format_invalid_env_bool,
    "invalid_env_int": _format_invalid_env_int,
    "invalid_env_float": _format_invalid_env_float,
    "invalid_env_enum": _format_invalid_env_enum,
    "unsupported_env_type": _format_unsupported_env_type,
    "invalid_env_settings_type": _format_invalid_env_settings_type,
    "missing_env_variable": _format_missing_env_variable,
    "missing_registration": _format_missing_registration,
    "autowire_failure": _format_autowire_failure,
    "open_generic_resolution": _format_open_generic_resolution,
    "invocation_preparation": _format_invocation_preparation,
    "invocation_signature": _format_invocation_signature,
    "async_api_required": _format_async_api_required,
    "invalid_override": _format_invalid_override,
    "circular_dependency": _format_circular_dependency,
    "lifetime_mismatch": _format_lifetime_mismatch,
    "container_closed": _format_container_closed,
    "graph_validation": _format_graph_validation,
    "bundle_contract_violation": _format_bundle_contract_violation,
    "bundle_cycle": _format_bundle_cycle,
}


def format_error_message(
    code: str,
    details: Mapping[str, Any] | None = None,
    *,
    fallback: str | None = None,
) -> str:
    payload = details or {}
    formatter = _FORMATTERS.get(code)
    if formatter is not None:
        message = formatter(payload)
        if message is not None:
            return message
    reason = payload.get("reason")
    if reason is not None:
        return str(reason)
    if fallback is not None:
        return fallback
    return code.replace("_", " ")
