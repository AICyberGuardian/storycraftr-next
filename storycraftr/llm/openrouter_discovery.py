from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import requests

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
OPENROUTER_DISCOVERY_CACHE_TTL_SECONDS = 6 * 60 * 60
_CACHE_FILENAME = "openrouter-models-cache.json"


@dataclass(frozen=True)
class OpenRouterModelLimits:
    """Model limits used by budgeting and completion reserve clamping."""

    context_length: int
    max_completion_tokens: int | None


@dataclass(frozen=True)
class OpenRouterModelRecord:
    """Normalized OpenRouter model metadata used by runtime discovery."""

    model_id: str
    label: str
    pricing_prompt: float | None
    pricing_completion: float | None
    context_length: int
    max_completion_tokens: int | None
    supported_parameters: tuple[str, ...]

    @property
    def is_free(self) -> bool:
        return self.pricing_prompt == 0.0 and self.pricing_completion == 0.0


@dataclass(frozen=True)
class OpenRouterCatalog:
    """Runtime catalog plus fetch timestamp metadata."""

    fetched_at: float
    models: tuple[OpenRouterModelRecord, ...]


@dataclass(frozen=True)
class OpenRouterCacheMetadata:
    """User-local cache metadata exposed for diagnostics views."""

    cache_path: str
    cache_exists: bool
    cache_status: str
    fetched_at: float | None
    age_seconds: float | None
    ttl_seconds: int
    free_model_count: int
    total_model_count: int


def _cache_path() -> Path:
    cache_dir = Path.home() / ".storycraftr"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / _CACHE_FILENAME


def _parse_float(value: Any) -> float | None:
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


def _parse_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _as_model_record(payload: dict[str, Any]) -> OpenRouterModelRecord | None:
    model_id = str(payload.get("id", "")).strip()
    if not model_id:
        return None

    label = str(payload.get("name", "")).strip() or model_id
    pricing = payload.get("pricing")
    pricing_prompt = None
    pricing_completion = None
    if isinstance(pricing, dict):
        pricing_prompt = _parse_float(pricing.get("prompt"))
        pricing_completion = _parse_float(pricing.get("completion"))

    context_length = _parse_int(payload.get("context_length")) or 8192

    top_provider = payload.get("top_provider")
    max_completion_tokens = None
    if isinstance(top_provider, dict):
        max_completion_tokens = _parse_int(top_provider.get("max_completion_tokens"))

    supported_parameters_raw = payload.get("supported_parameters")
    supported_parameters: tuple[str, ...]
    if isinstance(supported_parameters_raw, list):
        supported_parameters = tuple(
            str(item).strip() for item in supported_parameters_raw if str(item).strip()
        )
    else:
        supported_parameters = ()

    return OpenRouterModelRecord(
        model_id=model_id,
        label=label,
        pricing_prompt=pricing_prompt,
        pricing_completion=pricing_completion,
        context_length=context_length,
        max_completion_tokens=max_completion_tokens,
        supported_parameters=supported_parameters,
    )


def _parse_models_payload(payload: dict[str, Any]) -> tuple[OpenRouterModelRecord, ...]:
    rows = payload.get("data")
    if not isinstance(rows, list):
        return ()

    models: list[OpenRouterModelRecord] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        record = _as_model_record(row)
        if record is not None:
            models.append(record)

    models.sort(key=lambda item: item.model_id.lower())
    return tuple(models)


def _load_cache() -> OpenRouterCatalog | None:
    cache_file = _cache_path()
    if not cache_file.exists():
        return None

    try:
        payload = json.loads(cache_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, ValueError):
        return None

    if not isinstance(payload, dict):
        return None

    fetched_at = payload.get("fetched_at")
    try:
        fetched_at_value = float(fetched_at)
    except (TypeError, ValueError):
        return None

    rows = payload.get("models")
    if not isinstance(rows, list):
        return None

    models: list[OpenRouterModelRecord] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        record = _as_model_record(row)
        if record is not None:
            models.append(record)

    if not models:
        return None

    models.sort(key=lambda item: item.model_id.lower())
    return OpenRouterCatalog(fetched_at=fetched_at_value, models=tuple(models))


def _write_cache(catalog: OpenRouterCatalog) -> None:
    cache_file = _cache_path()
    rows = []
    for model in catalog.models:
        row = asdict(model)
        row["supported_parameters"] = list(model.supported_parameters)
        rows.append(row)
    payload = {
        "fetched_at": catalog.fetched_at,
        "models": rows,
    }
    cache_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _catalog_from_emergency_fallback() -> OpenRouterCatalog:
    # Emergency fallback stays intentionally tiny and conservative.
    fallback_model = OpenRouterModelRecord(
        model_id="openrouter/free",
        label="OpenRouter Free (fallback)",
        pricing_prompt=0.0,
        pricing_completion=0.0,
        context_length=32768,
        max_completion_tokens=4096,
        supported_parameters=(),
    )
    return OpenRouterCatalog(fetched_at=time.time(), models=(fallback_model,))


def _is_fresh(catalog: OpenRouterCatalog) -> bool:
    age_seconds = time.time() - catalog.fetched_at
    return age_seconds < OPENROUTER_DISCOVERY_CACHE_TTL_SECONDS


def fetch_openrouter_models(timeout_seconds: int = 10) -> OpenRouterCatalog:
    """Fetch and normalize the full OpenRouter models catalog."""

    response = requests.get(
        OPENROUTER_MODELS_URL,
        headers={
            "Accept": "application/json",
            "User-Agent": "storycraftr-openrouter-discovery/0.1",
        },
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Unexpected OpenRouter models response shape.")

    models = _parse_models_payload(payload)
    if not models:
        raise ValueError("OpenRouter models payload did not contain valid model rows.")

    catalog = OpenRouterCatalog(fetched_at=time.time(), models=models)
    _write_cache(catalog)
    return catalog


def _load_or_fetch_catalog(force_refresh: bool = False) -> OpenRouterCatalog:
    cached = _load_cache()
    if cached and not force_refresh and _is_fresh(cached):
        return cached

    try:
        return fetch_openrouter_models()
    except Exception:
        if cached:
            return cached
        fallback = _catalog_from_emergency_fallback()
        try:
            _write_cache(fallback)
        except OSError:
            pass
        return fallback


def get_cache_metadata() -> OpenRouterCacheMetadata:
    """Return cache metadata without forcing network discovery calls."""

    cache_file = _cache_path()
    cached = _load_cache()
    if cached is None:
        return OpenRouterCacheMetadata(
            cache_path=str(cache_file),
            cache_exists=cache_file.exists(),
            cache_status="missing",
            fetched_at=None,
            age_seconds=None,
            ttl_seconds=OPENROUTER_DISCOVERY_CACHE_TTL_SECONDS,
            free_model_count=0,
            total_model_count=0,
        )

    now = time.time()
    age_seconds = max(0.0, now - cached.fetched_at)
    status = "fresh" if _is_fresh(cached) else "stale"
    free_model_count = sum(1 for model in cached.models if model.is_free)
    return OpenRouterCacheMetadata(
        cache_path=str(cache_file),
        cache_exists=True,
        cache_status=status,
        fetched_at=cached.fetched_at,
        age_seconds=age_seconds,
        ttl_seconds=OPENROUTER_DISCOVERY_CACHE_TTL_SECONDS,
        free_model_count=free_model_count,
        total_model_count=len(cached.models),
    )


def refresh_free_models() -> list[OpenRouterModelRecord]:
    """Force-refresh and return the current free-model catalog."""

    return get_free_models(force_refresh=True)


def get_free_models(force_refresh: bool = False) -> list[OpenRouterModelRecord]:
    """Return currently free OpenRouter models using live data with cache fallback."""

    catalog = _load_or_fetch_catalog(force_refresh=force_refresh)
    models = [model for model in catalog.models if model.is_free]
    models.sort(key=lambda item: item.model_id.lower())
    return models


def is_model_free(model_id: str, force_refresh: bool = False) -> bool:
    """Return True when the model exists in the current free-model catalog."""

    requested = (model_id or "").strip().lower()
    if not requested:
        return False

    free_models = get_free_models(force_refresh=force_refresh)
    return any(model.model_id.lower() == requested for model in free_models)


def build_dynamic_model_registry(
    force_refresh: bool = False,
) -> dict[str, OpenRouterModelLimits]:
    """Build a free-only model limits registry keyed by model ID."""

    registry: dict[str, OpenRouterModelLimits] = {}
    for model in get_free_models(force_refresh=force_refresh):
        registry[model.model_id.lower()] = OpenRouterModelLimits(
            context_length=model.context_length,
            max_completion_tokens=model.max_completion_tokens,
        )
    return registry


def get_model_limits(
    model_id: str, force_refresh: bool = False
) -> OpenRouterModelLimits | None:
    """Return limits for a free OpenRouter model from dynamic discovery."""

    requested = (model_id or "").strip().lower()
    if not requested:
        return None

    registry = build_dynamic_model_registry(force_refresh=force_refresh)
    return registry.get(requested)
