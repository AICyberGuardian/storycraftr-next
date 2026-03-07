from __future__ import annotations

import json
from pathlib import Path

from storycraftr.llm.openrouter_discovery import (
    OPENROUTER_DISCOVERY_CACHE_TTL_SECONDS,
    OpenRouterCacheMetadata,
    OpenRouterCatalog,
    OpenRouterModelLimits,
    OpenRouterModelRecord,
    build_dynamic_model_registry,
    fetch_openrouter_models,
    get_cache_metadata,
    get_free_models,
    get_model_limits,
    is_model_free,
)


def _sample_payload() -> dict[str, object]:
    return {
        "data": [
            {
                "id": "meta-llama/llama-3.2-3b-instruct:free",
                "name": "Llama 3.2 3B Free",
                "context_length": 65536,
                "pricing": {"prompt": "0", "completion": "0"},
                "top_provider": {"max_completion_tokens": 8192},
                "supported_parameters": ["temperature", "top_p"],
            },
            {
                "id": "openai/gpt-4o",
                "name": "GPT-4o",
                "context_length": 128000,
                "pricing": {"prompt": "0.000005", "completion": "0.000015"},
                "top_provider": {"max_completion_tokens": 4096},
            },
        ]
    }


def _catalog(model_id: str = "openrouter/free") -> OpenRouterCatalog:
    return OpenRouterCatalog(
        fetched_at=1234.0,
        models=(
            OpenRouterModelRecord(
                model_id=model_id,
                label=model_id,
                pricing_prompt=0.0,
                pricing_completion=0.0,
                context_length=32768,
                max_completion_tokens=4096,
                supported_parameters=(),
            ),
        ),
    )


def test_fetch_openrouter_models_parses_models_and_writes_cache(
    monkeypatch, tmp_path
) -> None:
    cache_file = tmp_path / "openrouter-cache.json"
    monkeypatch.setattr(
        "storycraftr.llm.openrouter_discovery._cache_path", lambda: cache_file
    )

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return _sample_payload()

    monkeypatch.setattr(
        "storycraftr.llm.openrouter_discovery.requests.get",
        lambda *args, **kwargs: _Response(),
    )

    catalog = fetch_openrouter_models()

    assert len(catalog.models) == 2
    assert cache_file.exists()
    payload = json.loads(cache_file.read_text(encoding="utf-8"))
    assert payload["models"][0]["model_id"]


def test_get_free_models_filters_to_free_only(monkeypatch) -> None:
    monkeypatch.setattr(
        "storycraftr.llm.openrouter_discovery._load_or_fetch_catalog",
        lambda force_refresh=False: OpenRouterCatalog(
            fetched_at=1234.0,
            models=(
                OpenRouterModelRecord(
                    model_id="openrouter/free",
                    label="OpenRouter Free",
                    pricing_prompt=0.0,
                    pricing_completion=0.0,
                    context_length=32768,
                    max_completion_tokens=4096,
                    supported_parameters=(),
                ),
                OpenRouterModelRecord(
                    model_id="paid/model",
                    label="Paid",
                    pricing_prompt=0.001,
                    pricing_completion=0.001,
                    context_length=128000,
                    max_completion_tokens=4096,
                    supported_parameters=(),
                ),
            ),
        ),
    )

    free_models = get_free_models()

    assert [model.model_id for model in free_models] == ["openrouter/free"]


def test_cache_hit_uses_fresh_cache_without_network(monkeypatch, tmp_path) -> None:
    cache_file = tmp_path / "openrouter-cache.json"
    now = 10000.0
    payload = {
        "fetched_at": now,
        "models": [
            {
                "model_id": "openrouter/free",
                "label": "OpenRouter Free",
                "pricing_prompt": 0.0,
                "pricing_completion": 0.0,
                "context_length": 32768,
                "max_completion_tokens": 4096,
                "supported_parameters": [],
            }
        ],
    }
    cache_file.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr(
        "storycraftr.llm.openrouter_discovery._cache_path", lambda: cache_file
    )
    monkeypatch.setattr("storycraftr.llm.openrouter_discovery.time.time", lambda: now)

    def _fail_fetch(timeout_seconds: int = 10):
        raise AssertionError("network should not be called on fresh cache")

    monkeypatch.setattr(
        "storycraftr.llm.openrouter_discovery.fetch_openrouter_models", _fail_fetch
    )

    models = get_free_models()

    assert [model.model_id for model in models] == ["openrouter/free"]


def test_stale_cache_is_used_when_live_fetch_fails(monkeypatch, tmp_path) -> None:
    cache_file = tmp_path / "openrouter-cache.json"
    now = 10000.0
    stale = now - (OPENROUTER_DISCOVERY_CACHE_TTL_SECONDS + 5)
    payload = {
        "fetched_at": stale,
        "models": [
            {
                "model_id": "openrouter/free",
                "label": "OpenRouter Free",
                "pricing_prompt": 0.0,
                "pricing_completion": 0.0,
                "context_length": 32768,
                "max_completion_tokens": 4096,
                "supported_parameters": [],
            }
        ],
    }
    cache_file.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr(
        "storycraftr.llm.openrouter_discovery._cache_path", lambda: cache_file
    )
    monkeypatch.setattr("storycraftr.llm.openrouter_discovery.time.time", lambda: now)
    monkeypatch.setattr(
        "storycraftr.llm.openrouter_discovery.fetch_openrouter_models",
        lambda timeout_seconds=10: (_ for _ in ()).throw(RuntimeError("api down")),
    )

    models = get_free_models()

    assert [model.model_id for model in models] == ["openrouter/free"]


def test_corrupted_cache_recovers_with_live_fetch(monkeypatch, tmp_path) -> None:
    cache_file = tmp_path / "openrouter-cache.json"
    cache_file.write_text("{broken", encoding="utf-8")
    monkeypatch.setattr(
        "storycraftr.llm.openrouter_discovery._cache_path", lambda: cache_file
    )
    monkeypatch.setattr(
        "storycraftr.llm.openrouter_discovery.fetch_openrouter_models",
        lambda timeout_seconds=10: _catalog("meta-llama/llama-3.2-3b-instruct:free"),
    )

    models = get_free_models()

    assert [model.model_id for model in models] == [
        "meta-llama/llama-3.2-3b-instruct:free"
    ]


def test_dynamic_registry_and_limit_lookup(monkeypatch) -> None:
    registry_input = [
        OpenRouterModelRecord(
            model_id="openrouter/free",
            label="OpenRouter Free",
            pricing_prompt=0.0,
            pricing_completion=0.0,
            context_length=32768,
            max_completion_tokens=4096,
            supported_parameters=(),
        )
    ]
    monkeypatch.setattr(
        "storycraftr.llm.openrouter_discovery.get_free_models",
        lambda force_refresh=False: registry_input,
    )

    registry = build_dynamic_model_registry()

    assert registry == {
        "openrouter/free": OpenRouterModelLimits(
            context_length=32768,
            max_completion_tokens=4096,
        )
    }
    assert is_model_free("openrouter/free") is True
    assert is_model_free("paid/model") is False
    assert get_model_limits("openrouter/free") == OpenRouterModelLimits(
        context_length=32768,
        max_completion_tokens=4096,
    )


def test_get_cache_metadata_reports_missing_cache(monkeypatch, tmp_path) -> None:
    cache_file = tmp_path / "openrouter-cache.json"
    monkeypatch.setattr(
        "storycraftr.llm.openrouter_discovery._cache_path", lambda: cache_file
    )
    monkeypatch.setattr(
        "storycraftr.llm.openrouter_discovery._load_cache", lambda: None
    )

    metadata = get_cache_metadata()

    assert metadata == OpenRouterCacheMetadata(
        cache_path=str(cache_file),
        cache_exists=False,
        cache_status="missing",
        fetched_at=None,
        age_seconds=None,
        ttl_seconds=OPENROUTER_DISCOVERY_CACHE_TTL_SECONDS,
        free_model_count=0,
        total_model_count=0,
    )


def test_get_cache_metadata_reports_fresh_or_stale(monkeypatch) -> None:
    catalog = OpenRouterCatalog(
        fetched_at=1000.0,
        models=(
            OpenRouterModelRecord(
                model_id="openrouter/free",
                label="OpenRouter Free",
                pricing_prompt=0.0,
                pricing_completion=0.0,
                context_length=32768,
                max_completion_tokens=4096,
                supported_parameters=(),
            ),
            OpenRouterModelRecord(
                model_id="paid/model",
                label="Paid",
                pricing_prompt=0.001,
                pricing_completion=0.001,
                context_length=32768,
                max_completion_tokens=4096,
                supported_parameters=(),
            ),
        ),
    )

    monkeypatch.setattr(
        "storycraftr.llm.openrouter_discovery._cache_path",
        lambda: Path("/tmp/test-cache.json"),  # nosec B108
    )
    monkeypatch.setattr(
        "storycraftr.llm.openrouter_discovery._load_cache", lambda: catalog
    )

    monkeypatch.setattr(
        "storycraftr.llm.openrouter_discovery.time.time", lambda: 1005.0
    )
    fresh = get_cache_metadata()
    assert fresh.cache_status == "fresh"
    assert fresh.free_model_count == 1
    assert fresh.total_model_count == 2

    monkeypatch.setattr(
        "storycraftr.llm.openrouter_discovery.time.time",
        lambda: 1000.0 + OPENROUTER_DISCOVERY_CACHE_TTL_SECONDS + 10,
    )
    stale = get_cache_metadata()
    assert stale.cache_status == "stale"
