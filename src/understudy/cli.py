from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Sequence

from playwright.sync_api import sync_playwright

from understudy.artifact.models import CapabilityArtifact
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
) -> ReplayResult:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=not headed)

        try:
            page = browser.new_page()
            surface = PlaywrightWebSurface(
                page,
                artifact.surface_contexts,
            )
            return ReplayEngine(artifact, surface).run(
                inputs=inputs,
                runtime=runtime,
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
    return parser


def _print_json(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        artifact = load_artifact(args.artifact)

        if args.command == "validate":
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
        )
        _print_json(asdict(result))
        return 0
    except Exception as error:
        _print_json(
            {
                "status": "error",
                "error_type": type(error).__name__,
                "message": str(error),
            }
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
