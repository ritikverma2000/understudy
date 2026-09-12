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


def test_unknown_action_value_reference_is_rejected(
    artifact_data: dict,
) -> None:
    artifact_data["steps"][1]["action"]["value_from"] = (
        "inputs.missing_member"
    )

    with pytest.raises(ValidationError, match="references unknown value"):
        CapabilityArtifact.model_validate(artifact_data)


def test_unknown_locator_value_reference_is_rejected(
    artifact_data: dict,
) -> None:
    relation = artifact_data["targets"]["member_result_link"][
        "strategies"
    ][0]
    relation["row_match"]["equals_from"] = "inputs.missing_member"

    with pytest.raises(ValidationError, match="references unknown value"):
        CapabilityArtifact.model_validate(artifact_data)


def test_unknown_condition_output_is_rejected(
    artifact_data: dict,
) -> None:
    artifact_data["success_checkpoint"]["condition"]["conditions"][2][
        "output"
    ] = "missing_output"

    with pytest.raises(ValidationError, match="references unknown output"):
        CapabilityArtifact.model_validate(artifact_data)


def test_unknown_route_template_reference_is_rejected(
    artifact_data: dict,
) -> None:
    artifact_data["target"]["routes"]["app_shell"]["pattern"] = (
        "{{runtime.missing_origin}}/app"
    )

    with pytest.raises(ValidationError, match="references unknown value"):
        CapabilityArtifact.model_validate(artifact_data)


def test_actionable_target_cannot_treat_absence_as_success(
    artifact_data: dict,
) -> None:
    artifact_data["targets"]["member_id_input"]["drift_policy"][
        "no_resolution"
    ] = "condition_not_present"

    with pytest.raises(ValidationError, match="only detection targets"):
        CapabilityArtifact.model_validate(artifact_data)


def test_money_parser_output_types_are_checked(
    artifact_data: dict,
) -> None:
    parser = artifact_data["steps"][4]["action"]["parser"]
    parser["amount_output"] = "currency"
    parser["currency_output"] = "savings_balance_cents"

    with pytest.raises(ValidationError, match="money parser requires"):
        CapabilityArtifact.model_validate(artifact_data)


def test_sensitive_output_cannot_allow_raw_logging(
    artifact_data: dict,
) -> None:
    artifact_data["outputs"]["savings_balance_cents"]["log_policy"] = (
        "allow"
    )

    with pytest.raises(ValidationError, match="sensitive outputs"):
        CapabilityArtifact.model_validate(artifact_data)
