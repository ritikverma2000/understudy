from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from understudy.artifact.models import CapabilityArtifact, Step
from understudy.replay.actions import ActionExecutor
from understudy.replay.conditions import ConditionEvaluator
from understudy.replay.context import ReplayContext
from understudy.replay.parsers import MoneyParseError
from understudy.replay.runtime import (
    BusinessOutcomeReached,
    RuntimeConditionMonitor,
)
from understudy.replay.waiting import ConditionTimeoutError, ConditionWaiter
from understudy.surface import Surface, TargetResolutionError


ReplayStatus = Literal["success", "business_outcome"]


@dataclass(frozen=True)
class ReplayResult:
    status: ReplayStatus
    outputs: dict[str, Any]
    completed_steps: tuple[str, ...]
    message: str | None = None
    condition_code: str | None = None


class ReplayPolicyError(RuntimeError):
    pass


class StepExecutionError(RuntimeError):
    def __init__(self, step_id: str, attempts: int) -> None:
        self.step_id = step_id
        self.attempts = attempts
        super().__init__(
            f"step {step_id!r} failed after {attempts} attempt(s)"
        )


class ReplayEngine:
    def __init__(
        self,
        artifact: CapabilityArtifact,
        surface: Surface,
        *,
        poll_interval_ms: int = 50,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._artifact = artifact
        self._surface = surface
        self._monotonic = monotonic
        self._sleep = sleep
        self._evaluator = ConditionEvaluator(surface, artifact.targets)
        self._waiter = ConditionWaiter(
            self._evaluator,
            poll_interval_ms=poll_interval_ms,
            monotonic=monotonic,
            sleep=sleep,
        )
        self._actions = ActionExecutor(
            surface,
            artifact.targets,
            artifact.target.routes,
        )
        self._runtime = RuntimeConditionMonitor(
            artifact.runtime_conditions,
            self._evaluator,
            self._waiter,
        )

    def run(
        self,
        *,
        inputs: dict[str, Any],
        runtime: dict[str, Any],
    ) -> ReplayResult:
        self._validate_request(inputs, runtime)
        context = ReplayContext(inputs=inputs, runtime=runtime)
        completed: list[str] = []
        started_at = self._monotonic()

        try:
            for step in self._artifact.steps:
                self._enforce_runtime_budget(started_at)
                self._run_step(step, context, started_at)
                completed.append(step.id)
                self._runtime.check("after_step", context)

            checkpoint_timeout = self._remaining_runtime_ms(started_at)
            if checkpoint_timeout <= 0:
                raise ReplayPolicyError("maximum runtime exceeded")

            self._waiter.wait_until(
                self._artifact.success_checkpoint.condition,
                context,
                timeout_ms=checkpoint_timeout,
                during_wait=lambda: self._runtime.check(
                    "during_wait",
                    context,
                ),
            )
        except BusinessOutcomeReached as outcome:
            return ReplayResult(
                status="business_outcome",
                outputs=dict(context.outputs),
                completed_steps=tuple(completed),
                message=outcome.message,
                condition_code=outcome.code,
            )

        return ReplayResult(
            status="success",
            outputs=dict(context.outputs),
            completed_steps=tuple(completed),
        )

    def _run_step(
        self,
        step: Step,
        context: ReplayContext,
        started_at: float,
    ) -> None:
        during_wait = lambda: self._runtime.check(
            "during_wait",
            context,
        )
        self._waiter.wait_until(
            step.precondition,
            context,
            timeout_ms=self._step_timeout(step, started_at),
            during_wait=during_wait,
        )

        action_completed = False
        last_error: Exception | None = None
        attempts_made = 0

        for attempt in range(1, step.retry.max_attempts + 1):
            attempts_made = attempt
            self._enforce_runtime_budget(started_at)

            try:
                if not action_completed or step.retry.retry_action:
                    self._actions.execute(step.action, context)
                    action_completed = True

                self._waiter.wait_until(
                    step.postcondition,
                    context,
                    timeout_ms=self._step_timeout(step, started_at),
                    during_wait=during_wait,
                )
                return
            except (
                ConditionTimeoutError,
                MoneyParseError,
                TargetResolutionError,
            ) as error:
                last_error = error

                if attempt == step.retry.max_attempts:
                    break

                if not self._retry_allowed(error, step.retry.retry_on):
                    break

                self._sleep(self._backoff_seconds(step, attempt))

        raise StepExecutionError(
            step.id,
            attempts_made,
        ) from last_error

    @staticmethod
    def _retry_allowed(error: Exception, retry_on: list[str]) -> bool:
        if isinstance(error, ConditionTimeoutError):
            return any(
                reason.startswith("postcondition_not_met")
                for reason in retry_on
            )

        if isinstance(error, MoneyParseError):
            return "parse_failed" in retry_on

        if isinstance(error, TargetResolutionError):
            return "target_temporarily_unavailable" in retry_on

        return False

    @staticmethod
    def _backoff_seconds(step: Step, attempt: int) -> float:
        if not step.retry.backoff_ms:
            return 0

        index = min(attempt - 1, len(step.retry.backoff_ms) - 1)
        return step.retry.backoff_ms[index] / 1000

    def _validate_request(
        self,
        inputs: dict[str, Any],
        runtime: dict[str, Any],
    ) -> None:
        artifact = self._artifact
        policy = artifact.policy_requirements

        if len(artifact.steps) > policy.maximum_steps:
            raise ReplayPolicyError("artifact exceeds maximum_steps")

        for name, definition in artifact.inputs.items():
            if definition.required and name not in inputs:
                raise ReplayPolicyError(f"missing required input {name!r}")

            if name in inputs and re.fullmatch(
                definition.pattern,
                str(inputs[name]),
            ) is None:
                raise ReplayPolicyError(
                    f"input {name!r} does not match its pattern"
                )

        for name, definition in artifact.target.runtime_bindings.items():
            if definition.required and not runtime.get(name):
                raise ReplayPolicyError(
                    f"missing required runtime binding {name!r}"
                )

        for step in artifact.steps:
            if step.action.type not in policy.allowed_action_types:
                raise ReplayPolicyError(
                    f"action {step.action.type!r} is not allowed"
                )

            if step.risk not in policy.risk.allowed_without_confirmation:
                raise ReplayPolicyError(
                    f"step {step.id!r} requires human confirmation"
                )

            route_ref = getattr(step.action, "route_ref", None)
            if (
                route_ref is not None
                and route_ref not in policy.allowed_route_refs
            ):
                raise ReplayPolicyError(
                    f"route {route_ref!r} is not allowed"
                )

    def _enforce_runtime_budget(self, started_at: float) -> None:
        if self._remaining_runtime_ms(started_at) <= 0:
            raise ReplayPolicyError("maximum runtime exceeded")

    def _step_timeout(self, step: Step, started_at: float) -> int:
        remaining = self._remaining_runtime_ms(started_at)
        if remaining <= 0:
            raise ReplayPolicyError("maximum runtime exceeded")
        return min(step.timeout_ms, remaining)

    def _remaining_runtime_ms(self, started_at: float) -> int:
        elapsed_ms = int((self._monotonic() - started_at) * 1000)
        return max(
            0,
            self._artifact.policy_requirements.maximum_runtime_ms
            - elapsed_ms,
        )
