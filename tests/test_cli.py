import json
from pathlib import Path
from typing import Any

import pytest

from understudy import cli
from understudy.discovery import DiscoveryResult
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
        evidence_dir: Path | None,
    ) -> ReplayResult:
        captured.update(
            inputs=inputs,
            runtime=runtime,
            headed=headed,
            evidence_dir=evidence_dir,
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
        "evidence_dir": None,
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


def test_discover_passes_goal_and_target_to_boundary(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, Any] = {}

    def fake_discovery(template: Any, **kwargs: Any) -> DiscoveryResult:
        captured.update(kwargs)
        return DiscoveryResult(
            run_id="discovery-test",
            artifact_path=tmp_path / "generated.json",
            evidence_path=tmp_path / "discovery-run.json",
            screenshot_path=tmp_path / "final.png",
            steps=5,
            provider="test-provider",
            model="test-model",
        )

    monkeypatch.setattr(cli, "execute_discovery", fake_discovery)
    output = tmp_path / "generated.json"
    evidence = tmp_path / "evidence"
    exit_code = cli.main(
        [
            "discover",
            "--goal",
            "Look up member 00123",
            "--target",
            "http://127.0.0.1:5000/app",
            "--template",
            str(FIXTURE_PATH),
            "--input",
            "member_id=00123",
            "--output",
            str(output),
            "--evidence-dir",
            str(evidence),
            "--model",
            "test-model",
            "--provider",
            "openrouter",
        ]
    )

    assert exit_code == 0
    assert captured["goal"] == "Look up member 00123"
    assert captured["target_url"] == "http://127.0.0.1:5000/app"
    assert captured["inputs"] == {"member_id": "00123"}
    assert captured["provider_name"] == "openrouter"
    assert output_json(capsys)["run_id"] == "discovery-test"


def test_handoff_demo_reports_returned_control(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    evidence_path = tmp_path / "handoff-run.json"
    monkeypatch.setattr(
        cli,
        "execute_handoff_demo",
        lambda **kwargs: evidence_path,
    )

    exit_code = cli.main(
        [
            "handoff-demo",
            "--target",
            "http://127.0.0.1:5000/app?inject=expired",
            "--evidence-dir",
            str(tmp_path),
        ]
    )

    assert exit_code == 0
    assert output_json(capsys) == {
        "status": "success",
        "evidence": str(evidence_path),
        "owner": "automation",
    }
