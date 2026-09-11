from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol

from understudy.artifact.models import Target


ResolutionStatus = Literal["primary", "degraded", "absent"]


@dataclass(frozen=True)
class ResolvedTarget:
    """The result of resolving one artifact target on a live surface."""

    target_ref: str
    status: ResolutionStatus
    strategy_id: str | None
    match_count: int
    handle: Any | None

    @property
    def degraded(self) -> bool:
        return self.status == "degraded"

    @property
    def present(self) -> bool:
        return self.status != "absent"


class TargetResolutionError(RuntimeError):
    """Raised when an actionable target cannot be resolved uniquely."""


class Surface(Protocol):
    def navigate(self, url: str) -> None: ...

    def resolve_target(
        self,
        target_ref: str,
        target: Target,
        values: dict[str, Any],
    ) -> ResolvedTarget: ...

    def is_visible(self, target: ResolvedTarget) -> bool: ...

    def is_enabled(self, target: ResolvedTarget) -> bool: ...

    def enter_text(self, target: ResolvedTarget, value: str) -> None: ...

    def activate(self, target: ResolvedTarget) -> None: ...

    def press_key(
        self,
        key: str,
        target: ResolvedTarget | None = None,
    ) -> None: ...

    def read_text(self, target: ResolvedTarget) -> str: ...

    def read_value(self, target: ResolvedTarget) -> str: ...
