from __future__ import annotations

import os
import re
from dataclasses import MISSING, fields, is_dataclass
from enum import Enum
from pathlib import Path
from types import NoneType, UnionType
from typing import Annotated, Any, Mapping, TypeVar, Union, get_args, get_origin, get_type_hints

from .core.errors import RegistrationError

T = TypeVar("T")

_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


def _env_token(value: str) -> str:
    snake = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", snake).strip("_")
    return normalized.upper()


def _env_names(field_name: str, *, prefix: str, profile: str | None) -> tuple[str, ...]:
    token = _env_token(field_name)
    normalized_prefix = prefix or ""
    names: list[str] = []
    if profile is not None:
        names.append(f"{normalized_prefix}{_env_token(profile)}_{token}")
    names.append(f"{normalized_prefix}{token}")
    return tuple(names)


def _strip_annotated(annotation: Any) -> Any:
    if get_origin(annotation) is Annotated:
        base, *_ = get_args(annotation)
        return base
    return annotation


def _is_optional(annotation: Any) -> tuple[Any, bool]:
    origin = get_origin(annotation)
    if origin not in (Union, UnionType):
        return annotation, False
    args = [arg for arg in get_args(annotation) if arg is not NoneType]
    if len(args) == 1:
        return args[0], True
    return annotation, False


def _parse_bool(raw: str, *, field_name: str, env_name: str) -> bool:
    value = raw.strip().lower()
    if value in _TRUE_VALUES:
        return True
    if value in _FALSE_VALUES:
        return False
    raise RegistrationError(
        code="invalid_env_bool",
        details={
            "env_name": repr(env_name),
            "field_name": repr(field_name),
            "allowed": ", ".join(sorted(_TRUE_VALUES | _FALSE_VALUES)),
        },
    )


def _coerce_env_value(annotation: Any, raw: str, *, field_name: str, env_name: str) -> Any:
    annotation = _strip_annotated(annotation)
    annotation, optional = _is_optional(annotation)
    if optional and raw == "":
        return None

    origin = get_origin(annotation)
    if origin is list:
        (item_type,) = get_args(annotation) or (str,)
        if raw.strip() == "":
            return []
        return [
            _coerce_env_value(item_type, item.strip(), field_name=field_name, env_name=env_name)
            for item in raw.split(",")
        ]
    if origin is tuple:
        args = get_args(annotation)
        if len(args) == 2 and args[1] is Ellipsis:
            if raw.strip() == "":
                return ()
            return tuple(
                _coerce_env_value(args[0], item.strip(), field_name=field_name, env_name=env_name)
                for item in raw.split(",")
            )

    if annotation in (Any, str):
        return raw
    if annotation is bool:
        return _parse_bool(raw, field_name=field_name, env_name=env_name)
    if annotation is int:
        try:
            return int(raw)
        except ValueError as exc:
            raise RegistrationError(
                code="invalid_env_int",
                details={"env_name": repr(env_name), "field_name": repr(field_name)},
            ) from exc
    if annotation is float:
        try:
            return float(raw)
        except ValueError as exc:
            raise RegistrationError(
                code="invalid_env_float",
                details={"env_name": repr(env_name), "field_name": repr(field_name)},
            ) from exc
    if annotation is Path:
        return Path(raw)
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        try:
            return annotation[raw]
        except KeyError:
            try:
                return annotation(raw)
            except ValueError as exc:
                allowed = ", ".join(member.name for member in annotation)
                raise RegistrationError(
                    code="invalid_env_enum",
                    details={
                        "env_name": repr(env_name),
                        "field_name": repr(field_name),
                        "enum_name": annotation.__name__,
                        "allowed": allowed,
                    },
                ) from exc
    if annotation is NoneType:
        return None

    raise RegistrationError(
        code="unsupported_env_type",
        details={"field_name": repr(field_name), "annotation": repr(annotation)},
    )


def from_env(
    settings_type: type[T],
    *,
    prefix: str = "",
    profile: str | None = None,
    env: Mapping[str, str] | None = None,
) -> T:
    """Load a dataclass settings object from environment variables."""
    if not isinstance(settings_type, type) or not is_dataclass(settings_type):
        raise RegistrationError(code="invalid_env_settings_type", details={"settings_type": repr(settings_type)})

    source = os.environ if env is None else env
    hints = get_type_hints(settings_type, include_extras=True)
    kwargs: dict[str, Any] = {}

    for field in fields(settings_type):
        if not field.init:
            continue
        env_name = next((name for name in _env_names(field.name, prefix=prefix, profile=profile) if name in source), None)
        if env_name is None:
            if field.default is not MISSING or field.default_factory is not MISSING:
                continue
            raise RegistrationError(
                code="missing_env_variable",
                details={
                    "field_name": repr(field.name),
                    "candidates": ", ".join(_env_names(field.name, prefix=prefix, profile=profile)),
                },
            )
        kwargs[field.name] = _coerce_env_value(
            hints.get(field.name, field.type),
            source[env_name],
            field_name=field.name,
            env_name=env_name,
        )

    return settings_type(**kwargs)
