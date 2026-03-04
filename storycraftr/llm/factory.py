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

console = Console()


_PROVIDER_DEFAULT_ENV = {
    "openai": "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "ollama": None,
    "fake": None,
}

_OPENROUTER_DEFAULT_ENDPOINT = "https://openrouter.ai/api/v1"
_SUPPORTED_PROVIDERS = {"openai", "openrouter", "ollama", "fake"}


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


def _resolve_api_key(provider: str, explicit_env: Optional[str]) -> Optional[str]:
    env_var = (explicit_env or _PROVIDER_DEFAULT_ENV.get(provider) or "").strip()
    if not env_var:
        raise LLMConfigurationError(
            f"No API key environment variable configured for provider '{provider}'."
        )
    api_key = os.getenv(env_var)
    if not api_key:
        raise LLMAuthenticationError(
            f"Missing environment variable '{env_var}' required for provider '{provider}'."
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
    model_name = (model or "").strip()
    if not model_name:
        raise LLMConfigurationError(
            f"Missing 'llm_model' for provider '{provider}'. "
            "Set an explicit model in storycraftr.json."
        )

    if provider == "openrouter":
        if "/" not in model_name:
            raise LLMConfigurationError(
                "OpenRouter requires an explicit provider/model identifier in "
                "'llm_model' (for example 'meta-llama/llama-3.3-70b-instruct')."
            )
        owner, model_slug = model_name.split("/", 1)
        if not owner.strip() or not model_slug.strip():
            raise LLMConfigurationError(
                "Invalid OpenRouter model identifier. Expected 'provider/model'."
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
        api_key = _resolve_api_key(provider, settings.api_key_env)
        base_url = settings.endpoint or (
            os.getenv("OPENROUTER_BASE_URL") if provider == "openrouter" else None
        )
        if provider == "openrouter" and not base_url:
            base_url = _OPENROUTER_DEFAULT_ENDPOINT
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
            raise LLMInitializationError(
                f"Failed to initialize provider '{provider}' with model '{model_name}'."
            ) from exc

    if provider == "ollama":
        base_url = settings.endpoint or os.getenv("OLLAMA_BASE_URL")
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
            raise LLMInitializationError(
                f"Failed to initialize provider 'ollama' with model '{model_name}'."
            ) from exc

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
