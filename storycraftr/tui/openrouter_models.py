from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"


@dataclass(frozen=True)
class OpenRouterModel:
    """Normalized OpenRouter model metadata used by the TUI."""

    model_id: str
    label: str


def _parse_price(value: Any) -> float | None:
    """Parse OpenRouter pricing values that may be numeric strings or '$' prefixed."""

    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.startswith("$"):
        text = text[1:]
    try:
        return float(text)
    except ValueError:
        return None


def _is_free_model(payload: dict[str, Any]) -> bool:
    """Treat a model as free when both prompt and completion token prices are zero."""

    pricing = payload.get("pricing")
    if not isinstance(pricing, dict):
        return False

    prompt_price = _parse_price(pricing.get("prompt"))
    completion_price = _parse_price(pricing.get("completion"))
    if prompt_price is None or completion_price is None:
        return False

    return prompt_price == 0.0 and completion_price == 0.0


def normalize_free_models(payload: dict[str, Any]) -> list[OpenRouterModel]:
    """Extract and sort free OpenRouter models from a `/models` API payload."""

    raw_models = payload.get("data")
    if not isinstance(raw_models, list):
        return []

    models: list[OpenRouterModel] = []
    for raw in raw_models:
        if not isinstance(raw, dict) or not _is_free_model(raw):
            continue

        model_id = str(raw.get("id", "")).strip()
        if not model_id:
            continue

        name = str(raw.get("name", "")).strip()
        label = name or model_id
        models.append(OpenRouterModel(model_id=model_id, label=label))

    # Keep deterministic order for UX and validation checks.
    models.sort(key=lambda model: (model.model_id.lower(), model.label.lower()))
    return models


def fetch_free_openrouter_models(
    *,
    api_key: str | None = None,
    timeout_seconds: int = 10,
) -> list[OpenRouterModel]:
    """Fetch free model metadata from OpenRouter's public models endpoint."""

    headers = {
        "Accept": "application/json",
        "User-Agent": "storycraftr-tui/0.1",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    response = requests.get(
        OPENROUTER_MODELS_URL,
        headers=headers,
        timeout=timeout_seconds,
    )
    response.raise_for_status()

    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Unexpected OpenRouter models response shape.")
    return normalize_free_models(payload)
