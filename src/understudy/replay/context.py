from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


_BINDING_PATTERN = re.compile(
    r"\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}"
)


@dataclass
class ReplayContext:
    inputs: dict[str, Any]
    runtime: dict[str, Any]
    outputs: dict[str, Any] = field(default_factory=dict)

    def lookup(self, reference: str) -> Any:
        current: Any = {
            "inputs": self.inputs,
            "runtime": self.runtime,
            "outputs": self.outputs,
        }

        for part in reference.split("."):
            if not isinstance(current, dict) or part not in current:
                raise KeyError(f"missing replay value {reference!r}")
            current = current[part]

        return current

    def values(self) -> dict[str, Any]:
        return {
            "inputs": self.inputs,
            "runtime": self.runtime,
            "outputs": self.outputs,
        }

    def render(self, template: str) -> str:
        return _BINDING_PATTERN.sub(
            lambda match: str(self.lookup(match.group(1))),
            template,
        )
