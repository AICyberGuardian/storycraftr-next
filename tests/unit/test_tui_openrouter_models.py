from __future__ import annotations

from typing import Any

from storycraftr.tui.openrouter_models import (
    OpenRouterModel,
    fetch_free_openrouter_models,
    normalize_free_models,
)


def test_normalize_free_models_filters_and_sorts() -> None:
    payload: dict[str, Any] = {
        "data": [
            {
                "id": "zeta/free-model",
                "name": "Zeta Free",
                "pricing": {"prompt": "0", "completion": "0"},
            },
            {
                "id": "alpha/free-model",
                "name": "Alpha Free",
                "pricing": {"prompt": "0.0", "completion": "$0"},
            },
            {
                "id": "paid/model",
                "name": "Paid",
                "pricing": {"prompt": "0.000001", "completion": "0.000001"},
            },
        ]
    }

    models = normalize_free_models(payload)

    assert models == [
        OpenRouterModel(model_id="alpha/free-model", label="Alpha Free"),
        OpenRouterModel(model_id="zeta/free-model", label="Zeta Free"),
    ]


def test_fetch_free_openrouter_models_parses_response(monkeypatch) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {
                "data": [
                    {
                        "id": "provider/model-free",
                        "name": "Provider Model Free",
                        "pricing": {"prompt": "0", "completion": "0"},
                    }
                ]
            }

    def fake_get(url: str, headers: dict[str, str], timeout: int):
        assert "openrouter.ai/api/v1/models" in url
        assert headers.get("Accept") == "application/json"
        assert timeout == 10
        return FakeResponse()

    monkeypatch.setattr("storycraftr.tui.openrouter_models.requests.get", fake_get)

    models = fetch_free_openrouter_models()

    assert [model.model_id for model in models] == ["provider/model-free"]
