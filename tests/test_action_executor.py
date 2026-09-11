from pathlib import Path
from typing import Any

import pytest

from understudy.artifact.models import (
    CapabilityArtifact,
    PressKeyAction,
    Target,
)
from understudy.replay.actions import ActionExecutor
from understudy.replay.context import ReplayContext
from understudy.surface import ResolvedTarget


FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "lookup_member_savings.hand-authored.json"
)


class FakeSurface:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.target_text: dict[str, str] = {
            "savings_balance_cell": "$1,250.50",
        }

    def navigate(self, url: str) -> None:
        self.calls.append(("navigate", url))

    def resolve_target(
        self,
        target_ref: str,
        target: Target,
        values: dict[str, Any],
    ) -> ResolvedTarget:
        self.calls.append(("resolve", target_ref))

        return ResolvedTarget(
            target_ref=target_ref,
            status="primary",
            strategy_id=target.drift_policy.primary_strategy_id,
            match_count=1,
            handle=target_ref,
        )

    def enter_text(
        self,
        target: ResolvedTarget,
        value: str,
    ) -> None:
        self.calls.append(
            ("enter_text", target.target_ref, value)
        )

    def activate(self, target: ResolvedTarget) -> None:
        self.calls.append(("activate", target.target_ref))

    def press_key(
        self,
        key: str,
        target: ResolvedTarget | None = None,
    ) -> None:
        target_ref = (
            target.target_ref if target is not None else None
        )
        self.calls.append(("press_key", key, target_ref))

    def read_text(self, target: ResolvedTarget) -> str:
        self.calls.append(("read_text", target.target_ref))
        return self.target_text[target.target_ref]


@pytest.fixture
def artifact() -> CapabilityArtifact:
    return CapabilityArtifact.model_validate_json(
        FIXTURE_PATH.read_text()
    )


@pytest.fixture
def context() -> ReplayContext:
    return ReplayContext(
        inputs={"member_id": "00123"},
        runtime={"base_url": "http://127.0.0.1:5000"},
    )


@pytest.fixture
def surface() -> FakeSurface:
    return FakeSurface()


@pytest.fixture
def executor(
    artifact: CapabilityArtifact,
    surface: FakeSurface,
) -> ActionExecutor:
    return ActionExecutor(
        surface=surface,
        targets=artifact.targets,
        routes=artifact.target.routes,
    )


def test_navigate_renders_runtime_binding(
    artifact: CapabilityArtifact,
    context: ReplayContext,
    surface: FakeSurface,
    executor: ActionExecutor,
) -> None:
    executor.execute(artifact.steps[0].action, context)

    assert surface.calls == [
        ("navigate", "http://127.0.0.1:5000/app")
    ]


def test_enter_text_reads_input(
    artifact: CapabilityArtifact,
    context: ReplayContext,
    surface: FakeSurface,
    executor: ActionExecutor,
) -> None:
    executor.execute(artifact.steps[1].action, context)

    assert surface.calls == [
        ("resolve", "member_id_input"),
        ("enter_text", "member_id_input", "00123"),
    ]


def test_activate_resolves_and_clicks_target(
    artifact: CapabilityArtifact,
    context: ReplayContext,
    surface: FakeSurface,
    executor: ActionExecutor,
) -> None:
    executor.execute(artifact.steps[2].action, context)

    assert surface.calls == [
        ("resolve", "search_control"),
        ("activate", "search_control"),
    ]


def test_read_parses_and_populates_outputs(
    artifact: CapabilityArtifact,
    context: ReplayContext,
    surface: FakeSurface,
    executor: ActionExecutor,
) -> None:
    executor.execute(artifact.steps[4].action, context)

    assert context.outputs == {
        "savings_balance_cents": 125050,
        "currency": "USD",
    }


def test_press_key_without_target(
    context: ReplayContext,
    surface: FakeSurface,
    executor: ActionExecutor,
) -> None:
    action = PressKeyAction(
        type="press_key",
        key="Escape",
    )

    executor.execute(action, context)

    assert surface.calls == [
        ("press_key", "Escape", None)
    ]


def test_press_key_with_target(
    context: ReplayContext,
    surface: FakeSurface,
    executor: ActionExecutor,
) -> None:
    action = PressKeyAction(
        type="press_key",
        key="Enter",
        target_ref="member_id_input",
    )

    executor.execute(action, context)

    assert surface.calls == [
        ("resolve", "member_id_input"),
        ("press_key", "Enter", "member_id_input"),
    ]