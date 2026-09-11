import json
from pathlib import Path
from typing import Any

from understudy.artifact.models import CapabilityArtifact
from understudy.discovery.engine import DiscoveryRunner
from understudy.discovery.models import (
    ActivateDecision,
    ControlSnapshot,
    FinishDecision,
    Observation,
    ReadDecision,
    TypeTextDecision,
)
from understudy.discovery.surface import LiveControl


FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "lookup_member_savings.hand-authored.json"
)


class FakePage:
    def screenshot(self, *, path: str, full_page: bool) -> None:
        Path(path).write_bytes(b"synthetic screenshot")


class FakeLocator:
    pass


class FakeDiscoverySurface:
    def __init__(self) -> None:
        self.page = FakePage()
        self.actions: list[tuple[str, str, str | None]] = []
        self.state = 0

    def navigate(self, url: str) -> None:
        self.actions.append(("navigate", url, None))

    def observe(self) -> Observation:
        controls = [
            ControlSnapshot(
                id="c1",
                role=("textbox", "link", "link", "cell", "heading")[
                    self.state
                ],
                name=(
                    "Member ID",
                    "Find member",
                    "View details",
                    "$1,250.50",
                    "Member Details",
                )[self.state],
                context="frame:1",
            )
        ]
        return Observation(
            url="http://example.test/app",
            title="CoreView",
            controls=controls,
        )

    def _control(self) -> LiveControl:
        snapshot = self.observe().controls[0]
        return LiveControl(snapshot, FakeLocator())  # type: ignore[arg-type]

    def type_text(self, control_id: str, value: str) -> LiveControl:
        control = self._control()
        self.actions.append(("type_text", control_id, value))
        self.state += 1
        return control

    def activate(self, control_id: str) -> LiveControl:
        control = self._control()
        self.actions.append(("activate", control_id, None))
        self.state += 1
        return control

    def read(self, control_id: str) -> tuple[LiveControl, str]:
        control = self._control()
        self.actions.append(("read", control_id, None))
        self.state += 1
        return control, "$1,250.50"


class FakeModel:
    provider_name = "fake-provider"
    model_name = "fake-model"

    def __init__(self) -> None:
        self.decisions = iter(
            [
                TypeTextDecision(
                    type="type_text",
                    control_id="c1",
                    target_ref="member_id_input",
                    input_name="member_id",
                    decision_summary="Use the labeled member ID field.",
                ),
                ActivateDecision(
                    type="activate",
                    control_id="c1",
                    target_ref="search_control",
                    decision_summary="Submit the search.",
                ),
                ActivateDecision(
                    type="activate",
                    control_id="c1",
                    target_ref="member_result_link",
                    decision_summary="Open the matching result for 00123.",
                ),
                ReadDecision(
                    type="read",
                    control_id="c1",
                    target_ref="savings_balance_cell",
                    decision_summary="Read $1,250.50 from the Savings cell.",
                ),
                FinishDecision(
                    type="finish",
                    decision_summary=(
                        "The requested output $1,250.50 is available."
                    ),
                ),
            ]
        )

    def decide(self, **kwargs: Any) -> Any:
        return next(self.decisions)


def test_discovery_emits_valid_artifact_and_sanitized_evidence(
    tmp_path: Path,
) -> None:
    template = CapabilityArtifact.model_validate_json(FIXTURE_PATH.read_text())
    surface = FakeDiscoverySurface()
    runner = DiscoveryRunner(
        model=FakeModel(),  # type: ignore[arg-type]
        surface=surface,  # type: ignore[arg-type]
        template=template,
    )
    runner._verify_checkpoint = (  # type: ignore[method-assign]
        lambda inputs, outputs: None
    )
    artifact_path = tmp_path / "capabilities" / "generated.json"
    evidence_dir = tmp_path / "evidence"

    result = runner.run(
        goal="Look up member 00123 and read the savings balance",
        target_url="http://example.test/app",
        inputs={"member_id": "00123"},
        artifact_path=artifact_path,
        evidence_dir=evidence_dir,
    )

    artifact = CapabilityArtifact.model_validate_json(artifact_path.read_text())
    evidence = json.loads(result.evidence_path.read_text())
    assert artifact.provenance.source == "discovery_generated"
    assert artifact.provenance.discovery_run_id == result.run_id
    primary = artifact.targets["search_control"].strategies[0]
    assert primary.name == "Find member"  # type: ignore[union-attr]
    assert evidence["kind"] == "llm_discovery"
    assert evidence["provider"] == "fake-provider"
    assert "00123" not in evidence["goal"]
    assert evidence["outputs"] == {
        "savings_balance_cents": "[REDACTED]",
        "currency": "[REDACTED]",
    }
    assert evidence["raw_model_transcript_persisted"] is False
    serialized_evidence = result.evidence_path.read_text()
    assert "00123" not in serialized_evidence
    assert "$1,250.50" not in serialized_evidence
    assert "{{inputs.member_id}}" in serialized_evidence
    assert (evidence_dir / artifact_path.name).exists()
    assert surface.actions[1] == ("type_text", "c1", "00123")
