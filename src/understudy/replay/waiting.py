from __future__ import annotations

import time
from collections.abc import Callable
from typing import Protocol

from understudy.artifact.models import Condition
from understudy.replay.context import ReplayContext
from understudy.surface import TargetResolutionError


class ConditionEvaluation(Protocol):
    def evaluate(
        self,
        condition: Condition,
        context: ReplayContext,
    ) -> bool: ...


class ConditionTimeoutError(TimeoutError):
    def __init__(
        self,
        condition: Condition,
        timeout_ms: int,
    ) -> None:
        self.condition = condition
        self.timeout_ms = timeout_ms

        super().__init__(
            f"condition {condition.kind!r} was not met "
            f"within {timeout_ms} ms"
        )


class ConditionWaiter:
    def __init__(
        self,
        evaluator: ConditionEvaluation,
        *,
        poll_interval_ms: int = 50,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if poll_interval_ms <= 0:
            raise ValueError(
                "poll_interval_ms must be greater than zero"
            )

        self._evaluator = evaluator
        self._poll_interval_seconds = (
            poll_interval_ms / 1000
        )
        self._monotonic = monotonic
        self._sleep = sleep

    def wait_until(
        self,
        condition: Condition,
        context: ReplayContext,
        *,
        timeout_ms: int,
        during_wait: Callable[[], None] | None = None,
    ) -> None:
        if timeout_ms <= 0:
            raise ValueError(
                "timeout_ms must be greater than zero"
            )

        deadline = self._monotonic() + timeout_ms / 1000

        while True:
            try:
                condition_met = self._evaluator.evaluate(
                    condition,
                    context,
                )
            except TargetResolutionError:
                condition_met = False

            if condition_met:
                return

            # Exceptional states must be observed while the page is changing,
            # rather than only after this condition times out.
            if during_wait is not None:
                during_wait()

            remaining = deadline - self._monotonic()

            if remaining <= 0:
                raise ConditionTimeoutError(
                    condition,
                    timeout_ms,
                )

            self._sleep(
                min(
                    self._poll_interval_seconds,
                    remaining,
                )
            )
