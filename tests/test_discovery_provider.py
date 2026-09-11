import io
import json
import urllib.request
from typing import Any

import pytest

from understudy.discovery.models import ControlSnapshot, Observation
from understudy.discovery.provider import (
    ModelResponseError,
    OpenRouterDiscoveryModel,
    create_discovery_model,
)


def test_openrouter_requires_its_own_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    with pytest.raises(ModelResponseError, match="OPENROUTER_API_KEY"):
        OpenRouterDiscoveryModel()


def test_provider_factory_uses_provider_specific_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    model = create_discovery_model("openrouter")

    assert model.provider_name == "openrouter"
    assert model.model_name == "nex-agi/nex-n2.5-pro:free"


def test_openrouter_sends_and_parses_function_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    response_payload = {
        "choices": [
            {
                "message": {
                    "tool_calls": [
                        {
                            "type": "function",
                            "function": {
                                "name": "choose_action",
                                "arguments": json.dumps(
                                    {
                                        "decision": json.dumps(
                                            {
                                                "type": "finish",
                                                "decision_summary": (
                                                    "The requested value was read."
                                                ),
                                            }
                                        )
                                    }
                                ),
                            },
                        }
                    ]
                }
            }
        ]
    }

    def fake_urlopen(
        request: urllib.request.Request,
        timeout: int,
    ) -> io.BytesIO:
        captured["request"] = request
        captured["timeout"] = timeout
        return io.BytesIO(json.dumps(response_payload).encode("utf-8"))

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    model = OpenRouterDiscoveryModel(
        api_key="secret-test-key",
        timeout_seconds=12,
    )
    decision = model.decide(
        goal="Read a synthetic Savings balance",
        observation=Observation(
            url="http://example.test/app",
            title="Synthetic CoreView",
            controls=[
                ControlSnapshot(
                    id="c1",
                    role="cell",
                    name="[REDACTED]",
                    context="frame:1",
                )
            ],
        ),
        history=[],
    )

    request = captured["request"]
    payload = json.loads(request.data)
    assert request.full_url == OpenRouterDiscoveryModel.endpoint
    assert request.get_header("Authorization") == "Bearer secret-test-key"
    assert captured["timeout"] == 12
    assert payload["model"] == "nex-agi/nex-n2.5-pro:free"
    assert payload["tools"][0]["function"]["name"] == "choose_action"
    assert payload["tool_choice"]["function"]["name"] == "choose_action"
    assert payload["provider"]["require_parameters"] is True
    assert decision.type == "finish"
