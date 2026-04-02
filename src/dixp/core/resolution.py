from __future__ import annotations

from dataclasses import dataclass

from .errors import CircularDependencyError, LifetimeMismatchError
from .graph import describe_key
from .models import Lifetime, ServiceKey


def format_path(frames: tuple["ResolutionFrame", ...], tail: ServiceKey | None = None) -> str:
    keys = [frame.display for frame in frames]
    if tail is not None:
        keys.append(describe_key(tail))
    return " -> ".join(keys)


@dataclass(frozen=True, slots=True)
class ResolutionFrame:
    key: ServiceKey
    display: str
    lifetime: Lifetime


@dataclass(frozen=True, slots=True)
class ResolutionContext:
    frames: tuple[ResolutionFrame, ...] = ()

    def enter(self, key: ServiceKey, lifetime: Lifetime, *, display: str | None = None) -> "ResolutionContext":
        for frame in self.frames:
            if frame.key == key:
                path = format_path(self.frames, tail=display or key)
                raise CircularDependencyError(details={"path": path})
        if lifetime is Lifetime.SCOPED and any(frame.lifetime is Lifetime.SINGLETON for frame in self.frames):
            path = format_path(self.frames, tail=display or key)
            raise LifetimeMismatchError(details={"key": display or describe_key(key), "path": path})
        return ResolutionContext(
            self.frames
            + (
                ResolutionFrame(
                    key=key,
                    display=display or describe_key(key),
                    lifetime=lifetime,
                ),
            )
        )
