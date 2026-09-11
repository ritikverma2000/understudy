from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Sequence

from playwright.sync_api import sync_playwright

from understudy.artifact.models import CapabilityArtifact
from understudy.discovery import (
    DiscoveryResult,
    DiscoveryRunner,
    PlaywrightDiscoverySurface,
    create_discovery_model,
)
from understudy.evidence import (
    redact_page_for_evidence,
    write_failure_evidence,
    write_replay_evidence,
)
from understudy.handoff import InteractiveBrowserHandoff
from understudy.replay import ReplayEngine, ReplayResult
from understudy.surface import PlaywrightWebSurface


Assignment = tuple[str, str]


def _assignment(value: str) -> Assignment:
    key, separator, assigned_value = value.partition("=")

    if not separator or not key:
        raise argparse.ArgumentTypeError(
            f"expected NAME=VALUE, received {value!r}"
        )

    return key, assigned_value


def _assignments_to_dict(
    assignments: list[Assignment],
    *,
    label: str,
) -> dict[str, str]:
    values: dict[str, str] = {}

    for key, value in assignments:
        if key in values:
            raise ValueError(f"duplicate {label} {key!r}")
        values[key] = value

    return values


def load_artifact(path: Path) -> CapabilityArtifact:
    return CapabilityArtifact.model_validate_json(path.read_text())


def execute_replay(
    artifact: CapabilityArtifact,
    *,
    inputs: dict[str, str],
    runtime: dict[str, str],
    headed: bool,
    evidence_dir: Path | None = None,
) -> ReplayResult:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=not headed)

        try:
            page = browser.new_page()
            surface = PlaywrightWebSurface(
                page,
                artifact.surface_contexts,
            )
            try:
                return ReplayEngine(artifact, surface).run(
                    inputs=inputs,
                    runtime=runtime,
                )
            except Exception as error:
                if evidence_dir is not None:
                    evidence_dir.mkdir(parents=True, exist_ok=True)
                    screenshot = evidence_dir / "replay-failure.png"
                    redact_page_for_evidence(page)
                    page.screenshot(path=str(screenshot), full_page=True)
                    write_failure_evidence(
                        artifact=artifact,
                        error=error,
                        evidence_dir=evidence_dir,
                        screenshot=screenshot,
                    )
                raise
        finally:
            browser.close()


def execute_discovery(
    template: CapabilityArtifact,
    *,
    goal: str,
    target_url: str,
    inputs: dict[str, str],
    output: Path,
    evidence_dir: Path,
    provider_name: str,
    model_name: str | None,
    headed: bool,
) -> DiscoveryResult:
    model = create_discovery_model(provider_name, model_name)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=not headed)

        try:
            page = browser.new_page()
            runner = DiscoveryRunner(
                model=model,
                surface=PlaywrightDiscoverySurface(page),
                template=template,
            )
            return runner.run(
                goal=goal,
                target_url=target_url,
                inputs=inputs,
                artifact_path=output,
                evidence_dir=evidence_dir,
            )
        finally:
            browser.close()


def execute_handoff_demo(
    *,
    target_url: str,
    evidence_dir: Path,
) -> Path:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)

        try:
            page = browser.new_page()
            page.goto(target_url)
            workspace = page.frame_locator("iframe[name='memberWorkspace']")
            expired = workspace.get_by_text(
                "Your session has expired",
                exact=True,
            )
            expired.wait_for()
            handoff = InteractiveBrowserHandoff()
            return handoff.handle(
                page=page,
                capability_id="lookup_member_savings",
                goal="Restore an expired synthetic member-servicing session",
                current_step="navigate_to_member_search",
                reason="The session requires human reauthentication.",
                resume_check=lambda: not expired.is_visible(),
                evidence_dir=evidence_dir,
            )
        finally:
            browser.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="understudy",
        description=(
            "Validate and deterministically replay Understudy capabilities."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)

    validate = commands.add_parser(
        "validate",
        help="validate a capability artifact",
    )
    validate.add_argument("artifact", type=Path)

    replay = commands.add_parser(
        "replay",
        help="replay a capability without an LLM",
    )
    replay.add_argument("artifact", type=Path)
    replay.add_argument(
        "--input",
        action="append",
        default=[],
        type=_assignment,
        metavar="NAME=VALUE",
        help="capability input; may be repeated",
    )
    replay.add_argument(
        "--runtime",
        action="append",
        default=[],
        type=_assignment,
        metavar="NAME=VALUE",
        help="runtime binding; may be repeated",
    )
    replay.add_argument(
        "--headed",
        action="store_true",
        help="show the browser while replaying",
    )
    replay.add_argument(
        "--evidence-dir",
        type=Path,
        help=(
            "write a sanitized replay record and capture a screenshot on "
            "failure"
        ),
    )

    discover = commands.add_parser(
        "discover",
        help="use an LLM to discover and record a capability",
    )
    discover.add_argument(
        "--goal",
        required=True,
        help="natural-language goal for the discovery agent",
    )
    discover.add_argument(
        "--target",
        required=True,
        help="live application entry-point URL",
    )
    discover.add_argument(
        "--template",
        required=True,
        type=Path,
        help="reviewed capability contract used for normalization",
    )
    discover.add_argument(
        "--input",
        action="append",
        default=[],
        type=_assignment,
        metavar="NAME=VALUE",
        help="discovery input; may be repeated",
    )
    discover.add_argument(
        "--output",
        type=Path,
        default=Path("capabilities/lookup_member_savings.generated.json"),
        help="generated artifact path",
    )
    discover.add_argument(
        "--evidence-dir",
        type=Path,
        default=Path("evidence"),
        help="sanitized discovery evidence directory",
    )
    discover.add_argument(
        "--provider",
        choices=("anthropic", "openrouter"),
        default="anthropic",
        help="LLM API provider used only during discovery",
    )
    discover.add_argument(
        "--model",
        help=(
            "provider model ID; defaults to claude-sonnet-4-6 for Anthropic "
            "or nex-agi/nex-n2.5-pro:free for OpenRouter"
        ),
    )
    discover.add_argument(
        "--headed",
        action="store_true",
        help="show the browser during discovery",
    )

    handoff = commands.add_parser(
        "handoff-demo",
        help="demonstrate same-session human control transfer",
    )
    handoff.add_argument(
        "--target",
        default="http://127.0.0.1:5000/app?inject=expired",
        help="expired-session demo URL",
    )
    handoff.add_argument(
        "--evidence-dir",
        type=Path,
        default=Path("evidence"),
        help="handoff evidence directory",
    )
    return parser


def _print_json(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        if args.command == "validate":
            artifact = load_artifact(args.artifact)
            _print_json(
                {
                    "status": "valid",
                    "schema_version": artifact.schema_version,
                    "capability_id": artifact.capability.id,
                    "capability_version": artifact.capability.version,
                    "steps": len(artifact.steps),
                    "targets": len(artifact.targets),
                }
            )
            return 0

        if args.command == "discover":
            template = load_artifact(args.template)
            inputs = _assignments_to_dict(args.input, label="input")
            result = execute_discovery(
                template,
                goal=args.goal,
                target_url=args.target,
                inputs=inputs,
                output=args.output,
                evidence_dir=args.evidence_dir,
                provider_name=args.provider,
                model_name=args.model,
                headed=args.headed,
            )
            _print_json(
                {
                    "status": "success",
                    "run_id": result.run_id,
                    "provider": result.provider,
                    "model": result.model,
                    "steps": result.steps,
                    "artifact": str(result.artifact_path),
                    "evidence": str(result.evidence_path),
                    "screenshot": str(result.screenshot_path),
                }
            )
            return 0

        if args.command == "handoff-demo":
            evidence_path = execute_handoff_demo(
                target_url=args.target,
                evidence_dir=args.evidence_dir,
            )
            _print_json(
                {
                    "status": "success",
                    "evidence": str(evidence_path),
                    "owner": "automation",
                }
            )
            return 0

        artifact = load_artifact(args.artifact)
        inputs = _assignments_to_dict(args.input, label="input")
        runtime = _assignments_to_dict(
            args.runtime,
            label="runtime binding",
        )
        result = execute_replay(
            artifact,
            inputs=inputs,
            runtime=runtime,
            headed=args.headed,
            evidence_dir=args.evidence_dir,
        )
        payload = asdict(result)
        if args.evidence_dir is not None:
            evidence_path = write_replay_evidence(
                artifact,
                result,
                args.evidence_dir,
            )
            payload["evidence"] = str(evidence_path)
        _print_json(payload)
        return 0
    except Exception as error:
        payload = {
            "status": "error",
            "error_type": type(error).__name__,
            "message": str(error),
        }
        for field in (
            "step_id",
            "attempts",
            "cause_type",
            "observed",
            "code",
            "category",
            "reason",
        ):
            value = getattr(error, field, None)
            if value is not None:
                payload[field] = value
        _print_json(payload)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
