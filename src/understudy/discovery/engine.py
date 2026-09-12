from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from understudy.artifact.models import (
    AccessibilityStrategy,
    CapabilityArtifact,
    DescendantSelect,
    Provenance,
    TableRelationStrategy,
)
from understudy.discovery.models import (
    ActivateDecision,
    EscalateDecision,
    FinishDecision,
    ReadDecision,
    TraceEvent,
    TypeTextDecision,
)
from understudy.discovery.provider import DiscoveryModel
from understudy.discovery.surface import PlaywrightDiscoverySurface
from understudy.evidence import redact_page_for_evidence
from understudy.replay.conditions import ConditionEvaluator
from understudy.replay.context import ReplayContext
from understudy.replay.parsers import parse_money
from understudy.surface import PlaywrightWebSurface


class DiscoveryError(RuntimeError):
    pass


@dataclass(frozen=True)
class DiscoveryResult:
    run_id: str
    artifact_path: Path
    evidence_path: Path
    screenshot_path: Path
    steps: int
    provider: str
    model: str


class DiscoveryRunner:
    expected_flow: tuple[tuple[str, str | None], ...] = (
        ("type_text", "member_id_input"),
        ("activate", "search_control"),
        ("activate", "member_result_link"),
        ("read", "savings_balance_cell"),
        ("finish", None),
    )

    def __init__(
        self,
        *,
        model: DiscoveryModel,
        surface: PlaywrightDiscoverySurface,
        template: CapabilityArtifact,
        max_steps: int = 8,
        timeout_seconds: int = 90,
    ) -> None:
        self._model = model
        self._surface = surface
        self._template = template
        self._max_steps = max_steps
        self._timeout_seconds = timeout_seconds

    def run(
        self,
        *,
        goal: str,
        target_url: str,
        inputs: dict[str, str],
        artifact_path: Path,
        evidence_dir: Path,
    ) -> DiscoveryResult:
        run_id = f"discovery-{uuid.uuid4().hex[:12]}"
        started_at = datetime.now(UTC)
        deadline = time.monotonic() + self._timeout_seconds
        history: list[TraceEvent] = []
        outputs: dict[str, object] = {}
        sensitive_read_values: set[str] = set()
        self._validate_request(goal, target_url, inputs)
        self._surface.navigate(target_url)

        for index, (expected_action, expected_target) in enumerate(
            self.expected_flow,
            start=1,
        ):
            if index > self._max_steps or time.monotonic() >= deadline:
                raise DiscoveryError("discovery stopping condition reached")

            observation = self._surface.observe()
            decision = self._model.decide(
                goal=goal,
                observation=observation,
                history=history,
            )

            if isinstance(decision, EscalateDecision):
                raise DiscoveryError(
                    f"model requested human intervention: "
                    f"{decision.decision_summary}"
                )

            if decision.type != expected_action:
                raise DiscoveryError(
                    f"policy rejected {decision.type!r}; expected "
                    f"{expected_action!r}"
                )

            actual_target = getattr(decision, "target_ref", None)
            if actual_target != expected_target:
                raise DiscoveryError(
                    f"policy rejected target {actual_target!r}; expected "
                    f"{expected_target!r}"
                )

            control_role: str | None = None
            control_name: str | None = None

            if isinstance(decision, TypeTextDecision):
                if decision.input_name not in inputs:
                    raise DiscoveryError(
                        f"missing discovery input {decision.input_name!r}"
                    )
                control = self._surface.type_text(
                    decision.control_id,
                    inputs[decision.input_name],
                )
                control_role = control.snapshot.role
                control_name = control.snapshot.name
            elif isinstance(decision, ActivateDecision):
                control = self._surface.activate(decision.control_id)
                control_role = control.snapshot.role
                control_name = control.snapshot.name
            elif isinstance(decision, ReadDecision):
                control, raw_value = self._surface.read(decision.control_id)
                sensitive_read_values.add(raw_value)
                parsed = parse_money(
                    raw_value,
                    locale="en-US",
                    expected_currency="USD",
                )
                outputs = {
                    "savings_balance_cents": parsed.amount_cents,
                    "currency": parsed.currency,
                }
                control_role = control.snapshot.role
                control_name = "[REDACTED FINANCIAL VALUE]"
            elif isinstance(decision, FinishDecision):
                self._verify_checkpoint(inputs, outputs)

            sanitized_summary = self._redact_goal(
                decision.decision_summary[:240],
                inputs,
            )
            for sensitive_value in sensitive_read_values:
                sanitized_summary = sanitized_summary.replace(
                    sensitive_value,
                    "[REDACTED FINANCIAL VALUE]",
                )

            history.append(
                TraceEvent(
                    index=index,
                    action=decision.type,
                    target_ref=actual_target,
                    control_role=control_role,
                    control_name=control_name,
                    decision_summary=sanitized_summary,
                )
            )

            if isinstance(decision, FinishDecision):
                break
        else:
            raise DiscoveryError("model did not finish the goal")

        completed_at = datetime.now(UTC)
        artifact = self._compile_artifact(run_id, completed_at, history)
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(
            json.dumps(artifact.model_dump(mode="json"), indent=2) + "\n"
        )
        evidence_dir.mkdir(parents=True, exist_ok=True)
        screenshot_path = evidence_dir / f"{run_id}-final.png"
        redact_page_for_evidence(self._surface.page)
        self._surface.page.screenshot(path=str(screenshot_path), full_page=True)
        evidence_path = evidence_dir / "discovery-run.json"
        evidence = {
            "run_id": run_id,
            "kind": "llm_discovery",
            "status": "success",
            "provider": self._model.provider_name,
            "model": self._model.model_name,
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
            "goal": self._redact_goal(goal, inputs),
            "target": self._origin(target_url),
            "steps": [event.model_dump() for event in history],
            "outputs": {
                key: "[REDACTED]" for key in outputs
            },
            "artifact": str(artifact_path),
            "screenshot": str(screenshot_path),
            "raw_model_transcript_persisted": False,
        }
        evidence_path.write_text(json.dumps(evidence, indent=2) + "\n")
        evidence_artifact = evidence_dir / artifact_path.name
        evidence_artifact.write_text(artifact_path.read_text())

        return DiscoveryResult(
            run_id=run_id,
            artifact_path=artifact_path,
            evidence_path=evidence_path,
            screenshot_path=screenshot_path,
            steps=len(history),
            provider=self._model.provider_name,
            model=self._model.model_name,
        )

    def _verify_checkpoint(
        self,
        inputs: dict[str, str],
        outputs: dict[str, object],
    ) -> None:
        context = ReplayContext(
            inputs=inputs,
            runtime={},
            outputs=outputs,
        )
        evaluator = ConditionEvaluator(
            PlaywrightWebSurface(
                self._surface.page,
                self._template.surface_contexts,
            ),
            self._template.targets,
        )
        if not evaluator.evaluate(
            self._template.success_checkpoint.condition,
            context,
        ):
            raise DiscoveryError("final capability checkpoint was not met")

    def _compile_artifact(
        self,
        run_id: str,
        recorded_at: datetime,
        history: list[TraceEvent],
    ) -> CapabilityArtifact:
        provenance = Provenance(
            source="discovery_generated",
            authorship="model_discovered",
            discovery_run_id=run_id,
            recorded_at=recorded_at.isoformat(),
            contains_runtime_values=False,
            notes=(
                "Generated from a genuine constrained LLM-driven UI run. "
                "The observed trace was normalized into the reviewed contract; "
                "raw model transcripts and runtime values were not persisted."
            ),
        )
        artifact = self._template.model_copy(
            deep=True,
            update={"provenance": provenance},
        )
        observed = {
            event.target_ref: event
            for event in history
            if event.target_ref is not None
        }

        for target_ref, event in observed.items():
            if event.control_role is None or event.control_name is None:
                continue
            target = artifact.targets[target_ref]
            primary_id = target.drift_policy.primary_strategy_id
            primary = next(
                strategy
                for strategy in target.strategies
                if strategy.id == primary_id
            )

            if isinstance(primary, AccessibilityStrategy):
                primary.role = event.control_role
                primary.name = event.control_name
            elif (
                isinstance(primary, TableRelationStrategy)
                and isinstance(primary.select, DescendantSelect)
            ):
                primary.select.role = event.control_role
                primary.select.name = event.control_name

        return CapabilityArtifact.model_validate(
            artifact.model_dump(mode="json")
        )

    def _validate_request(
        self,
        goal: str,
        target_url: str,
        inputs: dict[str, str],
    ) -> None:
        if not goal.strip():
            raise DiscoveryError("discovery goal cannot be empty")

        unknown_inputs = set(inputs) - set(self._template.inputs)
        if unknown_inputs:
            raise DiscoveryError(
                f"unknown discovery inputs: {sorted(unknown_inputs)}"
            )

        for name, definition in self._template.inputs.items():
            if definition.required and name not in inputs:
                raise DiscoveryError(
                    f"missing discovery input {name!r}"
                )
            if name in inputs and re.fullmatch(
                definition.pattern,
                inputs[name],
            ) is None:
                raise DiscoveryError(
                    f"discovery input {name!r} does not match its pattern"
                )

        policy = self._template.policy_requirements
        entry_route_ref = self._template.target.entry_point.route_ref
        if entry_route_ref not in policy.allowed_route_refs:
            raise DiscoveryError("entry route is outside the policy allowlist")

        required_actions = {
            "navigate",
            *(
                "enter_text" if action == "type_text" else action
                for action, _ in self.expected_flow
                if action != "finish"
            ),
        }
        disallowed_actions = required_actions - set(
            policy.allowed_action_types
        )
        if disallowed_actions:
            raise DiscoveryError(
                "discovery requires disallowed actions: "
                f"{sorted(disallowed_actions)}"
            )

        origin = self._origin(target_url)
        runtime = {
            name: origin
            for name in self._template.target.runtime_bindings
        }
        context = ReplayContext(inputs=inputs, runtime=runtime)
        allowed_origins = {
            self._origin(context.render(allowed))
            for allowed in policy.allowed_origins
        }
        if origin not in allowed_origins:
            raise DiscoveryError("target is outside allowed origins")

        expected_entry = context.render(
            self._template.target.routes[entry_route_ref].pattern
        )
        if target_url != expected_entry:
            raise DiscoveryError(
                "target does not match the reviewed entry-point route"
            )

    @staticmethod
    def _redact_goal(goal: str, inputs: dict[str, str]) -> str:
        redacted = goal
        for name, value in inputs.items():
            redacted = redacted.replace(value, f"{{{{inputs.{name}}}}}")
        return redacted

    @staticmethod
    def _origin(url: str) -> str:
        parsed = urlsplit(url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise DiscoveryError("target must be an HTTP(S) URL without credentials")
        return f"{parsed.scheme}://{parsed.netloc}"
