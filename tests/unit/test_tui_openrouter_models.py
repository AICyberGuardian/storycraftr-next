from __future__ import annotations

from typing import Any

from storycraftr.llm.openrouter_discovery import OpenRouterModelRecord
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
                "context_length": 32000,
                "pricing": {"prompt": "0", "completion": "0"},
                "top_provider": {"max_completion_tokens": 1024},
            },
            {
                "id": "alpha/free-model",
                "name": "Alpha Free",
                "context_length": 64000,
                "pricing": {"prompt": "0.0", "completion": "$0"},
                "top_provider": {"max_completion_tokens": 2048},
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
        OpenRouterModel(
            model_id="alpha/free-model",
            label="Alpha Free",
            context_length=64000,
            max_completion_tokens=2048,
        ),
        OpenRouterModel(
            model_id="zeta/free-model",
            label="Zeta Free",
            context_length=32000,
            max_completion_tokens=1024,
        ),
    ]


def test_fetch_free_openrouter_models_parses_response(monkeypatch) -> None:
    monkeypatch.setattr(
        "storycraftr.tui.openrouter_models.get_free_models",
        lambda force_refresh=False: [
            OpenRouterModelRecord(
                model_id="provider/model-free",
                label="Provider Model Free",
                pricing_prompt=0.0,
                pricing_completion=0.0,
                context_length=32768,
                max_completion_tokens=2048,
                supported_parameters=(),
            )
        ],
    )

    models = fetch_free_openrouter_models()

    assert [model.model_id for model in models] == ["provider/model-free"]
    assert models[0].context_length == 32768
    assert models[0].max_completion_tokens == 2048
