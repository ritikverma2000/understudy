import pytest

from understudy.artifact.models import RuntimeBindingPresentCondition
from understudy.replay.context import ReplayContext
from understudy.replay.waiting import ConditionTimeoutError, ConditionWaiter
from understudy.surface import TargetResolutionError


CONDITION = RuntimeBindingPresentCondition(
    kind="runtime_binding_present",
    binding="base_url",
)
CONTEXT = ReplayContext(inputs={}, runtime={})


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class SequenceEvaluator:
    def __init__(self, outcomes: list[bool | Exception]) -> None:
        self._outcomes = iter(outcomes)
        self.calls = 0

    def evaluate(self, condition: object, context: object) -> bool:
        self.calls += 1
        outcome = next(self._outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def make_waiter(
    outcomes: list[bool | Exception],
) -> tuple[ConditionWaiter, SequenceEvaluator, FakeClock]:
    evaluator = SequenceEvaluator(outcomes)
    clock = FakeClock()
    waiter = ConditionWaiter(
        evaluator,
        poll_interval_ms=10,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )
    return waiter, evaluator, clock


def test_returns_immediately_when_condition_is_met() -> None:
    waiter, evaluator, clock = make_waiter([True])

    waiter.wait_until(CONDITION, CONTEXT, timeout_ms=100)

    assert evaluator.calls == 1
    assert clock.now == 0


def test_polls_until_condition_is_met() -> None:
    waiter, evaluator, clock = make_waiter([False, False, True])

    waiter.wait_until(CONDITION, CONTEXT, timeout_ms=100)

    assert evaluator.calls == 3
    assert clock.now == pytest.approx(0.02)


def test_checks_runtime_conditions_during_wait() -> None:
    waiter, _, _ = make_waiter([False, False, True])
    checks = 0

    def during_wait() -> None:
        nonlocal checks
        checks += 1

    waiter.wait_until(
        CONDITION,
        CONTEXT,
        timeout_ms=100,
        during_wait=during_wait,
    )

    assert checks == 2


def test_target_resolution_failure_is_transient() -> None:
    error = TargetResolutionError("not ready")
    waiter, evaluator, _ = make_waiter([error, True])

    waiter.wait_until(CONDITION, CONTEXT, timeout_ms=100)

    assert evaluator.calls == 2


def test_raises_after_timeout() -> None:
    evaluator = AlwaysFalseEvaluator()
    clock = FakeClock()
    waiter = ConditionWaiter(
        evaluator,
        poll_interval_ms=10,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    with pytest.raises(ConditionTimeoutError):
        waiter.wait_until(CONDITION, CONTEXT, timeout_ms=25)

    assert clock.now == pytest.approx(0.025)


class AlwaysFalseEvaluator:
    def evaluate(self, condition: object, context: object) -> bool:
        return False
