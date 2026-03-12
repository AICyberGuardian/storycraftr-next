from unittest import mock
from types import SimpleNamespace

import json

import pytest

from storycraftr.llm.factory import (
    LLMAuthenticationError,
    LLMConfigurationError,
    LLMInitializationError,
    LLMInvocationError,
    LLMSettings,
    _load_openrouter_rankings,
    _rankings_fallback_models_for_batch,
    build_chat_model,
    get_model_health_registry,
    validate_ranking_consensus,
)
from storycraftr.utils.core import llm_settings_from_config
from storycraftr.utils.core import BookConfig


@pytest.fixture(autouse=True)
def clean_llm_env(monkeypatch):
    for env_var in (
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "OPENROUTER_BASE_URL",
        "STORYCRAFTR_OPENROUTER_FALLBACK_MODELS",
        "CUSTOM_OPENROUTER_KEY",
        "OLLAMA_BASE_URL",
        "STORYCRAFTR_HTTP_REFERER",
        "STORYCRAFTR_APP_NAME",
    ):
        monkeypatch.delenv(env_var, raising=False)


@pytest.fixture(autouse=True)
def allow_openrouter_models_by_default(monkeypatch):
    monkeypatch.setattr("storycraftr.llm.factory.is_model_free", lambda model_id: True)


@pytest.fixture(autouse=True)
def reset_model_health_registry():
    from storycraftr.llm import factory as factory_module

    registry = get_model_health_registry()
    registry.reset()
    factory_module._OPENROUTER_CIRCUIT_BREAKERS.clear()
    factory_module._PROVIDER_CIRCUIT_BREAKERS.clear()
    yield
    registry.reset()
    factory_module._OPENROUTER_CIRCUIT_BREAKERS.clear()
    factory_module._PROVIDER_CIRCUIT_BREAKERS.clear()


def test_openrouter_requires_explicit_provider_model(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")

    settings = LLMSettings(provider="openrouter", model="gpt-4o")

    with pytest.raises(LLMConfigurationError, match="provider/model"):
        build_chat_model(settings)


def test_openrouter_rejects_non_free_model_before_client_init(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")
    monkeypatch.setattr("storycraftr.llm.factory.is_model_free", lambda model_id: False)

    with mock.patch("storycraftr.llm.factory.ChatOpenAI") as mock_chat_openai:
        with pytest.raises(LLMConfigurationError, match="free-only mode"):
            build_chat_model(
                LLMSettings(
                    provider="openrouter",
                    model="meta-llama/llama-3.3-70b-instruct",
                )
            )

    assert mock_chat_openai.call_count == 0


def test_openrouter_rejects_model_when_discovery_cannot_verify(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")
    monkeypatch.setattr("storycraftr.llm.factory.is_model_free", lambda model_id: False)

    with pytest.raises(LLMConfigurationError, match="unknown, or unavailable"):
        build_chat_model(
            LLMSettings(
                provider="openrouter",
                model="openrouter/free",
            )
        )


def test_openrouter_missing_api_key_raises_provider_auth_error():
    settings = LLMSettings(
        provider="openrouter",
        model="meta-llama/llama-3.3-70b-instruct",
    )

    with pytest.raises(
        LLMAuthenticationError,
        match=r"provider 'openrouter'.*meta-llama/llama-3.3-70b-instruct.*https://openrouter.ai/api/v1.*OPENROUTER_API_KEY",
    ) as exc:
        build_chat_model(settings)
    assert "Verify your OPENROUTER_API_KEY is set and valid" in str(exc.value)


def test_openrouter_missing_model_fails_fast_with_actionable_message(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")
    settings = LLMSettings(provider="openrouter", model="")

    with pytest.raises(
        LLMConfigurationError,
        match=r"storycraftr\.json.*\"llm_model\".*openrouter/free",
    ):
        build_chat_model(settings)


def test_openrouter_init_error_includes_raw_code_and_body(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")

    response = SimpleNamespace(status_code=503, text='{"error":"upstream timeout"}')
    init_exc = RuntimeError("provider init failed")
    init_exc.response = response

    with mock.patch(
        "storycraftr.llm.factory.ChatOpenAI",
        side_effect=init_exc,
    ):
        with pytest.raises(LLMInitializationError) as caught:
            build_chat_model(
                LLMSettings(
                    provider="openrouter",
                    model="openrouter/free",
                )
            )

    message = str(caught.value)
    assert "OpenRouter Error [503]" in message
    assert "upstream timeout" in message


def test_openrouter_builds_chatopenai_with_default_endpoint_and_headers(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")

    with mock.patch("storycraftr.llm.factory.ChatOpenAI") as mock_chat_openai:
        mock_chat_openai.return_value = object()

        settings = LLMSettings(
            provider="openrouter",
            model="openrouter/free",
            request_timeout=30,
        )
        result = build_chat_model(settings)

    assert result._llm_type == "openrouter-resilient"
    kwargs = mock_chat_openai.call_args.kwargs
    assert kwargs["api_key"] == "or-test"  # nosec B105  # pragma: allowlist secret
    assert kwargs["model"] == "openrouter/free"
    assert kwargs["base_url"] == "https://openrouter.ai/api/v1"
    assert kwargs["max_tokens"] == 4000
    assert kwargs["timeout"] == 30
    assert kwargs["default_headers"]["HTTP-Referer"] == "https://storycraftr.app"
    assert kwargs["default_headers"]["X-Title"] == "StoryCraftr CLI"


def test_openai_builds_chatopenai_with_explicit_max_tokens(monkeypatch):
    monkeypatch.setenv(
        "OPENAI_API_KEY",
        "sk-test",  # nosec B105  # pragma: allowlist secret
    )

    with mock.patch("storycraftr.llm.factory.ChatOpenAI") as mock_chat_openai:
        mock_chat_openai.return_value = object()
        result = build_chat_model(
            LLMSettings(
                provider="openai",
                model="gpt-4o",
                max_tokens=2048,
            )
        )

    assert result._llm_type == "openai-resilient"
    assert result.wrapped_model is mock_chat_openai.return_value
    kwargs = mock_chat_openai.call_args.kwargs
    assert kwargs["model"] == "gpt-4o"
    assert kwargs["max_tokens"] == 2048


def test_openrouter_invalid_max_tokens_fails_before_client_init(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")

    with pytest.raises(LLMConfigurationError, match="max_tokens"):
        build_chat_model(
            LLMSettings(
                provider="openrouter",
                model="openrouter/free",
                max_tokens=0,
            )
        )


def test_openrouter_does_not_silently_fallback_to_openai_default(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")
    settings = llm_settings_from_config(
        BookConfig.from_mapping(
            book_path=str(tmp_path / "test_book"),
            config_data={"llm_provider": "openrouter"},
        )
    )

    assert settings.model == ""
    with pytest.raises(LLMConfigurationError, match="Missing 'llm_model'"):
        build_chat_model(settings)


def test_openrouter_invalid_endpoint_fails_before_client_init(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")
    settings = LLMSettings(
        provider="openrouter",
        model="meta-llama/llama-3.3-70b-instruct",
        endpoint="localhost:11434",
    )

    with pytest.raises(LLMConfigurationError, match="Invalid endpoint"):
        build_chat_model(settings)


def test_openrouter_uses_openrouter_base_url_env_when_endpoint_missing(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://router.example/v1")

    with mock.patch("storycraftr.llm.factory.ChatOpenAI") as mock_chat_openai:
        mock_chat_openai.return_value = object()
        result = build_chat_model(
            LLMSettings(
                provider="openrouter",
                model="meta-llama/llama-3.3-70b-instruct",
            )
        )

    assert result._llm_type == "openrouter-resilient"
    assert mock_chat_openai.call_args.kwargs["base_url"] == "https://router.example/v1"


def test_openrouter_prefers_explicit_endpoint_over_env(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://router.example/v1")

    with mock.patch("storycraftr.llm.factory.ChatOpenAI") as mock_chat_openai:
        mock_chat_openai.return_value = object()
        result = build_chat_model(
            LLMSettings(
                provider="openrouter",
                model="meta-llama/llama-3.3-70b-instruct",
                endpoint="https://explicit.example/v1",
            )
        )

    assert result._llm_type == "openrouter-resilient"
    assert (
        mock_chat_openai.call_args.kwargs["base_url"] == "https://explicit.example/v1"
    )


def test_openrouter_honors_custom_api_key_env_override(monkeypatch):
    monkeypatch.setenv(
        "CUSTOM_OPENROUTER_KEY", "or-custom"
    )  # nosec B105  # pragma: allowlist secret

    with mock.patch("storycraftr.llm.factory.ChatOpenAI") as mock_chat_openai:
        mock_chat_openai.return_value = object()
        result = build_chat_model(
            LLMSettings(
                provider="openrouter",
                model="meta-llama/llama-3.3-70b-instruct",
                api_key_env="CUSTOM_OPENROUTER_KEY",  # nosec B105  # pragma: allowlist secret
            )
        )

    assert result._llm_type == "openrouter-resilient"
    assert (
        mock_chat_openai.call_args.kwargs["api_key"]
        == "or-custom"  # nosec B105  # pragma: allowlist secret
    )


def test_openrouter_wrapper_uses_env_fallback_chain(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")
    monkeypatch.setenv(
        "STORYCRAFTR_OPENROUTER_FALLBACK_MODELS",
        "meta-llama/llama-3.2-3b-instruct:free,openrouter/free",
    )

    first = object()
    second = object()
    third = object()
    with mock.patch(
        "storycraftr.llm.factory.ChatOpenAI",
        side_effect=[first, second, third],
    ) as mock_chat_openai:
        result = build_chat_model(
            LLMSettings(
                provider="openrouter",
                model="meta-llama/llama-3.3-70b-instruct",
            )
        )

    assert result._llm_type == "openrouter-resilient"
    assert result.model_sequence == [
        "meta-llama/llama-3.3-70b-instruct",
        "meta-llama/llama-3.2-3b-instruct:free",
        "openrouter/free",
    ]
    assert mock_chat_openai.call_count == 3


def test_model_health_registry_marks_model_degraded_after_errors() -> None:
    registry = get_model_health_registry()
    for _ in range(4):
        registry.record_error("openrouter/free")

    assert registry.is_degraded("openrouter/free") is True


def test_model_health_registry_marks_model_degraded_after_high_latency() -> None:
    registry = get_model_health_registry()
    registry.record_success("openrouter/free", latency_seconds=301.0)

    assert registry.is_degraded("openrouter/free") is True


def test_model_health_registry_quarantines_after_repeated_429() -> None:
    registry = get_model_health_registry()
    registry.record_http_failure("openrouter/free", status_code=429)
    registry.record_http_failure("openrouter/free", status_code=429)

    assert registry.is_quarantined("openrouter/free") is True


def test_openrouter_wrapper_skips_degraded_primary_model(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")
    get_model_health_registry().mark_degraded("openrouter/free")

    primary = mock.Mock()
    primary._generate.side_effect = RuntimeError("primary should be skipped")

    fallback_result = object()
    fallback = mock.Mock()
    fallback._generate.return_value = fallback_result

    with mock.patch(
        "storycraftr.llm.factory.ChatOpenAI",
        side_effect=[primary, fallback],
    ):
        with mock.patch("storycraftr.llm.factory._openrouter_fallback_chain") as chain:
            chain.return_value = ["stepfun/step-3.5-flash:free"]
            model = build_chat_model(
                LLMSettings(
                    provider="openrouter",
                    model="openrouter/free",
                )
            )

    result = model._generate(messages=[], stop=None, run_manager=None)

    assert result is fallback_result
    assert primary._generate.call_count == 0
    assert fallback._generate.call_count == 1


def test_openrouter_wrapper_skips_quarantined_primary_model(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")
    get_model_health_registry().mark_quarantined("openrouter/free", seconds=600)

    primary = mock.Mock()
    primary._generate.side_effect = RuntimeError("primary should be skipped")

    fallback_result = object()
    fallback = mock.Mock()
    fallback._generate.return_value = fallback_result

    with mock.patch(
        "storycraftr.llm.factory.ChatOpenAI",
        side_effect=[primary, fallback],
    ):
        with mock.patch("storycraftr.llm.factory._openrouter_fallback_chain") as chain:
            chain.return_value = ["stepfun/step-3.5-flash:free"]
            model = build_chat_model(
                LLMSettings(
                    provider="openrouter",
                    model="openrouter/free",
                )
            )

    result = model._generate(messages=[], stop=None, run_manager=None)

    assert result is fallback_result
    assert primary._generate.call_count == 0
    assert fallback._generate.call_count == 1


def test_openrouter_fallback_init_warning_redacts_api_key(monkeypatch):
    secret = "or-super-secret"  # nosec B105  # pragma: allowlist secret
    monkeypatch.setenv(
        "OPENROUTER_API_KEY", secret
    )  # nosec B105  # pragma: allowlist secret
    monkeypatch.setenv(
        "STORYCRAFTR_OPENROUTER_FALLBACK_MODELS",
        "meta-llama/llama-3.2-3b-instruct:free",
    )

    primary = object()
    with mock.patch(
        "storycraftr.llm.factory.ChatOpenAI",
        side_effect=[primary, RuntimeError(f"fallback failed for {secret}")],
    ):
        with mock.patch("storycraftr.llm.factory._OPENROUTER_LOGGER") as mock_logger:
            build_chat_model(
                LLMSettings(
                    provider="openrouter",
                    model="meta-llama/llama-3.3-70b-instruct",
                )
            )

    logged_errors = "\n".join(
        str(call.kwargs.get("error", "")) for call in mock_logger.warning.call_args_list
    )
    assert "or-super-secret" not in logged_errors


def test_openrouter_success_on_primary_first_attempt_is_not_noisy(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")

    mock_result = object()
    primary = mock.Mock()
    primary._generate.return_value = mock_result
    with mock.patch("storycraftr.llm.factory.ChatOpenAI", return_value=primary):
        with mock.patch("storycraftr.llm.factory._OPENROUTER_LOGGER") as mock_logger:
            model = build_chat_model(
                LLMSettings(
                    provider="openrouter",
                    model="openrouter/free",
                )
            )
            result = model._generate(messages=[], stop=None, run_manager=None)

    assert result is mock_result
    assert mock_logger.warning.call_count == 0


def test_openrouter_token_budget_exceeded(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")
    mock_logger = mock.Mock()
    monkeypatch.setattr("storycraftr.llm.factory._OPENROUTER_LOGGER", mock_logger)
    monkeypatch.setattr(
        "storycraftr.llm.factory.get_model_limits",
        lambda _model_id: SimpleNamespace(context_length=64, max_completion_tokens=16),
    )

    primary = mock.Mock()
    with mock.patch("storycraftr.llm.factory.ChatOpenAI", return_value=primary):
        model = build_chat_model(
            LLMSettings(
                provider="openrouter",
                model="openrouter/free",
            )
        )

    with pytest.raises(LLMInvocationError) as exc_info:
        model._generate(
            messages=[SimpleNamespace(content="word " * 200)],
            stop=None,
            run_manager=None,
        )

    assert primary._generate.call_count == 0
    assert exc_info.value.transport_error["error_kind"] == "token_budget_exceeded"
    assert "token_budget_exceeded" in str(exc_info.value)
    assert any(
        call.args and call.args[0] == "openrouter_token_budget_exceeded"
        for call in mock_logger.warning.call_args_list
    )


def test_openai_token_budget_exceeded_preflight(monkeypatch):
    monkeypatch.setenv(
        "OPENAI_API_KEY",
        "sk-test",  # nosec B105  # pragma: allowlist secret
    )
    monkeypatch.setattr(
        "storycraftr.llm.factory._estimate_prompt_tokens",
        lambda _messages, _model_name: 200000,
    )

    wrapped = mock.Mock()
    with mock.patch("storycraftr.llm.factory.ChatOpenAI", return_value=wrapped):
        model = build_chat_model(
            LLMSettings(
                provider="openai",
                model="gpt-4o",
                max_tokens=4000,
            )
        )

    with pytest.raises(LLMInvocationError) as exc_info:
        model._generate(
            messages=[SimpleNamespace(content="tiny prompt")],
            stop=None,
            run_manager=None,
        )

    assert wrapped._generate.call_count == 0
    assert exc_info.value.transport_error["provider"] == "openai"
    assert exc_info.value.transport_error["error_kind"] == "token_budget_exceeded"


def test_ollama_token_budget_exceeded_preflight(monkeypatch):
    monkeypatch.setattr(
        "storycraftr.llm.factory._estimate_prompt_tokens",
        lambda _messages, _model_name: 50000,
    )

    wrapped = mock.Mock()
    with mock.patch("storycraftr.llm.factory.ChatOllama", return_value=wrapped):
        model = build_chat_model(
            LLMSettings(
                provider="ollama",
                model="llama3",
                max_tokens=4000,
            )
        )

    with pytest.raises(LLMInvocationError) as exc_info:
        model._generate(
            messages=[SimpleNamespace(content="tiny prompt")],
            stop=None,
            run_manager=None,
        )

    assert wrapped._generate.call_count == 0
    assert exc_info.value.transport_error["provider"] == "ollama"
    assert exc_info.value.transport_error["error_kind"] == "token_budget_exceeded"


def test_openrouter_wrapper_logs_retry_events(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")
    mock_logger = mock.Mock()
    monkeypatch.setattr("storycraftr.llm.factory._OPENROUTER_LOGGER", mock_logger)

    mock_result = object()
    primary = mock.Mock()
    primary._generate.side_effect = [TimeoutError("timed out"), mock_result]

    with mock.patch("storycraftr.llm.factory.ChatOpenAI", return_value=primary):
        with mock.patch("storycraftr.llm.factory.time.sleep"):
            model = build_chat_model(
                LLMSettings(
                    provider="openrouter",
                    model="openrouter/free",
                )
            )
            result = model._generate(messages=[], stop=None, run_manager=None)

    assert result is mock_result
    assert any(
        call.args and call.args[0] == "openrouter_retry"
        for call in mock_logger.warning.call_args_list
    )


def test_openrouter_wrapper_retries_then_succeeds(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")

    mock_result = object()
    primary = mock.Mock()
    primary._generate.side_effect = [
        TimeoutError("timed out"),
        mock_result,
    ]
    with mock.patch("storycraftr.llm.factory.ChatOpenAI", return_value=primary):
        with mock.patch("storycraftr.llm.factory.time.sleep") as mock_sleep:
            model = build_chat_model(
                LLMSettings(
                    provider="openrouter",
                    model="openrouter/free",
                )
            )

            result = model._generate(messages=[], stop=None, run_manager=None)

    assert result is mock_result
    assert primary._generate.call_count == 2
    assert mock_sleep.call_count == 1


def test_openrouter_wrapper_retries_on_http_502(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")

    mock_result = object()
    primary = mock.Mock()
    primary._generate.side_effect = [
        RuntimeError("Error code: 502 - bad gateway"),
        mock_result,
    ]
    with mock.patch("storycraftr.llm.factory.ChatOpenAI", return_value=primary):
        with mock.patch("storycraftr.llm.factory.time.sleep") as mock_sleep:
            model = build_chat_model(
                LLMSettings(
                    provider="openrouter",
                    model="openrouter/free",
                )
            )

            result = model._generate(messages=[], stop=None, run_manager=None)

    assert result is mock_result
    assert primary._generate.call_count == 2
    assert mock_sleep.call_count == 1


def test_openrouter_wrapper_retries_on_empty_response(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")

    mock_result = object()
    primary = mock.Mock()
    primary._generate.side_effect = [
        SimpleNamespace(generations=[]),
        mock_result,
    ]
    with mock.patch("storycraftr.llm.factory.ChatOpenAI", return_value=primary):
        with mock.patch("storycraftr.llm.factory.time.sleep") as mock_sleep:
            model = build_chat_model(
                LLMSettings(
                    provider="openrouter",
                    model="openrouter/free",
                )
            )

            result = model._generate(messages=[], stop=None, run_manager=None)

    assert result is mock_result
    assert primary._generate.call_count == 2
    assert mock_sleep.call_count == 1


def test_openrouter_wrapper_falls_back_after_retry_exhaustion(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")
    monkeypatch.setenv(
        "STORYCRAFTR_OPENROUTER_FALLBACK_MODELS",
        "stepfun/step-3.5-flash:free",
    )

    primary = mock.Mock()
    primary._generate.side_effect = TimeoutError("timed out")
    fallback = mock.Mock()
    fallback_result = object()
    fallback._generate.return_value = fallback_result

    with mock.patch(
        "storycraftr.llm.factory.ChatOpenAI",
        side_effect=[primary, fallback],
    ):
        with mock.patch("storycraftr.llm.factory.time.sleep"):
            model = build_chat_model(
                LLMSettings(
                    provider="openrouter",
                    model="meta-llama/llama-3.3-70b-instruct:free",
                )
            )
            result = model._generate(messages=[], stop=None, run_manager=None)

    assert result is fallback_result
    assert primary._generate.call_count == 2
    assert fallback._generate.call_count == 1


def test_openrouter_wrapper_quarantines_on_repeated_503_and_rotates(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")
    monkeypatch.setenv(
        "STORYCRAFTR_OPENROUTER_FALLBACK_MODELS",
        "stepfun/step-3.5-flash:free",
    )

    response = SimpleNamespace(status_code=503, text='{"error":"upstream down"}')
    primary = mock.Mock()
    exc = RuntimeError("service unavailable")
    exc.response = response
    primary._generate.side_effect = [exc, exc]

    fallback = mock.Mock()
    fallback_result = object()
    fallback._generate.return_value = fallback_result

    with mock.patch(
        "storycraftr.llm.factory.ChatOpenAI",
        side_effect=[primary, fallback],
    ):
        with mock.patch("storycraftr.llm.factory.time.sleep"):
            model = build_chat_model(
                LLMSettings(
                    provider="openrouter",
                    model="meta-llama/llama-3.3-70b-instruct:free",
                )
            )
            model.set_invocation_stage("draft")
            result = model._generate(messages=[], stop=None, run_manager=None)

    assert result is fallback_result
    assert get_model_health_registry().is_quarantined(
        "meta-llama/llama-3.3-70b-instruct:free"
    )
    assert primary._generate.call_count == 2
    assert fallback._generate.call_count == 1


def test_openrouter_rejects_invalid_model_identifier(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")

    with pytest.raises(LLMConfigurationError, match="Expected 'provider/model'"):
        build_chat_model(LLMSettings(provider="openrouter", model="meta-llama/"))


def test_openrouter_wraps_chatopenai_initialization_errors(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")
    with mock.patch(
        "storycraftr.llm.factory.ChatOpenAI", side_effect=ValueError("bad")
    ):
        with pytest.raises(LLMInitializationError, match="openrouter"):
            build_chat_model(
                LLMSettings(
                    provider="openrouter",
                    model="meta-llama/llama-3.3-70b-instruct",
                )
            )


def test_openrouter_provider_auth_error_is_actionable_and_redacts_key(monkeypatch):
    secret = "or-super-secret-token"  # nosec B105  # pragma: allowlist secret
    monkeypatch.setenv(
        "OPENROUTER_API_KEY", secret
    )  # nosec B105  # pragma: allowlist secret
    with mock.patch(
        "storycraftr.llm.factory.ChatOpenAI",
        side_effect=RuntimeError(f"401 unauthorized api key {secret}"),
    ):
        with pytest.raises(LLMAuthenticationError) as exc:
            build_chat_model(
                LLMSettings(provider="openrouter", model="openrouter/free")
            )

    message = str(exc.value)
    assert "Provider 'openrouter'" in message
    assert "model 'openrouter/free'" in message
    assert "endpoint 'https://openrouter.ai/api/v1'" in message
    assert "Verify your OPENROUTER_API_KEY is set and valid." in message
    assert secret not in message


def test_openrouter_timeout_error_is_actionable_and_redacts_key(monkeypatch):
    secret = "or-timeout-secret"  # nosec B105  # pragma: allowlist secret
    monkeypatch.setenv(
        "OPENROUTER_API_KEY", secret
    )  # nosec B105  # pragma: allowlist secret
    with mock.patch(
        "storycraftr.llm.factory.ChatOpenAI",
        side_effect=TimeoutError(f"request timed out using {secret}"),
    ):
        with pytest.raises(LLMInitializationError) as exc:
            build_chat_model(
                LLMSettings(
                    provider="openrouter",
                    model="openrouter/free",
                    endpoint="https://router.example/v1",
                )
            )

    message = str(exc.value)
    assert "Provider 'openrouter'" in message
    assert "model 'openrouter/free'" in message
    assert "endpoint 'https://router.example/v1'" in message
    assert "Retry with a higher request_timeout" in message
    assert secret not in message


def _valid_rankings_payload(*, prose_primary: str = "z-ai/glm-4.5-air:free") -> dict:
    return {
        "batch_planning": {
            "primary": "meta-llama/llama-3.3-70b-instruct:free",
            "fallbacks": ["stepfun/step-3.5-flash:free"],
            "why": "Planner model provides stable long-context behavior.",
        },
        "batch_prose": {
            "primary": prose_primary,
            "fallbacks": ["meta-llama/llama-3.3-70b-instruct:free"],
            "why": "Prose model remains creative with controlled fallback behavior.",
        },
        "batch_editing": {
            "primary": "google/gemma-3-27b-it:free",
            "fallbacks": ["z-ai/glm-4.5-air:free"],
            "why": "Editing role prioritizes precise, reliable rewrites.",
        },
        "repair_json": {
            "primary": "google/gemma-3-27b-it:free",
            "fallbacks": ["stepfun/step-3.5-flash:free"],
            "why": "Repair role enforces strict format compliance for JSON output.",
        },
        "coherence_check": {
            "primary": "stepfun/step-3.5-flash:free",
            "fallbacks": ["openai/gpt-oss-120b:free"],
            "context_limit": 200000,
            "why": "Coherence gate scans long chapter context for contradictions.",
        },
    }


def test_openrouter_rankings_loader_accepts_strict_payload(monkeypatch, tmp_path):
    rankings_path = tmp_path / "rankings.json"
    rankings_path.write_text(
        json.dumps(_valid_rankings_payload(), indent=2),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "storycraftr.llm.factory._OPENROUTER_RANKINGS_PATH", rankings_path
    )
    monkeypatch.setattr("storycraftr.llm.factory.is_model_free", lambda model_id: True)
    monkeypatch.setattr(
        "storycraftr.llm.factory.get_model_limits",
        lambda model_id: SimpleNamespace(context_length=300000),
    )

    loaded = _load_openrouter_rankings()

    assert loaded["batch_planning"]["fallbacks"] == ["stepfun/step-3.5-flash:free"]
    assert loaded["coherence_check"]["context_limit"] == 200000


def test_openrouter_rankings_loader_rejects_legacy_fallback_key(monkeypatch, tmp_path):
    rankings_path = tmp_path / "rankings.json"
    invalid_payload = _valid_rankings_payload()
    invalid_payload["batch_planning"]["fallback"] = invalid_payload[
        "batch_planning"
    ].pop("fallbacks")
    rankings_path.write_text(json.dumps(invalid_payload, indent=2), encoding="utf-8")
    monkeypatch.setattr(
        "storycraftr.llm.factory._OPENROUTER_RANKINGS_PATH", rankings_path
    )
    monkeypatch.setattr("storycraftr.llm.factory.is_model_free", lambda model_id: True)
    monkeypatch.setattr(
        "storycraftr.llm.factory.get_model_limits",
        lambda model_id: SimpleNamespace(context_length=300000),
    )

    assert _load_openrouter_rankings() == {}


def test_openrouter_rankings_restricts_openrouter_free_in_prose(monkeypatch, tmp_path):
    rankings_path = tmp_path / "rankings.json"
    rankings_path.write_text(
        json.dumps(_valid_rankings_payload(prose_primary="openrouter/free"), indent=2),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "storycraftr.llm.factory._OPENROUTER_RANKINGS_PATH", rankings_path
    )
    monkeypatch.setattr("storycraftr.llm.factory.is_model_free", lambda model_id: True)
    monkeypatch.setattr(
        "storycraftr.llm.factory.get_model_limits",
        lambda model_id: SimpleNamespace(context_length=300000),
    )
    monkeypatch.delenv("STORYCRAFTR_ALLOW_OPENROUTER_FREE_PROSE", raising=False)

    assert _load_openrouter_rankings() == {}

    monkeypatch.setenv("STORYCRAFTR_ALLOW_OPENROUTER_FREE_PROSE", "1")
    assert _load_openrouter_rankings()["batch_prose"]["primary"] == "openrouter/free"


def test_rankings_fallback_models_for_batch_reads_fallbacks(monkeypatch, tmp_path):
    rankings_path = tmp_path / "rankings.json"
    rankings_path.write_text(
        json.dumps(_valid_rankings_payload(), indent=2),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "storycraftr.llm.factory._OPENROUTER_RANKINGS_PATH", rankings_path
    )
    monkeypatch.setattr("storycraftr.llm.factory.is_model_free", lambda model_id: True)
    monkeypatch.setattr(
        "storycraftr.llm.factory.get_model_limits",
        lambda model_id: SimpleNamespace(context_length=300000),
    )

    fallbacks = _rankings_fallback_models_for_batch("batch_planning")
    assert fallbacks == ["stepfun/step-3.5-flash:free"]


def test_validate_ranking_consensus_substitutes_non_free_models(monkeypatch, tmp_path):
    rankings_path = tmp_path / "rankings.json"
    payload = _valid_rankings_payload()
    payload["batch_prose"]["primary"] = "openai/gpt-4o-mini"
    payload["batch_editing"]["fallbacks"] = [
        "openai/gpt-4o-mini",
        "stepfun/step-3.5-flash:free",
    ]
    rankings_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    monkeypatch.setattr(
        "storycraftr.llm.factory._OPENROUTER_RANKINGS_PATH", rankings_path
    )
    monkeypatch.setattr(
        "storycraftr.llm.factory.get_free_models",
        lambda force_refresh=False: [
            "z-ai/glm-4.5-air:free",
            "stepfun/step-3.5-flash:free",
            "google/gemma-3-27b-it:free",
            "meta-llama/llama-3.3-70b-instruct:free",
            "openai/gpt-oss-120b:free",
        ],
    )

    validated = validate_ranking_consensus()
    assert validated["batch_prose"]["primary"].endswith(":free")
    assert validated["batch_prose"]["primary"] != "openai/gpt-4o-mini"
    assert validated["batch_editing"]["fallbacks"][0].endswith(":free")
    assert validated["batch_editing"]["fallbacks"][0] != "openai/gpt-4o-mini"


def test_ollama_connection_error_is_actionable(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    with mock.patch(
        "storycraftr.llm.factory.ChatOllama",
        side_effect=ConnectionError("connection refused"),
    ):
        with pytest.raises(LLMInitializationError) as exc:
            build_chat_model(LLMSettings(provider="ollama", model="llama3.2"))

    message = str(exc.value)
    assert "Provider 'ollama'" in message
    assert "model 'llama3.2'" in message
    assert "endpoint 'http://localhost:11434'" in message
    assert "Check if Ollama is running at http://localhost:11434." in message
