from pathlib import Path
from typing import Any

import pytest

from understudy.artifact.models import CapabilityArtifact, LocatorStrategy
from understudy.surface import PlaywrightWebSurface, TargetResolutionError


FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "lookup_member_savings.hand-authored.json"
)


class FakeLocator:
    def __init__(self, count: int) -> None:
        self._count = count

    def count(self) -> int:
        return self._count


class FakeSurface(PlaywrightWebSurface):
    def __init__(self, counts: dict[str, int]) -> None:
        self._counts = counts

    def _resolve_context(
        self,
        context_ref: str,
        values: dict[str, Any],
    ) -> Any:
        return object()

    def _compile(
        self,
        root: Any,
        strategy: LocatorStrategy,
        values: dict[str, Any],
    ) -> Any:
        return FakeLocator(self._counts.get(strategy.id, 0))


@pytest.fixture(scope="module")
def artifact() -> CapabilityArtifact:
    return CapabilityArtifact.model_validate_json(
        FIXTURE_PATH.read_text()
    )


def test_primary_resolution_is_not_degraded(
    artifact: CapabilityArtifact,
) -> None:
    surface = FakeSurface({"member_id_input_accessibility": 1})

    result = surface.resolve_target(
        "member_id_input",
        artifact.targets["member_id_input"],
        {},
    )

    assert result.status == "primary"
    assert result.present
    assert not result.degraded


def test_fallback_resolution_is_degraded(
    artifact: CapabilityArtifact,
) -> None:
    surface = FakeSurface({"member_id_input_name": 1})

    result = surface.resolve_target(
        "member_id_input",
        artifact.targets["member_id_input"],
        {},
    )

    assert result.status == "degraded"
    assert result.strategy_id == "member_id_input_name"
    assert result.degraded


def test_detectable_target_may_be_absent(
    artifact: CapabilityArtifact,
) -> None:
    surface = FakeSurface({})

    result = surface.resolve_target(
        "member_not_found_message",
        artifact.targets["member_not_found_message"],
        {},
    )

    assert result.status == "absent"
    assert not result.present
    assert result.handle is None


def test_actionable_target_must_resolve_uniquely(
    artifact: CapabilityArtifact,
) -> None:
    surface = FakeSurface(
        {
            "member_id_input_accessibility": 2,
            "member_id_input_name": 0,
        }
    )

    with pytest.raises(
        TargetResolutionError,
        match="did not resolve uniquely",
    ):
        surface.resolve_target(
            "member_id_input",
            artifact.targets["member_id_input"],
            {},
        )
