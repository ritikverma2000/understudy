import json
from pathlib import Path
from typing import Any

import pytest

from understudy import cli
from understudy.replay import ReplayResult


FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "lookup_member_savings.hand-authored.json"
)


def output_json(capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    return json.loads(capsys.readouterr().out)


def test_validate_prints_artifact_summary(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = cli.main(["validate", str(FIXTURE_PATH)])

    assert exit_code == 0
    assert output_json(capsys) == {
        "status": "valid",
        "schema_version": "1.0.0",
        "capability_id": "lookup_member_savings",
        "capability_version": "1.0.0",
        "steps": 5,
        "targets": 12,
    }


def test_replay_passes_arguments_to_browser_boundary(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_execute_replay(
        artifact: Any,
        *,
        inputs: dict[str, str],
        runtime: dict[str, str],
        headed: bool,
    ) -> ReplayResult:
        captured.update(
            inputs=inputs,
            runtime=runtime,
            headed=headed,
            capability_id=artifact.capability.id,
        )
        return ReplayResult(
            status="success",
            outputs={
                "savings_balance_cents": 125050,
                "currency": "USD",
            },
            completed_steps=("read_savings_balance",),
        )

    monkeypatch.setattr(cli, "execute_replay", fake_execute_replay)

    exit_code = cli.main(
        [
            "replay",
            str(FIXTURE_PATH),
            "--input",
            "member_id=00123",
            "--runtime",
            "base_url=http://127.0.0.1:5000",
            "--headed",
        ]
    )

    assert exit_code == 0
    assert captured == {
        "inputs": {"member_id": "00123"},
        "runtime": {"base_url": "http://127.0.0.1:5000"},
        "headed": True,
        "capability_id": "lookup_member_savings",
    }
    assert output_json(capsys)["status"] == "success"


def test_business_outcome_is_serialized(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli,
        "execute_replay",
        lambda *args, **kwargs: ReplayResult(
            status="business_outcome",
            outputs={},
            completed_steps=("activate_member_search",),
            message="No member exists for the supplied identifier.",
            condition_code="MEMBER_NOT_FOUND",
        ),
    )

    exit_code = cli.main(
        [
            "replay",
            str(FIXTURE_PATH),
            "--input",
            "member_id=99999",
            "--runtime",
            "base_url=http://127.0.0.1:5000",
        ]
    )

    assert exit_code == 0
    payload = output_json(capsys)
    assert payload["status"] == "business_outcome"
    assert payload["condition_code"] == "MEMBER_NOT_FOUND"


def test_execution_error_is_structured_json(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args: Any, **kwargs: Any) -> ReplayResult:
        raise RuntimeError("browser unavailable")

    monkeypatch.setattr(cli, "execute_replay", fail)

    exit_code = cli.main(
        [
            "replay",
            str(FIXTURE_PATH),
            "--input",
            "member_id=00123",
            "--runtime",
            "base_url=http://127.0.0.1:5000",
        ]
    )

    assert exit_code == 1
    assert output_json(capsys) == {
        "status": "error",
        "error_type": "RuntimeError",
        "message": "browser unavailable",
    }


def test_missing_artifact_is_structured_json(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    exit_code = cli.main(["validate", str(tmp_path / "missing.json")])

    assert exit_code == 1
    assert output_json(capsys)["error_type"] == "FileNotFoundError"


def test_malformed_assignment_is_a_usage_error() -> None:
    with pytest.raises(SystemExit) as captured:
        cli.main(
            [
                "replay",
                str(FIXTURE_PATH),
                "--input",
                "member_id",
            ]
        )

    assert captured.value.code == 2


def test_duplicate_assignment_is_rejected(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def should_not_run(*args: Any, **kwargs: Any) -> ReplayResult:
        nonlocal called
        called = True
        raise AssertionError("should not run")

    monkeypatch.setattr(cli, "execute_replay", should_not_run)

    exit_code = cli.main(
        [
            "replay",
            str(FIXTURE_PATH),
            "--input",
            "member_id=00123",
            "--input",
            "member_id=99999",
        ]
    )

    assert exit_code == 1
    assert not called
    assert "duplicate input" in output_json(capsys)["message"]
