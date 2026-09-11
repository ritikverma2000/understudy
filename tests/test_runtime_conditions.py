from pathlib import Path
from typing import Any

import pytest

from understudy.artifact.models import (
    CapabilityArtifact,
    NotVisibleCondition,
    VisibleCondition,
)
from understudy.replay.context import ReplayContext
from understudy.replay.runtime import (
    BusinessOutcomeReached,
    HardRuntimeFailure,
    InterventionRequired,
    RuntimeConditionMonitor,
    RuntimeRecoveryError,
)
from understudy.replay.waiting import ConditionTimeoutError


FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "lookup_member_savings.hand-authored.json"
)
CONTEXT = ReplayContext(inputs={}, runtime={})


class DetectionEvaluator:
    def __init__(self, visible: set[str]) -> None:
        self.visible = visible

    def evaluate(self, condition: Any, context: ReplayContext) -> bool:
        if isinstance(condition, VisibleCondition):
            return condition.target_ref in self.visible
        if isinstance(condition, NotVisibleCondition):
            return condition.target_ref not in self.visible
        raise AssertionError(f"unexpected condition {condition!r}")


class RecordingWaiter:
    def __init__(self, *, time_out: bool = False) -> None:
        self.calls: list[tuple[str, int]] = []
        self.time_out = time_out

    def wait_until(
        self,
        condition: NotVisibleCondition,
        context: ReplayContext,
        *,
        timeout_ms: int,
        during_wait: Any = None,
    ) -> None:
        self.calls.append((condition.target_ref, timeout_ms))
        if self.time_out:
            raise ConditionTimeoutError(condition, timeout_ms)


@pytest.fixture(scope="module")
def artifact() -> CapabilityArtifact:
    return CapabilityArtifact.model_validate_json(FIXTURE_PATH.read_text())


def make_monitor(
    artifact: CapabilityArtifact,
    visible: set[str],
    waiter: RecordingWaiter | None = None,
) -> RuntimeConditionMonitor:
    return RuntimeConditionMonitor(
        artifact.runtime_conditions,
        DetectionEvaluator(visible),  # type: ignore[arg-type]
        waiter or RecordingWaiter(),  # type: ignore[arg-type]
    )


def test_highest_priority_condition_wins(
    artifact: CapabilityArtifact,
) -> None:
    monitor = make_monitor(
        artifact,
        {"session_expired_message", "application_error_message"},
    )

    with pytest.raises(InterventionRequired) as captured:
        monitor.check("during_wait", CONTEXT)

    assert captured.value.code == "SESSION_EXPIRED"


def test_application_error_is_a_hard_failure(
    artifact: CapabilityArtifact,
) -> None:
    monitor = make_monitor(artifact, {"application_error_message"})

    with pytest.raises(HardRuntimeFailure) as captured:
        monitor.check("after_step", CONTEXT)

    assert captured.value.code == "APPLICATION_ERROR"


def test_member_not_found_is_a_business_outcome(
    artifact: CapabilityArtifact,
) -> None:
    monitor = make_monitor(artifact, {"member_not_found_message"})

    with pytest.raises(BusinessOutcomeReached) as captured:
        monitor.check("after_step", CONTEXT)

    assert captured.value.code == "MEMBER_NOT_FOUND"


def test_transient_loading_waits_until_hidden(
    artifact: CapabilityArtifact,
) -> None:
    waiter = RecordingWaiter()
    monitor = make_monitor(artifact, {"loading_message"}, waiter)

    monitor.check("during_wait", CONTEXT)

    assert waiter.calls == [("loading_message", 5000)]


def test_exhausted_loading_recovery_fails(
    artifact: CapabilityArtifact,
) -> None:
    waiter = RecordingWaiter(time_out=True)
    monitor = make_monitor(artifact, {"loading_message"}, waiter)

    with pytest.raises(RuntimeRecoveryError, match="TRANSIENT_LOADING"):
        monitor.check("during_wait", CONTEXT)

    assert len(waiter.calls) == 2
