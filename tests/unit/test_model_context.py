from __future__ import annotations

from storycraftr.llm.model_context import (
    compute_input_budget_tokens,
    resolve_model_context,
)


def test_resolve_model_context_uses_known_registry_entry() -> None:
    spec = resolve_model_context("openrouter", "openrouter/free")

    assert spec.context_window_tokens == 32768
    assert spec.default_output_reserve_tokens == 4096
    assert spec.source == "openrouter-free-conservative"


def test_resolve_model_context_uses_conservative_free_suffix_fallback() -> None:
    spec = resolve_model_context("openrouter", "meta-llama/something:free")

    assert spec.context_window_tokens == 16384
    assert spec.default_output_reserve_tokens == 3072
    assert spec.source == "openrouter-free-suffix-conservative"


def test_resolve_model_context_uses_default_for_unknown_model() -> None:
    spec = resolve_model_context("custom", "my-model")

    assert spec.context_window_tokens == 8192
    assert spec.default_output_reserve_tokens == 2048
    assert spec.source == "fallback-default-conservative"


def test_compute_input_budget_tokens_respects_requested_output() -> None:
    spec = resolve_model_context("openrouter", "openrouter/free")

    budget = compute_input_budget_tokens(spec, requested_output_tokens=5000)

    assert budget == 27768
