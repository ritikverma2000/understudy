from pathlib import Path
from typing import Any

import pytest

from understudy.artifact.models import CapabilityArtifact, Target
from understudy.replay import ReplayEngine, ReplayPolicyError
from understudy.surface import ResolvedTarget


FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "lookup_member_savings.hand-authored.json"
)


class WorkflowSurface:
    def __init__(self) -> None:
        self.state = "blank"
        self.member_id = ""

    def navigate(self, url: str) -> None:
        self.state = "search"

    def resolve_target(
        self,
        target_ref: str,
        target: Target,
        values: dict[str, Any],
    ) -> ResolvedTarget:
        detectable_present = (
            target_ref == "member_not_found_message"
            and self.state == "not_found"
        )
        absent = target.role_in_flow == "detectable" and not detectable_present

        return ResolvedTarget(
            target_ref=target_ref,
            status="absent" if absent else "primary",
            strategy_id=(
                None if absent else target.drift_policy.primary_strategy_id
            ),
            match_count=0 if absent else 1,
            handle=None if absent else target_ref,
        )

    def is_visible(self, target: ResolvedTarget) -> bool:
        visible_by_state = {
            "search": {"member_search_heading", "member_id_input", "search_control"},
            "results": {"search_results_heading", "member_result_link"},
            "not_found": {"search_results_heading", "member_not_found_message"},
            "detail": {
                "member_detail_heading",
                "displayed_member_id",
                "savings_balance_cell",
            },
        }
        return target.target_ref in visible_by_state.get(self.state, set())

    def is_enabled(self, target: ResolvedTarget) -> bool:
        return self.is_visible(target)

    def enter_text(self, target: ResolvedTarget, value: str) -> None:
        self.member_id = value

    def activate(self, target: ResolvedTarget) -> None:
        if target.target_ref == "search_control":
            self.state = "results" if self.member_id == "00123" else "not_found"
        elif target.target_ref == "member_result_link":
            self.state = "detail"

    def press_key(
        self,
        key: str,
        target: ResolvedTarget | None = None,
    ) -> None:
        pass

    def read_text(self, target: ResolvedTarget) -> str:
        if target.target_ref == "displayed_member_id":
            return self.member_id
        if target.target_ref == "savings_balance_cell":
            return "$1,250.50"
        raise KeyError(target.target_ref)

    def read_value(self, target: ResolvedTarget) -> str:
        if target.target_ref == "member_id_input":
            return self.member_id
        raise KeyError(target.target_ref)


class FlakyMoneySurface(WorkflowSurface):
    def __init__(self) -> None:
        super().__init__()
        self.balance_reads = 0

    def read_text(self, target: ResolvedTarget) -> str:
        if target.target_ref == "savings_balance_cell":
            self.balance_reads += 1
            if self.balance_reads == 1:
                return "temporarily unavailable"
        return super().read_text(target)


@pytest.fixture(scope="module")
def artifact() -> CapabilityArtifact:
    return CapabilityArtifact.model_validate_json(FIXTURE_PATH.read_text())


def test_successful_replay_returns_declared_outputs(
    artifact: CapabilityArtifact,
) -> None:
    result = ReplayEngine(artifact, WorkflowSurface()).run(
        inputs={"member_id": "00123"},
        runtime={"base_url": "http://example.test"},
    )

    assert result.status == "success"
    assert result.outputs == {
        "savings_balance_cents": 125050,
        "currency": "USD",
    }
    assert result.completed_steps == tuple(step.id for step in artifact.steps)


def test_not_found_is_a_business_outcome(
    artifact: CapabilityArtifact,
) -> None:
    result = ReplayEngine(artifact, WorkflowSurface()).run(
        inputs={"member_id": "99999"},
        runtime={"base_url": "http://example.test"},
    )

    assert result.status == "business_outcome"
    assert result.condition_code == "MEMBER_NOT_FOUND"
    assert result.outputs == {}
    assert result.completed_steps[-1] == "activate_member_search"


def test_retryable_parse_failure_repeats_read_action(
    artifact: CapabilityArtifact,
) -> None:
    surface = FlakyMoneySurface()

    result = ReplayEngine(
        artifact,
        surface,
        sleep=lambda seconds: None,
    ).run(
        inputs={"member_id": "00123"},
        runtime={"base_url": "http://example.test"},
    )

    assert result.status == "success"
    assert surface.balance_reads == 2


@pytest.mark.parametrize("member_id", ["123", "abcde", "123456"])
def test_invalid_input_is_rejected(
    artifact: CapabilityArtifact,
    member_id: str,
) -> None:
    with pytest.raises(ReplayPolicyError, match="does not match"):
        ReplayEngine(artifact, WorkflowSurface()).run(
            inputs={"member_id": member_id},
            runtime={"base_url": "http://example.test"},
        )


def test_missing_runtime_binding_is_rejected(
    artifact: CapabilityArtifact,
) -> None:
    with pytest.raises(ReplayPolicyError, match="runtime binding"):
        ReplayEngine(artifact, WorkflowSurface()).run(
            inputs={"member_id": "00123"},
            runtime={},
        )
