import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from understudy.artifact.models import CapabilityArtifact


FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "lookup_member_savings.hand-authored.json"
)


@pytest.fixture
def artifact_data() -> dict:
    return json.loads(FIXTURE_PATH.read_text())


def test_hand_authored_artifact_is_valid() -> None:
    artifact = CapabilityArtifact.model_validate_json(
        FIXTURE_PATH.read_text()
    )

    assert artifact.capability.id == "lookup_member_savings"
    assert artifact.capability.version == "1.0.0"
    assert len(artifact.targets) == 12
    assert len(artifact.steps) == 5
    assert len(artifact.runtime_conditions) == 4


def test_unknown_top_level_field_is_rejected(
    artifact_data: dict,
) -> None:
    artifact_data["unexpected"] = True

    with pytest.raises(ValidationError):
        CapabilityArtifact.model_validate(artifact_data)


def test_unknown_locator_kind_is_rejected(
    artifact_data: dict,
) -> None:
    strategy = artifact_data["targets"][
        "member_search_heading"
    ]["strategies"][0]

    strategy["kind"] = "magic_selector"

    with pytest.raises(ValidationError):
        CapabilityArtifact.model_validate(artifact_data)


def test_duplicate_step_ids_are_rejected(
    artifact_data: dict,
) -> None:
    artifact_data["steps"][1]["id"] = (
        artifact_data["steps"][0]["id"]
    )

    with pytest.raises(
        ValidationError,
        match="step IDs must be unique",
    ):
        CapabilityArtifact.model_validate(artifact_data)


def test_dangling_action_target_is_rejected(
    artifact_data: dict,
) -> None:
    artifact_data["steps"][1]["action"]["target_ref"] = (
        "missing_target"
    )

    with pytest.raises(
        ValidationError,
        match="references unknown targets",
    ):
        CapabilityArtifact.model_validate(artifact_data)


def test_dangling_context_reference_is_rejected(
    artifact_data: dict,
) -> None:
    artifact_data["targets"][
        "member_id_input"
    ]["context_ref"] = "missing_context"

    with pytest.raises(
        ValidationError,
        match="references unknown context",
    ):
        CapabilityArtifact.model_validate(artifact_data)


def test_unknown_primary_strategy_is_rejected(
    artifact_data: dict,
) -> None:
    artifact_data["targets"][
        "member_id_input"
    ]["drift_policy"]["primary_strategy_id"] = (
        "missing_strategy"
    )

    with pytest.raises(
        ValidationError,
        match="references unknown primary strategy",
    ):
        CapabilityArtifact.model_validate(artifact_data)


def test_undeclared_parser_output_is_rejected(
    artifact_data: dict,
) -> None:
    artifact_data["steps"][4]["action"]["parser"][
        "amount_output"
    ] = "undeclared_balance"

    with pytest.raises(
        ValidationError,
        match="writes undeclared outputs",
    ):
        CapabilityArtifact.model_validate(artifact_data)