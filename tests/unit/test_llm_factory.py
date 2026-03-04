from unittest import mock

import pytest

from storycraftr.llm.factory import (
    LLMAuthenticationError,
    LLMConfigurationError,
    LLMInitializationError,
    LLMSettings,
    build_chat_model,
)


@pytest.fixture(autouse=True)
def clean_llm_env(monkeypatch):
    for env_var in (
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "OPENROUTER_BASE_URL",
        "CUSTOM_OPENROUTER_KEY",
        "OLLAMA_BASE_URL",
        "STORYCRAFTR_HTTP_REFERER",
        "STORYCRAFTR_APP_NAME",
    ):
        monkeypatch.delenv(env_var, raising=False)


def test_openrouter_requires_explicit_provider_model(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")

    settings = LLMSettings(provider="openrouter", model="gpt-4o")

    with pytest.raises(LLMConfigurationError, match="provider/model"):
        build_chat_model(settings)


def test_openrouter_missing_api_key_raises_provider_auth_error():
    settings = LLMSettings(
        provider="openrouter",
        model="meta-llama/llama-3.3-70b-instruct",
    )

    with pytest.raises(LLMAuthenticationError, match="OPENROUTER_API_KEY"):
        build_chat_model(settings)


def test_openrouter_builds_chatopenai_with_default_endpoint_and_headers(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")

    with mock.patch("storycraftr.llm.factory.ChatOpenAI") as mock_chat_openai:
        mock_chat_openai.return_value = object()

        settings = LLMSettings(
            provider="openrouter",
            model="meta-llama/llama-3.3-70b-instruct",
            request_timeout=30,
        )
        result = build_chat_model(settings)

    assert result is mock_chat_openai.return_value
    kwargs = mock_chat_openai.call_args.kwargs
    assert kwargs["api_key"] == "or-test"  # pragma: allowlist secret
    assert kwargs["model"] == "meta-llama/llama-3.3-70b-instruct"
    assert kwargs["base_url"] == "https://openrouter.ai/api/v1"
    assert kwargs["timeout"] == 30
    assert kwargs["default_headers"]["HTTP-Referer"] == "https://storycraftr.app"
    assert kwargs["default_headers"]["X-Title"] == "StoryCraftr CLI"


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

    assert result is mock_chat_openai.return_value
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

    assert result is mock_chat_openai.return_value
    assert (
        mock_chat_openai.call_args.kwargs["base_url"] == "https://explicit.example/v1"
    )


def test_openrouter_honors_custom_api_key_env_override(monkeypatch):
    monkeypatch.setenv("CUSTOM_OPENROUTER_KEY", "or-custom")  # pragma: allowlist secret

    with mock.patch("storycraftr.llm.factory.ChatOpenAI") as mock_chat_openai:
        mock_chat_openai.return_value = object()
        result = build_chat_model(
            LLMSettings(
                provider="openrouter",
                model="meta-llama/llama-3.3-70b-instruct",
                api_key_env="CUSTOM_OPENROUTER_KEY",
            )
        )

    assert result is mock_chat_openai.return_value
    assert (
        mock_chat_openai.call_args.kwargs["api_key"]
        == "or-custom"  # pragma: allowlist secret
    )


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
