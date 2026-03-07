from unittest import mock

import pytest

from storycraftr.llm.factory import (
    LLMAuthenticationError,
    LLMConfigurationError,
    LLMInitializationError,
    LLMSettings,
    build_chat_model,
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
    assert kwargs["max_tokens"] == 8192
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

    assert result is mock_chat_openai.return_value
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
        with mock.patch("storycraftr.llm.factory.console.print") as mock_print:
            build_chat_model(
                LLMSettings(
                    provider="openrouter",
                    model="meta-llama/llama-3.3-70b-instruct",
                )
            )

    printed = "\n".join(str(call.args[0]) for call in mock_print.call_args_list)
    assert "or-super-secret" not in printed


def test_openrouter_success_on_primary_first_attempt_is_not_noisy(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")

    mock_result = object()
    primary = mock.Mock()
    primary._generate.return_value = mock_result
    with mock.patch("storycraftr.llm.factory.ChatOpenAI", return_value=primary):
        with mock.patch("storycraftr.llm.factory.console.print") as mock_print:
            model = build_chat_model(
                LLMSettings(
                    provider="openrouter",
                    model="openrouter/free",
                )
            )
            result = model._generate(messages=[], stop=None, run_manager=None)

    assert result is mock_result
    assert mock_print.call_count == 0


def test_openrouter_wrapper_retries_then_succeeds(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")

    mock_result = object()
    primary = mock.Mock()
    primary._generate.side_effect = [
        TimeoutError("timed out"),
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
    assert primary._generate.call_count == 3
    assert mock_sleep.call_count == 2


def test_openrouter_wrapper_falls_back_after_retry_exhaustion(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")

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
                    model="meta-llama/llama-3.3-70b-instruct",
                )
            )
            result = model._generate(messages=[], stop=None, run_manager=None)

    assert result is fallback_result
    assert primary._generate.call_count == 3
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
