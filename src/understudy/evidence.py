from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from understudy.artifact.models import CapabilityArtifact
from understudy.replay import ReplayResult


def redact_page_for_evidence(page: Any) -> None:
    """Remove value-bearing UI content before a screenshot is persisted."""
    for frame in getattr(page, "frames", []):
        frame.locator("input, textarea, select").evaluate_all(
            """elements => elements.forEach(element => {
              if ('value' in element) element.value = '[REDACTED]';
            })"""
        )
        frame.locator("td").evaluate_all(
            "elements => elements.forEach(element => "
            "element.textContent = '[REDACTED]')"
        )


def write_replay_evidence(
    artifact: CapabilityArtifact,
    result: ReplayResult,
    evidence_dir: Path,
) -> Path:
    """Persist a sanitized, structured replay record.

    Runtime inputs are deliberately omitted. Outputs follow each declared
    output's log policy, so sensitive values remain return-only.
    """
    run_id = f"replay-{uuid.uuid4().hex[:12]}"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    path = evidence_dir / f"{run_id}.json"
    steps_by_id = {step.id: step for step in artifact.steps}
    completed = []

    for step_id in result.completed_steps:
        step = steps_by_id[step_id]
        completed.append(
            {
                "step_id": step.id,
                "intent": step.intent,
                "action_type": step.action.type,
                "risk": step.risk,
                "outcome": "postcondition_met",
                "why": "artifact-defined intent and policy-approved action",
            }
        )

    outputs: dict[str, Any] = {}
    for name, value in result.outputs.items():
        definition = artifact.outputs[name]
        outputs[name] = value if definition.log_policy == "allow" else "[REDACTED]"

    payload = {
        "run_id": run_id,
        "kind": "deterministic_replay",
        "recorded_at": datetime.now(UTC).isoformat(),
        "capability_id": artifact.capability.id,
        "capability_version": artifact.capability.version,
        "status": result.status,
        "condition_code": result.condition_code,
        "message": result.message,
        "completed_steps": completed,
        "outputs": outputs,
        "runtime_inputs_persisted": False,
        "model_in_decision_loop": False,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n")
    return path


def write_failure_evidence(
    *,
    artifact: CapabilityArtifact,
    error: Exception,
    evidence_dir: Path,
    screenshot: Path | None,
) -> Path:
    """Persist failure metadata without raw inputs or page content."""
    run_id = f"failure-{uuid.uuid4().hex[:12]}"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    path = evidence_dir / f"{run_id}.json"
    payload = {
        "run_id": run_id,
        "kind": "replay_failure",
        "recorded_at": datetime.now(UTC).isoformat(),
        "capability_id": artifact.capability.id,
        "status": "error",
        "error_type": type(error).__name__,
        "message": _safe_failure_message(error),
        "step_id": getattr(error, "step_id", None),
        "attempts": getattr(error, "attempts", None),
        "cause_type": getattr(error, "cause_type", None),
        "condition_code": getattr(error, "code", None),
        "category": getattr(error, "category", None),
        "screenshot": str(screenshot) if screenshot else None,
        "runtime_inputs_persisted": False,
        "dom_snapshot_persisted": False,
        "model_in_decision_loop": False,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n")
    return path


def _safe_failure_message(error: Exception) -> str:
    """Describe a failure without serializing an arbitrary exception value."""
    step_id = getattr(error, "step_id", None)
    attempts = getattr(error, "attempts", None)
    cause_type = getattr(error, "cause_type", None)
    if step_id is not None:
        return (
            f"Step {step_id!r} failed after {attempts} attempt(s); "
            f"cause={cause_type or 'unknown'}"
        )

    code = getattr(error, "code", None)
    category = getattr(error, "category", None)
    if code is not None:
        return f"Runtime condition {code!r} stopped replay ({category or 'review'})"

    return "Raw exception text withheld by evidence policy"
