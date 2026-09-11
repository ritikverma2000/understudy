import pytest

from understudy.handoff import HandoffSession


def test_control_lease_cedes_and_resumes() -> None:
    session = HandoffSession(
        session_id="handoff-test",
        capability_id="lookup_member_savings",
        goal="synthetic goal",
        current_step="navigate_to_member_search",
        reason="session expired",
    )

    session.cede_to_human()
    assert session.owner == "human"

    session.resume_automation(
        actor="operator-1",
        reason="session restored",
    )
    assert session.owner == "automation"
    assert [event.to_owner for event in session.transfers] == [
        "human",
        "automation",
    ]


def test_control_lease_rejects_invalid_transfer() -> None:
    session = HandoffSession(
        session_id="handoff-test",
        capability_id="lookup_member_savings",
        goal="synthetic goal",
        current_step="search",
        reason="blocked",
    )

    with pytest.raises(RuntimeError, match="human does not own"):
        session.resume_automation(actor="operator-1", reason="invalid")
