import json
import os
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Browser, sync_playwright
from werkzeug.serving import BaseWSGIServer, make_server

from target_app import create_app
from understudy.artifact.models import CapabilityArtifact
from understudy.handoff import InteractiveBrowserHandoff
from understudy.replay import ReplayEngine
from understudy.surface import PlaywrightWebSurface


pytestmark = pytest.mark.skipif(
    os.environ.get("UNDERSTUDY_E2E") != "1",
    reason="set UNDERSTUDY_E2E=1 to run browser integration tests",
)


FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "lookup_member_savings.hand-authored.json"
)


@pytest.fixture(scope="module")
def artifact() -> CapabilityArtifact:
    return CapabilityArtifact.model_validate_json(
        FIXTURE_PATH.read_text()
    )


@pytest.fixture(scope="module")
def target_app_url() -> Iterator[str]:
    server: BaseWSGIServer = make_server(
        "127.0.0.1",
        0,
        create_app(testing=True),
    )
    thread = threading.Thread(target=server.serve_forever)
    thread.start()

    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join()


@pytest.fixture(scope="module")
def browser() -> Iterator[Browser]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        yield browser
        browser.close()


def test_resolves_primary_accessibility_strategy(
    artifact: CapabilityArtifact,
    target_app_url: str,
    browser: Browser,
) -> None:
    page = browser.new_page()
    surface = PlaywrightWebSurface(page, artifact.surface_contexts)
    surface.navigate(f"{target_app_url}/app")

    resolved = surface.resolve_target(
        "member_id_input",
        artifact.targets["member_id_input"],
        {"inputs": {"member_id": "00123"}},
    )

    assert resolved.status == "primary"
    assert resolved.strategy_id == "member_id_input_accessibility"
    assert resolved.match_count == 1
    page.close()


def test_uses_fallback_and_marks_resolution_degraded(
    artifact: CapabilityArtifact,
    target_app_url: str,
    browser: Browser,
) -> None:
    page = browser.new_page()
    surface = PlaywrightWebSurface(page, artifact.surface_contexts)
    surface.navigate(f"{target_app_url}/app")
    target = artifact.targets["member_id_input"].model_copy(deep=True)
    primary = target.strategies[0]
    primary.name = "Changed label"  # type: ignore[union-attr]

    resolved = surface.resolve_target(
        "member_id_input",
        target,
        {"inputs": {"member_id": "00123"}},
    )

    assert resolved.status == "degraded"
    assert resolved.strategy_id == "member_id_input_name"
    page.close()


def test_detectable_target_can_be_absent(
    artifact: CapabilityArtifact,
    target_app_url: str,
    browser: Browser,
) -> None:
    page = browser.new_page()
    surface = PlaywrightWebSurface(page, artifact.surface_contexts)
    surface.navigate(f"{target_app_url}/app")

    resolved = surface.resolve_target(
        "member_not_found_message",
        artifact.targets["member_not_found_message"],
        {"inputs": {"member_id": "00123"}},
    )

    assert resolved.status == "absent"
    assert resolved.handle is None
    page.close()


def test_resolves_relational_table_targets(
    artifact: CapabilityArtifact,
    target_app_url: str,
    browser: Browser,
) -> None:
    page = browser.new_page()
    surface = PlaywrightWebSurface(page, artifact.surface_contexts)
    values = {"inputs": {"member_id": "00123"}}
    surface.navigate(f"{target_app_url}/app")

    member_id = surface.resolve_target(
        "member_id_input",
        artifact.targets["member_id_input"],
        values,
    )
    assert member_id.handle is not None
    member_id.handle.fill("00123")

    search = surface.resolve_target(
        "search_control",
        artifact.targets["search_control"],
        values,
    )
    assert search.handle is not None
    search.handle.click()

    # The legacy onclick invokes form.submit(), which is not guaranteed to
    # participate in Playwright's click auto-waiting. At a step boundary the
    # replay engine will poll the postcondition; this test performs that same
    # synchronization explicitly before resolving the next target.
    page.frame_locator("iframe[name='memberWorkspace']").get_by_role(
        "heading",
        name="Member Search Results",
        exact=True,
    ).wait_for()

    result = surface.resolve_target(
        "member_result_link",
        artifact.targets["member_result_link"],
        values,
    )
    assert result.strategy_id == "member_result_table_relation"
    assert result.handle is not None
    result.handle.click()

    page.frame_locator("iframe[name='memberWorkspace']").get_by_role(
        "heading",
        name="Member Details",
        exact=True,
    ).wait_for()

    balance = surface.resolve_target(
        "savings_balance_cell",
        artifact.targets["savings_balance_cell"],
        values,
    )
    assert balance.strategy_id == "savings_balance_table_relation"
    assert balance.handle is not None
    assert balance.handle.inner_text() == "$1,250.50"
    page.close()


def test_replay_engine_completes_success_workflow(
    artifact: CapabilityArtifact,
    target_app_url: str,
    browser: Browser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    page = browser.new_page()
    surface = PlaywrightWebSurface(page, artifact.surface_contexts)

    result = ReplayEngine(artifact, surface).run(
        inputs={"member_id": "00123"},
        runtime={"base_url": target_app_url},
    )

    assert result.status == "success"
    assert result.outputs == {
        "savings_balance_cents": 125050,
        "currency": "USD",
    }
    page.close()


def test_replay_engine_returns_not_found_business_outcome(
    artifact: CapabilityArtifact,
    target_app_url: str,
    browser: Browser,
) -> None:
    page = browser.new_page()
    surface = PlaywrightWebSurface(page, artifact.surface_contexts)

    result = ReplayEngine(artifact, surface).run(
        inputs={"member_id": "99999"},
        runtime={"base_url": target_app_url},
    )

    assert result.status == "business_outcome"
    assert result.condition_code == "MEMBER_NOT_FOUND"
    page.close()


def test_handoff_keeps_same_live_browser_session(
    target_app_url: str,
    browser: Browser,
    tmp_path: Path,
) -> None:
    page = browser.new_page()
    original_page = page
    page.goto(f"{target_app_url}/app?inject=expired")
    workspace = page.frame_locator("iframe[name='memberWorkspace']")
    expired = workspace.get_by_text(
        "Your session has expired",
        exact=True,
    )
    expired.wait_for()

    def human_operator(prompt: str) -> str:
        workspace.get_by_role(
            "link",
            name="Resume session",
            exact=True,
        ).click()
        return ""

    handoff = InteractiveBrowserHandoff(
        input_fn=human_operator,
        output_fn=lambda message: None,
    )
    evidence_path = handoff.handle(
        page=page,
        capability_id="lookup_member_savings",
        goal="Restore an expired synthetic session",
        current_step="navigate_to_member_search",
        reason="Human reauthentication is required.",
        resume_check=lambda: not expired.is_visible(),
        evidence_dir=tmp_path,
    )

    assert page is original_page
    workspace.get_by_role(
        "heading",
        name="Member Search",
        exact=True,
    ).wait_for()
    evidence = json.loads(evidence_path.read_text())
    assert evidence["owner"] == "automation"
    assert [event["to_owner"] for event in evidence["transfers"]] == [
        "human",
        "automation",
    ]
    assert any(
        action["name"] == "Resume session"
        for action in evidence["human_actions"]
    )
    assert evidence["sensitive_input_values_recorded"] is False
    page.close()
