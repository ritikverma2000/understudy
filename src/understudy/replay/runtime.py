from __future__ import annotations

from typing import Literal

from understudy.artifact.models import (
    BusinessOutcomeRuntimeCondition,
    HardFailureRuntimeCondition,
    InterventionRuntimeCondition,
    NotVisibleCondition,
    RecoverableRuntimeCondition,
    RuntimeCondition,
)
from understudy.replay.conditions import ConditionEvaluator
from understudy.replay.context import ReplayContext
from understudy.replay.waiting import ConditionTimeoutError, ConditionWaiter
from understudy.surface import TargetResolutionError


CheckPhase = Literal["during_wait", "after_step"]


class BusinessOutcomeReached(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


class InterventionRequired(RuntimeError):
    def __init__(
        self,
        code: str,
        reason: str,
        *,
        capability_id: str | None = None,
        goal: str | None = None,
        current_step: str | None = None,
    ) -> None:
        self.code = code
        self.reason = reason
        self.capability_id = capability_id
        self.goal = goal
        self.current_step = current_step
        super().__init__(f"{code}: {reason}")


class HardRuntimeFailure(RuntimeError):
    def __init__(self, code: str, category: str) -> None:
        self.code = code
        self.category = category
        super().__init__(f"{code}: {category}")


class RuntimeRecoveryError(RuntimeError):
    pass


class RuntimeConditionMonitor:
    def __init__(
        self,
        conditions: list[RuntimeCondition],
        evaluator: ConditionEvaluator,
        waiter: ConditionWaiter,
    ) -> None:
        self._conditions = sorted(
            conditions,
            key=lambda condition: condition.priority,
            reverse=True,
        )
        self._evaluator = evaluator
        self._waiter = waiter

    def check(
        self,
        phase: CheckPhase,
        context: ReplayContext,
        *,
        excluded_codes: frozenset[str] = frozenset(),
    ) -> None:
        for condition in self._conditions:
            if (
                condition.code in excluded_codes
                or phase not in condition.check_phases
            ):
                continue

            try:
                detected = self._evaluator.evaluate(
                    condition.detect,
                    context,
                )
            except TargetResolutionError:
                detected = False

            if not detected:
                continue

            if isinstance(condition, InterventionRuntimeCondition):
                raise InterventionRequired(
                    condition.code,
                    condition.intervention.reason,
                )

            if isinstance(condition, HardFailureRuntimeCondition):
                raise HardRuntimeFailure(
                    condition.code,
                    condition.failure.category,
                )

            if isinstance(condition, BusinessOutcomeRuntimeCondition):
                raise BusinessOutcomeReached(
                    condition.code,
                    condition.result.message,
                )

            if isinstance(condition, RecoverableRuntimeCondition):
                self._recover(condition, context, excluded_codes)

    def _recover(
        self,
        condition: RecoverableRuntimeCondition,
        context: ReplayContext,
        excluded_codes: frozenset[str],
    ) -> None:
        recovery = condition.recovery
        hidden = NotVisibleCondition(
            kind="not_visible",
            target_ref=recovery.target_ref,
        )
        exclusions = excluded_codes | {condition.code}

        for _ in range(recovery.max_attempts):
            try:
                self._waiter.wait_until(
                    hidden,
                    context,
                    timeout_ms=recovery.timeout_ms,
                    during_wait=lambda: self.check(
                        "during_wait",
                        context,
                        excluded_codes=exclusions,
                    ),
                )
                return
            except ConditionTimeoutError:
                continue

        raise RuntimeRecoveryError(
            f"{condition.code}: {recovery.on_exhausted}"
        )
