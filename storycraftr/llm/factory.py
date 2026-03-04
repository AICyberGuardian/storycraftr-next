from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, Optional, List
from urllib.parse import urlparse

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI
from langchain_community.chat_models import ChatOllama
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.callbacks.manager import CallbackManagerForLLMRun
from rich.console import Console

from storycraftr.llm.credentials import credential_lookup_details

console = Console()


_PROVIDER_DEFAULT_ENV = {
    "openai": "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "ollama": None,
    "fake": None,
}

_OPENROUTER_DEFAULT_ENDPOINT = "https://openrouter.ai/api/v1"
_SUPPORTED_PROVIDERS = {"openai", "openrouter", "ollama", "fake"}

_OPENROUTER_MODEL_REQUIRED_MESSAGE = (
    "Missing 'llm_model' for provider 'openrouter'. Set it explicitly in storycraftr.json, "
    'for example: "llm_provider": "openrouter", "llm_model": "openrouter/free" '
    'or "llm_model": "meta-llama/llama-3.2-3b-instruct:free".'
)


def _endpoint_for_message(provider: str, endpoint: Optional[str]) -> str:
    if endpoint:
        return endpoint
    if provider == "openrouter":
        return _OPENROUTER_DEFAULT_ENDPOINT
    if provider == "ollama":
        return "http://localhost:11434"
    return "provider default"


def _classify_provider_exception(exc: Exception) -> str:
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    if any(
        token in name
        for token in (
            "auth",
            "authentication",
            "permission",
            "forbidden",
            "unauthorized",
        )
    ):
        return "auth"
    if any(
        token in text
        for token in (
            "invalid api key",
            "incorrect api key",
            "unauthorized",
            "forbidden",
            "authentication",
        )
    ):
        return "auth"
    if any(
        token in text
        for token in ("rate limit", "ratelimit", "too many requests", "429")
    ):
        return "rate_limit"
    if any(token in text for token in ("timeout", "timed out")):
        return "timeout"
    if any(
        token in text for token in ("connection", "connect", "refused", "unreachable")
    ):
        return "connection"
    return "unknown"


def _next_action_for_error(
    provider: str, error_kind: str, endpoint: str, env_var: Optional[str]
) -> str:
    if error_kind == "auth":
        if env_var:
            return f"Verify your {env_var} is set and valid."
        return "Verify your provider credentials."
    if error_kind == "timeout":
        return "Retry with a higher request_timeout and verify provider availability."
    if error_kind == "rate_limit":
        return "Wait and retry, or choose another model/provider."
    if provider == "ollama" and error_kind == "connection":
        return f"Check if Ollama is running at {endpoint}."
    if error_kind == "connection":
        return "Check network connectivity and endpoint configuration."
    return "Check provider status and configuration, then retry."


def _raise_provider_error(
    *,
    provider: str,
    model_name: str,
    endpoint: str,
    env_var: Optional[str],
    exc: Exception,
) -> None:
    error_kind = _classify_provider_exception(exc)
    next_action = _next_action_for_error(provider, error_kind, endpoint, env_var)
    message = (
        f"Provider '{provider}' failed to initialize model '{model_name}' "
        f"at endpoint '{endpoint}'. {next_action}"
    )
    if error_kind == "auth":
        raise LLMAuthenticationError(message) from None
    raise LLMInitializationError(message) from None


class LLMConfigurationError(ValueError):
    """Raised when provider or model settings are invalid before model startup."""


class LLMAuthenticationError(RuntimeError):
    """Raised when provider credentials are missing or unreadable."""


class LLMInitializationError(RuntimeError):
    """Raised when a provider client fails to initialize."""


@dataclass
class LLMSettings:
    """Normalized configuration to construct a chat model."""

    provider: str
    model: str
    endpoint: Optional[str] = None
    api_key_env: Optional[str] = None
    temperature: float = 0.7
    request_timeout: Optional[float] = None
    default_headers: Dict[str, str] = field(default_factory=dict)


def _resolve_api_key(
    provider: str,
    explicit_env: Optional[str],
    *,
    model_name: Optional[str] = None,
    endpoint: Optional[str] = None,
) -> Optional[str]:
    env_var = (explicit_env or _PROVIDER_DEFAULT_ENV.get(provider) or "").strip()
    if not env_var:
        raise LLMConfigurationError(
            f"No API key environment variable configured for provider '{provider}'."
        )
    api_key = os.getenv(env_var)
    if not api_key:
        lookup = credential_lookup_details(env_var)
        keyring_usernames = ", ".join(lookup["keyring_usernames"])
        legacy_files = ", ".join(lookup["legacy_files"]) or "(none)"
        endpoint_text = _endpoint_for_message(provider, endpoint)
        model_text = (model_name or "").strip() or "<unset>"
        raise LLMAuthenticationError(
            f"Missing credentials for provider '{provider}'. "
            f"Model '{model_text}', endpoint '{endpoint_text}'. "
            f"Checked environment variable '{env_var}', "
            f"OS keyring service '{lookup['keyring_service']}' "
            f"(usernames: {keyring_usernames}), and legacy files: {legacy_files}. "
            f"Verify your {env_var} is set and valid."
        )
    return api_key


def _normalize_provider(provider: str) -> str:
    normalized = (provider or "").strip().lower()
    if not normalized:
        raise LLMConfigurationError(
            "Missing LLM provider. Set 'llm_provider' in storycraftr.json."
        )
    if normalized not in _SUPPORTED_PROVIDERS:
        supported = ", ".join(sorted(_SUPPORTED_PROVIDERS))
        raise LLMConfigurationError(
            f"Unsupported LLM provider '{provider}'. Supported providers: {supported}."
        )
    return normalized


def _validate_model(provider: str, model: str) -> str:
    model_text = "" if model is None else str(model)
    if provider == "openrouter":
        if not model_text.strip():
            raise LLMConfigurationError(_OPENROUTER_MODEL_REQUIRED_MESSAGE)

        if "/" not in model_text:
            raise LLMConfigurationError(
                "OpenRouter requires an explicit provider/model identifier in "
                "'llm_model' (for example 'meta-llama/llama-3.3-70b-instruct')."
            )
        owner, model_slug = model_text.split("/", 1)
        if not owner.strip() or not model_slug.strip():
            raise LLMConfigurationError(
                "Invalid OpenRouter model identifier. Expected 'provider/model'."
            )
        return model_text

    model_name = model_text.strip()
    if not model_name:
        raise LLMConfigurationError(
            f"Missing 'llm_model' for provider '{provider}'. "
            "Set an explicit model in storycraftr.json."
        )
    return model_name


def _validate_temperature(temperature: float) -> None:
    if not isinstance(temperature, (int, float)):
        raise LLMConfigurationError("Temperature must be a number.")
    if temperature < 0 or temperature > 2:
        raise LLMConfigurationError("Temperature must be between 0 and 2.")


def _validate_request_timeout(request_timeout: Optional[float]) -> None:
    if request_timeout is None:
        return
    if request_timeout <= 0:
        raise LLMConfigurationError("Request timeout must be greater than zero.")


def _validate_endpoint(provider: str, endpoint: Optional[str]) -> None:
    if not endpoint:
        return
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise LLMConfigurationError(
            f"Invalid endpoint '{endpoint}' for provider '{provider}'. "
            "Use a full URL such as 'https://host/api/v1'."
        )


def build_chat_model(settings: LLMSettings) -> BaseChatModel:
    """
    Build a LangChain chat model according to the supplied settings.

    Raises:
        RuntimeError: if required credentials are missing.
        ValueError: if the provider is unsupported.
    """

    provider = _normalize_provider(settings.provider)

    if provider == "fake":
        return _OfflineChatModel(
            template=(
                "Offline placeholder response for '{prompt}'. "
                "Set llm_provider to openai/openrouter/ollama for real generations."
            )
        )

    model_name = _validate_model(provider, settings.model)
    _validate_temperature(settings.temperature)
    _validate_request_timeout(settings.request_timeout)

    if provider in ("openai", "openrouter"):
        base_url = settings.endpoint or (
            os.getenv("OPENROUTER_BASE_URL") if provider == "openrouter" else None
        )
        if provider == "openrouter" and not base_url:
            base_url = _OPENROUTER_DEFAULT_ENDPOINT
        endpoint_text = _endpoint_for_message(provider, base_url)
        api_key_env = (
            settings.api_key_env or _PROVIDER_DEFAULT_ENV.get(provider) or ""
        ).strip()
        api_key = _resolve_api_key(
            provider,
            settings.api_key_env,
            model_name=model_name,
            endpoint=base_url,
        )
        _validate_endpoint(provider, base_url)
        params: Dict[str, object] = {
            "model": model_name,
            "temperature": settings.temperature,
        }
        if settings.request_timeout is not None:
            params["timeout"] = settings.request_timeout
        if base_url:
            params["base_url"] = base_url

        headers: Dict[str, str] = {}
        headers.update(settings.default_headers or {})
        if provider == "openrouter":
            headers.setdefault(
                "HTTP-Referer",
                os.getenv("STORYCRAFTR_HTTP_REFERER", "https://storycraftr.app"),
            )
            headers.setdefault(
                "X-Title", os.getenv("STORYCRAFTR_APP_NAME", "StoryCraftr CLI")
            )
        if headers:
            params["default_headers"] = headers

        try:
            return ChatOpenAI(api_key=api_key, **params)
        except Exception as exc:
            _raise_provider_error(
                provider=provider,
                model_name=model_name,
                endpoint=endpoint_text,
                env_var=api_key_env,
                exc=exc,
            )

    if provider == "ollama":
        base_url = settings.endpoint or os.getenv("OLLAMA_BASE_URL")
        endpoint_text = _endpoint_for_message(provider, base_url)
        _validate_endpoint(provider, base_url)
        params = {
            "model": model_name,
            "temperature": settings.temperature,
        }
        if base_url:
            params["base_url"] = base_url
        if settings.request_timeout is not None:
            params["timeout"] = settings.request_timeout

        try:
            return ChatOllama(**params)
        except Exception as exc:
            _raise_provider_error(
                provider=provider,
                model_name=model_name,
                endpoint=endpoint_text,
                env_var=None,
                exc=exc,
            )

    raise LLMConfigurationError(f"Unsupported LLM provider '{settings.provider}'.")


class _OfflineChatModel(BaseChatModel):
    """Minimal offline chat model that returns placeholder responses."""

    template: str = (
        "Offline placeholder response for '{prompt}'. "
        "Set llm_provider to openai/openrouter/ollama for real generations."
    )

    def __init__(self, template: str):
        super().__init__(template=template)

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs,
    ) -> ChatResult:
        prompt_text = ""
        if messages:
            last_message = messages[-1]
            prompt_text = getattr(last_message, "content", str(last_message))
        content = self.template.format(prompt=prompt_text)
        generation = ChatGeneration(message=AIMessage(content=content))
        return ChatResult(generations=[generation])

    @property
    def _llm_type(self) -> str:
        return "offline-placeholder"
