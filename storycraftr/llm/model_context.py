from __future__ import annotations

from dataclasses import dataclass

from storycraftr.llm.openrouter_discovery import get_model_limits


@dataclass(frozen=True)
class ModelContextSpec:
    """Effective context and reserve defaults for one resolved model profile."""

    provider: str
    model_id: str
    context_window_tokens: int
    default_output_reserve_tokens: int
    max_completion_tokens: int | None
    source: str


@dataclass(frozen=True)
class _RegistryEntry:
    provider: str
    matcher: str
    context_window_tokens: int
    default_output_reserve_tokens: int
    max_completion_tokens: int | None
    source: str


# Conservative by design: unknown models are capped to avoid prompt-overflow failures.
_DEFAULT_CONTEXT_WINDOW_TOKENS = 8192
_DEFAULT_OUTPUT_RESERVE_TOKENS = 2048

_MODEL_REGISTRY: tuple[_RegistryEntry, ...] = (
    _RegistryEntry(
        provider="openai",
        matcher="gpt-4o",
        context_window_tokens=128000,
        default_output_reserve_tokens=4096,
        max_completion_tokens=4096,
        source="openai-docs-gpt-4o",
    ),
    _RegistryEntry(
        provider="openai",
        matcher="gpt-4o-mini",
        context_window_tokens=128000,
        default_output_reserve_tokens=4096,
        max_completion_tokens=4096,
        source="openai-docs-gpt-4o-mini",
    ),
    _RegistryEntry(
        provider="openrouter",
        matcher="openrouter/free",
        context_window_tokens=32768,
        default_output_reserve_tokens=4096,
        max_completion_tokens=4096,
        source="openrouter-free-conservative",
    ),
)


def _normalize_provider(provider: str | None) -> str:
    return (provider or "").strip().lower()


def _normalize_model_id(model_id: str | None) -> str:
    return (model_id or "").strip().lower()


def resolve_model_context(
    provider: str | None, model_id: str | None
) -> ModelContextSpec:
    """Resolve effective model context profile using a tiny in-repo registry."""

    provider_key = _normalize_provider(provider)
    model_key = _normalize_model_id(model_id)

    if provider_key == "openrouter" and model_key:
        dynamic_limits = get_model_limits(model_key)
        if dynamic_limits is not None:
            reserve = dynamic_limits.max_completion_tokens or 3072
            reserve = max(512, min(reserve, 8192))
            return ModelContextSpec(
                provider=provider_key,
                model_id=model_key,
                context_window_tokens=dynamic_limits.context_length,
                default_output_reserve_tokens=reserve,
                max_completion_tokens=dynamic_limits.max_completion_tokens,
                source="openrouter-live-discovery",
            )
    for entry in _MODEL_REGISTRY:
        if provider_key != entry.provider:
            continue
        if model_key == entry.matcher:
            return ModelContextSpec(
                provider=provider_key,
                model_id=model_key,
                context_window_tokens=entry.context_window_tokens,
                default_output_reserve_tokens=entry.default_output_reserve_tokens,
                max_completion_tokens=entry.max_completion_tokens,
                source=entry.source,
            )

    # OpenRouter free variants have volatile upstream routing; use a stricter default.
    if provider_key == "openrouter" and model_key.endswith(":free"):
        return ModelContextSpec(
            provider=provider_key,
            model_id=model_key,
            context_window_tokens=16384,
            default_output_reserve_tokens=3072,
            max_completion_tokens=3072,
            source="openrouter-free-suffix-conservative",
        )

    return ModelContextSpec(
        provider=provider_key,
        model_id=model_key,
        context_window_tokens=_DEFAULT_CONTEXT_WINDOW_TOKENS,
        default_output_reserve_tokens=_DEFAULT_OUTPUT_RESERVE_TOKENS,
        max_completion_tokens=None,
        source="fallback-default-conservative",
    )


def compute_input_budget_tokens(
    spec: ModelContextSpec,
    *,
    requested_output_tokens: int | None,
    minimum_input_tokens: int = 512,
) -> int:
    """Compute input budget tokens from context window minus reserved output tokens."""

    reserve = spec.default_output_reserve_tokens
    if requested_output_tokens is not None:
        reserve = max(1, int(requested_output_tokens))

    if spec.max_completion_tokens is not None:
        reserve = min(reserve, max(1, spec.max_completion_tokens))
    max_reserve = max(1, spec.context_window_tokens - max(1, minimum_input_tokens))
    reserve = min(reserve, max_reserve)

    input_budget = spec.context_window_tokens - reserve
    return max(1, input_budget)
