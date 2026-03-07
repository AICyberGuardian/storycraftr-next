from __future__ import annotations

from storycraftr.llm.openrouter_discovery import OpenRouterModelLimits
from storycraftr.llm.model_context import (
    compute_input_budget_tokens,
    resolve_model_context,
)


def test_resolve_model_context_uses_openrouter_dynamic_discovery(monkeypatch) -> None:
    monkeypatch.setattr(
        "storycraftr.llm.model_context.get_model_limits",
        lambda model_id: OpenRouterModelLimits(
            context_length=64000,
            max_completion_tokens=2048,
        ),
    )

    spec = resolve_model_context("openrouter", "openrouter/free")

    assert spec.context_window_tokens == 64000
    assert spec.default_output_reserve_tokens == 2048
    assert spec.max_completion_tokens == 2048
    assert spec.source == "openrouter-live-discovery"


def test_resolve_model_context_uses_conservative_free_suffix_fallback(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "storycraftr.llm.model_context.get_model_limits",
        lambda model_id: None,
    )

    spec = resolve_model_context("openrouter", "meta-llama/something:free")

    assert spec.context_window_tokens == 16384
    assert spec.default_output_reserve_tokens == 3072
    assert spec.max_completion_tokens == 3072
    assert spec.source == "openrouter-free-suffix-conservative"


def test_resolve_model_context_uses_default_for_unknown_model() -> None:
    spec = resolve_model_context("custom", "my-model")

    assert spec.context_window_tokens == 8192
    assert spec.default_output_reserve_tokens == 2048
    assert spec.max_completion_tokens is None
    assert spec.source == "fallback-default-conservative"


def test_compute_input_budget_tokens_respects_requested_output(monkeypatch) -> None:
    monkeypatch.setattr(
        "storycraftr.llm.model_context.get_model_limits",
        lambda model_id: None,
    )

    spec = resolve_model_context("openrouter", "openrouter/free")

    budget = compute_input_budget_tokens(spec, requested_output_tokens=5000)

    assert budget == 28672


def test_compute_input_budget_tokens_clamps_to_model_max_completion(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "storycraftr.llm.model_context.get_model_limits",
        lambda model_id: OpenRouterModelLimits(
            context_length=16000,
            max_completion_tokens=1024,
        ),
    )

    spec = resolve_model_context("openrouter", "meta-llama/some-free:free")
    budget = compute_input_budget_tokens(spec, requested_output_tokens=5000)

    assert budget == 14976
