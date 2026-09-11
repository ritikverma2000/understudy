from pathlib import Path
from typing import Any

import pytest

from understudy.artifact.models import (
    AllCondition,
    CapabilityArtifact,
    ElementValueEqualsCondition,
    EnabledCondition,
    NotVisibleCondition,
    OutputMatchesCondition,
    RuntimeBindingPresentCondition,
    Target,
    VisibleCondition,
)
from understudy.replay.conditions import ConditionEvaluator
from understudy.replay.context import ReplayContext
from understudy.surface import ResolvedTarget


FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "lookup_member_savings.hand-authored.json"
)


class FakeSurface:
    def __init__(self) -> None:
        self.absent: set[str] = set()
        self.visible: set[str] = set()
        self.enabled: set[str] = set()
        self.text: dict[str, str] = {}
        self.values: dict[str, str] = {}

    def resolve_target(
        self,
        target_ref: str,
        target: Target,
        values: dict[str, Any],
    ) -> ResolvedTarget:
        if target_ref in self.absent:
            return ResolvedTarget(
                target_ref=target_ref,
                status="absent",
                strategy_id=None,
                match_count=0,
                handle=None,
            )

        return ResolvedTarget(
            target_ref=target_ref,
            status="primary",
            strategy_id=target.drift_policy.primary_strategy_id,
            match_count=1,
            handle=target_ref,
        )

    def is_visible(self, target: ResolvedTarget) -> bool:
        return target.target_ref in self.visible

    def is_enabled(self, target: ResolvedTarget) -> bool:
        return target.target_ref in self.enabled

    def read_text(self, target: ResolvedTarget) -> str:
        return self.text[target.target_ref]

    def read_value(self, target: ResolvedTarget) -> str:
        return self.values[target.target_ref]


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
        outputs={
            "savings_balance_cents": 125050,
            "currency": "USD",
        },
    )


@pytest.fixture
def surface() -> FakeSurface:
    return FakeSurface()


def test_runtime_binding_present(
    artifact: CapabilityArtifact,
    context: ReplayContext,
    surface: FakeSurface,
) -> None:
    evaluator = ConditionEvaluator(surface, artifact.targets)
    condition = RuntimeBindingPresentCondition(
        kind="runtime_binding_present",
        binding="base_url",
    )

    assert evaluator.evaluate(condition, context)


def test_visible_condition(
    artifact: CapabilityArtifact,
    context: ReplayContext,
    surface: FakeSurface,
) -> None:
    surface.visible.add("member_search_heading")
    evaluator = ConditionEvaluator(surface, artifact.targets)

    condition = VisibleCondition(
        kind="visible",
        target_ref="member_search_heading",
    )

    assert evaluator.evaluate(condition, context)


def test_absent_target_satisfies_not_visible(
    artifact: CapabilityArtifact,
    context: ReplayContext,
    surface: FakeSurface,
) -> None:
    surface.absent.add("member_not_found_message")
    evaluator = ConditionEvaluator(surface, artifact.targets)

    condition = NotVisibleCondition(
        kind="not_visible",
        target_ref="member_not_found_message",
    )

    assert evaluator.evaluate(condition, context)


def test_enabled_condition(
    artifact: CapabilityArtifact,
    context: ReplayContext,
    surface: FakeSurface,
) -> None:
    surface.enabled.add("member_id_input")
    evaluator = ConditionEvaluator(surface, artifact.targets)

    condition = EnabledCondition(
        kind="enabled",
        target_ref="member_id_input",
    )

    assert evaluator.evaluate(condition, context)


def test_element_value_equals_input(
    artifact: CapabilityArtifact,
    context: ReplayContext,
    surface: FakeSurface,
) -> None:
    surface.values["member_id_input"] = "00123"
    evaluator = ConditionEvaluator(surface, artifact.targets)

    condition = ElementValueEqualsCondition(
        kind="element_value_equals",
        target_ref="member_id_input",
        source="value",
        value_from="inputs.member_id",
        log_policy="redact",
    )

    assert evaluator.evaluate(condition, context)


def test_output_matches_type_and_value(
    artifact: CapabilityArtifact,
    context: ReplayContext,
    surface: FakeSurface,
) -> None:
    evaluator = ConditionEvaluator(surface, artifact.targets)

    amount = OutputMatchesCondition(
        kind="output_matches",
        output="savings_balance_cents",
        type="integer",
    )
    currency = OutputMatchesCondition(
        kind="output_matches",
        output="currency",
        type="string",
        equals="USD",
    )

    assert evaluator.evaluate(amount, context)
    assert evaluator.evaluate(currency, context)


def test_all_condition_requires_every_child(
    artifact: CapabilityArtifact,
    context: ReplayContext,
    surface: FakeSurface,
) -> None:
    evaluator = ConditionEvaluator(surface, artifact.targets)

    condition = AllCondition(
        kind="all",
        conditions=[
            RuntimeBindingPresentCondition(
                kind="runtime_binding_present",
                binding="base_url",
            ),
            OutputMatchesCondition(
                kind="output_matches",
                output="currency",
                type="string",
                equals="USD",
            ),
        ],
    )

    assert evaluator.evaluate(condition, context)