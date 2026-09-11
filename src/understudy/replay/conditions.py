from __future__ import annotations

from typing import assert_never

from understudy.artifact.models import (
    AllCondition,
    Condition,
    ElementValueEqualsCondition,
    EnabledCondition,
    NotVisibleCondition,
    OutputMatchesCondition,
    RuntimeBindingPresentCondition,
    Target,
    VisibleCondition,
)
from understudy.replay.context import ReplayContext
from understudy.surface import Surface


class ConditionEvaluator:
    def __init__(
        self,
        surface: Surface,
        targets: dict[str, Target],
    ) -> None:
        self._surface = surface
        self._targets = targets

    def evaluate(
        self,
        condition: Condition,
        context: ReplayContext,
    ) -> bool:
        if isinstance(condition, AllCondition):
            return all(
                self.evaluate(child, context)
                for child in condition.conditions
            )

        if isinstance(condition, RuntimeBindingPresentCondition):
            return (
                condition.binding in context.runtime
                and context.runtime[condition.binding] is not None
            )

        if isinstance(condition, OutputMatchesCondition):
            return self._output_matches(condition, context)

        target = self._surface.resolve_target(
            condition.target_ref,
            self._targets[condition.target_ref],
            context.values(),
        )

        if isinstance(condition, VisibleCondition):
            return (
                target.present
                and self._surface.is_visible(target)
            )

        if isinstance(condition, NotVisibleCondition):
            return (
                not target.present
                or not self._surface.is_visible(target)
            )

        if isinstance(condition, EnabledCondition):
            return (
                target.present
                and self._surface.is_enabled(target)
            )

        if isinstance(condition, ElementValueEqualsCondition):
            if not target.present:
                return False

            if condition.source == "value":
                actual = self._surface.read_value(target)
            else:
                actual = self._surface.read_text(target)

            expected = context.lookup(condition.value_from)
            return actual.strip() == str(expected).strip()

        assert_never(condition)

    @staticmethod
    def _output_matches(
        condition: OutputMatchesCondition,
        context: ReplayContext,
    ) -> bool:
        if condition.output not in context.outputs:
            return False

        value = context.outputs[condition.output]

        if condition.type == "integer":
            type_matches = type(value) is int
        else:
            type_matches = isinstance(value, str)

        if not type_matches:
            return False

        if condition.equals is not None:
            return value == condition.equals

        return True