from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from storycraftr.llm.openrouter_discovery import (
    fetch_openrouter_models as _fetch_catalog,
    get_free_models,
)


@dataclass(frozen=True)
class OpenRouterModel:
    """Normalized OpenRouter model metadata used by the TUI."""

    model_id: str
    label: str
    context_length: int
    max_completion_tokens: int | None


def normalize_free_models(payload: dict[str, object]) -> list[OpenRouterModel]:
    """Extract and sort free OpenRouter models from a `/models` API payload."""

    rows = payload.get("data")
    if not isinstance(rows, list):
        return []

    models: list[OpenRouterModel] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        pricing = row.get("pricing")
        if not isinstance(pricing, dict):
            continue

        prompt_price = _parse_price(pricing.get("prompt"))
        completion_price = _parse_price(pricing.get("completion"))
        if prompt_price != 0.0 or completion_price != 0.0:
            continue

        model_id = str(row.get("id", "")).strip()
        if not model_id:
            continue

        label = str(row.get("name", "")).strip() or model_id
        context_length = _parse_positive_int(row.get("context_length")) or 8192

        top_provider = row.get("top_provider")
        max_completion_tokens = None
        if isinstance(top_provider, dict):
            max_completion_tokens = _parse_positive_int(
                top_provider.get("max_completion_tokens")
            )

        models.append(
            OpenRouterModel(
                model_id=model_id,
                label=label,
                context_length=context_length,
                max_completion_tokens=max_completion_tokens,
            )
        )

    models.sort(key=lambda model: (model.model_id.lower(), model.label.lower()))
    return models


def _parse_price(value: Any) -> float | None:
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


def _parse_positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def fetch_free_openrouter_models(
    *,
    api_key: str | None = None,
    force_refresh: bool = False,
    timeout_seconds: int = 10,
) -> list[OpenRouterModel]:
    """Fetch free model metadata from OpenRouter's public models endpoint."""

    _ = api_key
    if force_refresh:
        _fetch_catalog(timeout_seconds=timeout_seconds)

    models = get_free_models(force_refresh=False)
    return [
        OpenRouterModel(
            model_id=model.model_id,
            label=model.label,
            context_length=model.context_length,
            max_completion_tokens=model.max_completion_tokens,
        )
        for model in models
    ]
