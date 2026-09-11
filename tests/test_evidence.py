import json
from pathlib import Path

from understudy.artifact.models import CapabilityArtifact
from understudy.evidence import write_replay_evidence
from understudy.replay import ReplayResult


FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "lookup_member_savings.hand-authored.json"
)


def test_replay_evidence_redacts_sensitive_values(tmp_path: Path) -> None:
    artifact = CapabilityArtifact.model_validate_json(FIXTURE_PATH.read_text())
    result = ReplayResult(
        status="success",
        outputs={
            "savings_balance_cents": 125050,
            "currency": "USD",
        },
        completed_steps=tuple(step.id for step in artifact.steps),
    )

    evidence_path = write_replay_evidence(artifact, result, tmp_path)
    evidence = json.loads(evidence_path.read_text())

    assert evidence["outputs"] == {
        "savings_balance_cents": "[REDACTED]",
        "currency": "USD",
    }
    assert evidence["runtime_inputs_persisted"] is False
    assert evidence["model_in_decision_loop"] is False
    assert evidence["completed_steps"][0]["action_type"] == "navigate"
