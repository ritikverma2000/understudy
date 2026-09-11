from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from playwright.sync_api import Page


ControlOwner = Literal["automation", "human"]


@dataclass(frozen=True)
class ControlTransferEvent:
    at: str
    from_owner: ControlOwner
    to_owner: ControlOwner
    actor: str
    reason: str


@dataclass
class HandoffSession:
    session_id: str
    capability_id: str
    goal: str
    current_step: str
    reason: str
    owner: ControlOwner = "automation"
    transfers: list[ControlTransferEvent] = field(default_factory=list)

    def cede_to_human(self, *, actor: str = "system") -> None:
        if self.owner != "automation":
            raise RuntimeError("automation does not own the session")
        self.transfers.append(
            ControlTransferEvent(
                at=datetime.now(UTC).isoformat(),
                from_owner="automation",
                to_owner="human",
                actor=actor,
                reason=self.reason,
            )
        )
        self.owner = "human"

    def resume_automation(
        self,
        *,
        actor: str,
        reason: str,
    ) -> None:
        if self.owner != "human":
            raise RuntimeError("human does not own the session")
        self.transfers.append(
            ControlTransferEvent(
                at=datetime.now(UTC).isoformat(),
                from_owner="human",
                to_owner="automation",
                actor=actor,
                reason=reason,
            )
        )
        self.owner = "automation"


class InteractiveBrowserHandoff:
    def __init__(
        self,
        *,
        input_fn: Callable[[str], str] = input,
        output_fn: Callable[[str], None] = print,
    ) -> None:
        self._input = input_fn
        self._output = output_fn

    def handle(
        self,
        *,
        page: Page,
        capability_id: str,
        goal: str,
        current_step: str,
        reason: str,
        resume_check: Callable[[], bool],
        evidence_dir: Path,
        operator_id: str = "local-operator",
    ) -> Path:
        session = HandoffSession(
            session_id=f"handoff-{uuid.uuid4().hex[:12]}",
            capability_id=capability_id,
            goal=goal,
            current_step=current_step,
            reason=reason,
        )
        evidence_dir.mkdir(parents=True, exist_ok=True)
        before = evidence_dir / f"{session.session_id}-before.png"
        after = evidence_dir / f"{session.session_id}-after.png"
        page.screenshot(path=str(before), full_page=True)
        human_actions: list[dict[str, str]] = []
        binding_name = f"__understudyCapture_{uuid.uuid4().hex}"

        def capture(source: object, event: dict[str, str]) -> None:
            human_actions.append(event)

        page.expose_binding(binding_name, capture)
        listener = """binding => {
          if (window.__understudyHandoffListener) return;
          window.__understudyHandoffListener = true;
          const describe = element => ({
            event: 'activate',
            role: element.getAttribute('role') ||
              (element.tagName.toLowerCase() === 'a' ? 'link' :
               element.tagName.toLowerCase()),
            name: (element.innerText || element.getAttribute('name') || '')
              .trim().replace(/\\s+/g, ' ').slice(0, 120)
          });
          document.addEventListener('click', event => {
            window[binding](describe(event.target.closest('a,button,input') ||
              event.target));
          }, true);
          document.addEventListener('input', event => {
            window[binding]({
              event: 'input',
              role: event.target.tagName.toLowerCase(),
              name: event.target.getAttribute('name') || ''
            });
          }, true);
        }"""
        for frame in page.frames:
            frame.evaluate(listener, binding_name)

        session.cede_to_human()
        self._output(
            json.dumps(
                {
                    "type": "intervention_required",
                    "session_id": session.session_id,
                    "capability_id": capability_id,
                    "current_step": current_step,
                    "reason": reason,
                    "owner": session.owner,
                    "screenshot": str(before),
                },
                indent=2,
            )
        )
        self._input(
            "Automation paused. Operate the open browser, then press Enter "
            "to return control: "
        )
        page.wait_for_timeout(150)

        if not resume_check():
            raise RuntimeError("human handoff resume condition was not met")

        session.resume_automation(
            actor=operator_id,
            reason="operator signaled completion; resume condition verified",
        )
        page.screenshot(path=str(after), full_page=True)
        evidence_path = evidence_dir / "handoff-run.json"
        evidence_path.write_text(
            json.dumps(
                {
                    **asdict(session),
                    "human_actions": human_actions,
                    "before_screenshot": str(before),
                    "after_screenshot": str(after),
                    "sensitive_input_values_recorded": False,
                },
                indent=2,
            )
            + "\n"
        )
        return evidence_path
