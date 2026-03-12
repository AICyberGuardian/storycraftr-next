from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import pybreaker
import structlog
import tiktoken
from langchain_community.chat_models import ChatOllama
from langchain_core.callbacks.manager import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_openai import ChatOpenAI
from tenacity import Retrying, retry_if_exception, stop_after_attempt, wait_exponential

from storycraftr.llm.credentials import credential_lookup_details
from storycraftr.llm.openrouter_discovery import (
    get_free_models,
    get_model_limits,
    is_model_free,
)

_OPENROUTER_LOGGER = structlog.get_logger("storycraftr.openrouter")


_PROVIDER_DEFAULT_ENV = {
    "openai": "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "ollama": None,
    "fake": None,
}

_OPENROUTER_DEFAULT_ENDPOINT = "https://openrouter.ai/api/v1"
_SUPPORTED_PROVIDERS = {"openai", "openrouter", "ollama", "fake"}
_OPENROUTER_FALLBACK_MODELS_ENV = "STORYCRAFTR_OPENROUTER_FALLBACK_MODELS"
_OPENROUTER_BATCH_ENV = "STORYCRAFTR_OPENROUTER_BATCH"
_OPENROUTER_RANKINGS_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "rankings.json"
)
_OPENROUTER_RETRY_BASE_SECONDS = 10.0
_OPENROUTER_MAX_BACKOFF_SECONDS = 60.0
_OPENROUTER_MAX_ATTEMPTS = 3
_OPENROUTER_PRIMARY_RATE_LIMIT_FAILOVER_THRESHOLD = 2
_OPENROUTER_ALLOW_FREE_PROSE_ENV = "STORYCRAFTR_ALLOW_OPENROUTER_FREE_PROSE"
_OPENROUTER_RANKING_ROLES = {
    "batch_planning",
    "batch_prose",
    "batch_editing",
    "repair_json",
    "coherence_check",
}
_OPENROUTER_MODEL_ID_PATTERN = re.compile(
    r"^(openrouter/free|[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*(?::free))$"
)
_OPENROUTER_REPAIR_JSON_PRIMARY_ALLOWLIST = {
    "google/gemma-3-27b-it:free",
    "stepfun/step-3.5-flash:free",
    "openai/gpt-oss-120b:free",
}
_OPENROUTER_DEFAULT_MAX_TOKENS = 4000
_MODEL_HEALTH_MAX_MEAN_LATENCY_SECONDS = 300.0
_MODEL_HEALTH_MAX_ERRORS = 3
_MODEL_HEALTH_QUARANTINE_THRESHOLD = 2
_MODEL_HEALTH_QUARANTINE_SECONDS = 600
_OPENROUTER_BREAKER_FAIL_MAX = 3
_OPENROUTER_BREAKER_RESET_SECONDS = 60
_TOKEN_COUNT_FALLBACK_ENCODING = "cl100k_base"  # nosec B105
_PROVIDER_RETRY_BASE_SECONDS = 2.0
_PROVIDER_MAX_BACKOFF_SECONDS = 20.0
_PROVIDER_MAX_ATTEMPTS = 3
_PROVIDER_BREAKER_FAIL_MAX = 3
_PROVIDER_BREAKER_RESET_SECONDS = 30
_OPENAI_DEFAULT_CONTEXT_LENGTH = 128000
_OLLAMA_DEFAULT_CONTEXT_LENGTH = 8192

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
        token in text
        for token in (
            "500",
            "502",
            "503",
            "504",
            "bad gateway",
            "gateway timeout",
            "service unavailable",
            "server error",
        )
    ):
        return "server_error"
    if any(
        token in text for token in ("connection", "connect", "refused", "unreachable")
    ):
        return "connection"
    if any(token in text for token in ("empty response", "no content returned")):
        return "empty_response"
    return "unknown"


def _extract_provider_error_details(exc: Exception) -> tuple[str, str]:
    """Extract stable HTTP status and raw payload text from provider exceptions."""

    status = _extract_http_status_code(exc)
    response = getattr(exc, "response", None)
    raw_body = ""

    if response is not None:
        response_text = getattr(response, "text", None)
        if isinstance(response_text, str) and response_text.strip():
            raw_body = response_text.strip()

    if not raw_body:
        body = getattr(exc, "body", None)
        if isinstance(body, str):
            raw_body = body.strip()
        elif body is not None:
            raw_body = str(body).strip()

    if not raw_body:
        raw_body = str(exc).strip() or "<no-error-body>"

    code = str(status) if isinstance(status, int) else "unknown"
    return code, raw_body


def _sanitize_error_text(text: str, secrets: list[str]) -> str:
    sanitized = text
    for secret in secrets:
        if secret:
            sanitized = sanitized.replace(secret, "***")
    return sanitized


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
    detail_prefix = ""
    if provider == "openrouter":
        code, raw_body = _extract_provider_error_details(exc)
        sanitized_body = raw_body
        if env_var:
            secret = os.getenv(env_var)
            if secret:
                sanitized_body = _sanitize_error_text(raw_body, [secret])
        detail_prefix = f" OpenRouter Error [{code}]: {sanitized_body}."
    message = (
        f"Provider '{provider}' failed to initialize model '{model_name}' "
        f"at endpoint '{endpoint}'.{detail_prefix} {next_action}"
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


class LLMInvocationError(RuntimeError):
    """Raised when provider invocation fails with structured telemetry."""

    def __init__(
        self,
        message: str,
        *,
        transport_error: dict[str, Any] | None = None,
        quarantine_events: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.transport_error = dict(transport_error or {})
        self.quarantine_events = [
            dict(row) for row in (quarantine_events or []) if isinstance(row, dict)
        ]


class _PrimaryRateLimitFailover(RuntimeError):
    """Signal early model rotation after repeated primary 429 responses."""


class _QuarantinedModelFailover(RuntimeError):
    """Signal immediate model rotation once transient failures trigger quarantine."""


@dataclass
class LLMSettings:
    """Normalized configuration to construct a chat model."""

    provider: str
    model: str
    endpoint: Optional[str] = None
    api_key_env: Optional[str] = None
    temperature: float = 0.7
    request_timeout: Optional[float] = None
    max_tokens: Optional[int] = 8192
    default_headers: Dict[str, str] = field(default_factory=dict)


@dataclass
class ModelHealthStats:
    """In-memory per-model health counters for the current process/session."""

    latency_samples: List[float] = field(default_factory=list)
    error_count: int = 0
    empty_response_count: int = 0
    rate_limit_count: int = 0
    service_unavailable_count: int = 0
    quarantined_until: float = 0.0
    degraded: bool = False

    @property
    def mean_latency(self) -> float:
        if not self.latency_samples:
            return 0.0
        return sum(self.latency_samples) / len(self.latency_samples)


class ModelHealthRegistry:
    """Track per-model runtime health and quarantine degraded model IDs."""

    def __init__(self) -> None:
        self._stats: Dict[str, ModelHealthStats] = {}
        self._transient_streaks: Dict[str, tuple[str, int]] = {}

    def _key(self, model_id: str) -> str:
        return str(model_id).strip().lower()

    def _entry(self, model_id: str) -> ModelHealthStats:
        key = self._key(model_id)
        if key not in self._stats:
            self._stats[key] = ModelHealthStats()
        return self._stats[key]

    def record_success(self, model_id: str, *, latency_seconds: float) -> None:
        entry = self._entry(model_id)
        entry.latency_samples.append(max(0.0, float(latency_seconds)))
        entry.rate_limit_count = 0
        entry.service_unavailable_count = 0
        self._clear_transient_streaks_for_model(model_id)
        self._refresh_degraded(entry)

    def record_error(self, model_id: str) -> None:
        entry = self._entry(model_id)
        entry.error_count += 1
        self._refresh_degraded(entry)

    def record_empty_response(self, model_id: str) -> None:
        entry = self._entry(model_id)
        entry.empty_response_count += 1
        entry.error_count += 1
        self._refresh_degraded(entry)

    def is_degraded(self, model_id: str) -> bool:
        return self._entry(model_id).degraded

    def is_quarantined(self, model_id: str) -> bool:
        entry = self._entry(model_id)
        if entry.quarantined_until <= 0:
            return False
        if time.time() >= entry.quarantined_until:
            entry.quarantined_until = 0.0
            entry.rate_limit_count = 0
            entry.service_unavailable_count = 0
            return False
        return True

    def mark_degraded(self, model_id: str) -> None:
        self._entry(model_id).degraded = True

    def mark_quarantined(self, model_id: str, *, seconds: int) -> None:
        entry = self._entry(model_id)
        entry.quarantined_until = time.time() + max(1, int(seconds))

    def record_http_failure(self, model_id: str, *, status_code: int | None) -> None:
        """Track repeat 429/503 failures and quarantine unstable models."""

        entry = self._entry(model_id)
        if status_code == 429:
            entry.rate_limit_count += 1
        elif status_code == 503:
            entry.service_unavailable_count += 1

        if (
            entry.rate_limit_count >= _MODEL_HEALTH_QUARANTINE_THRESHOLD
            or entry.service_unavailable_count >= _MODEL_HEALTH_QUARANTINE_THRESHOLD
        ):
            self.mark_quarantined(
                model_id,
                seconds=_MODEL_HEALTH_QUARANTINE_SECONDS,
            )

    def reset(self) -> None:
        self._stats.clear()
        self._transient_streaks.clear()

    def record_stage_transient_failure(
        self,
        model_id: str,
        *,
        stage_name: str,
        failure_signature: str,
    ) -> bool:
        """Track stage/model consecutive transient failures and quarantine quickly."""

        normalized_stage = str(stage_name or "unknown").strip().lower() or "unknown"
        normalized_signature = str(failure_signature).strip().lower()
        if not normalized_signature:
            return False

        key = f"{normalized_stage}|{self._key(model_id)}"
        prior_signature, prior_count = self._transient_streaks.get(key, ("", 0))
        if prior_signature == normalized_signature:
            current_count = prior_count + 1
        else:
            current_count = 1
        self._transient_streaks[key] = (normalized_signature, current_count)

        if current_count >= _MODEL_HEALTH_QUARANTINE_THRESHOLD:
            self.mark_quarantined(model_id, seconds=_MODEL_HEALTH_QUARANTINE_SECONDS)
            return True
        return False

    def _clear_transient_streaks_for_model(self, model_id: str) -> None:
        model_key = self._key(model_id)
        prefix = f"|{model_key}"
        stale = [key for key in self._transient_streaks.keys() if key.endswith(prefix)]
        for key in stale:
            self._transient_streaks.pop(key, None)

    def snapshot(self) -> Dict[str, Dict[str, float | int | bool]]:
        rows: Dict[str, Dict[str, float | int | bool]] = {}
        for model_id, entry in self._stats.items():
            rows[model_id] = {
                "mean_latency": entry.mean_latency,
                "error_count": entry.error_count,
                "empty_response_count": entry.empty_response_count,
                "rate_limit_count": entry.rate_limit_count,
                "service_unavailable_count": entry.service_unavailable_count,
                "quarantined_until": entry.quarantined_until,
                "degraded": entry.degraded,
            }
        return rows

    def _refresh_degraded(self, entry: ModelHealthStats) -> None:
        entry.degraded = (
            entry.error_count > _MODEL_HEALTH_MAX_ERRORS
            or entry.mean_latency > _MODEL_HEALTH_MAX_MEAN_LATENCY_SECONDS
        )


_MODEL_HEALTH_REGISTRY = ModelHealthRegistry()
_OPENROUTER_CIRCUIT_BREAKERS: Dict[str, pybreaker.CircuitBreaker] = {}
_PROVIDER_CIRCUIT_BREAKERS: Dict[str, pybreaker.CircuitBreaker] = {}


def get_model_health_registry() -> ModelHealthRegistry:
    """Return process-local model health registry used by resilient routing."""

    return _MODEL_HEALTH_REGISTRY


def _openrouter_circuit_breaker(model_name: str) -> pybreaker.CircuitBreaker:
    """Return process-local circuit breaker per model ID."""

    key = str(model_name).strip().lower()
    breaker = _OPENROUTER_CIRCUIT_BREAKERS.get(key)
    if breaker is None:
        breaker = pybreaker.CircuitBreaker(
            fail_max=_OPENROUTER_BREAKER_FAIL_MAX,
            reset_timeout=_OPENROUTER_BREAKER_RESET_SECONDS,
        )
        _OPENROUTER_CIRCUIT_BREAKERS[key] = breaker
    return breaker


def _provider_circuit_breaker(
    provider_name: str,
    model_name: str,
) -> pybreaker.CircuitBreaker:
    """Return process-local circuit breaker for non-OpenRouter providers."""

    key = f"{str(provider_name).strip().lower()}::{str(model_name).strip().lower()}"
    breaker = _PROVIDER_CIRCUIT_BREAKERS.get(key)
    if breaker is None:
        breaker = pybreaker.CircuitBreaker(
            fail_max=_PROVIDER_BREAKER_FAIL_MAX,
            reset_timeout=_PROVIDER_BREAKER_RESET_SECONDS,
        )
        _PROVIDER_CIRCUIT_BREAKERS[key] = breaker
    return breaker


def _should_retry_openrouter_exception(exc: BaseException) -> bool:
    """Retry only transient provider errors; fail closed on auth/breaker signals."""

    if not isinstance(exc, Exception):
        return False
    if isinstance(
        exc,
        (
            pybreaker.CircuitBreakerError,
            _PrimaryRateLimitFailover,
            _QuarantinedModelFailover,
        ),
    ):
        return False
    error_kind = _classify_provider_exception(exc)
    if error_kind == "auth":
        return False
    return error_kind in {
        "rate_limit",
        "timeout",
        "connection",
        "server_error",
        "empty_response",
    } or _is_http_5xx(exc)


def _should_retry_provider_exception(exc: BaseException) -> bool:
    """Retry transient non-auth provider invocation failures."""

    if not isinstance(exc, Exception):
        return False
    if isinstance(exc, pybreaker.CircuitBreakerError):
        return False
    error_kind = _classify_provider_exception(exc)
    if error_kind == "auth":
        return False
    return error_kind in {
        "rate_limit",
        "timeout",
        "connection",
        "server_error",
        "empty_response",
    } or _is_http_5xx(exc)


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


def _validate_max_tokens(max_tokens: Optional[int]) -> None:
    if max_tokens is None:
        return
    if not isinstance(max_tokens, int):
        raise LLMConfigurationError("max_tokens must be an integer.")
    if max_tokens <= 0:
        raise LLMConfigurationError("max_tokens must be greater than zero.")


def _validate_endpoint(provider: str, endpoint: Optional[str]) -> None:
    if not endpoint:
        return
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise LLMConfigurationError(
            f"Invalid endpoint '{endpoint}' for provider '{provider}'. "
            "Use a full URL such as 'https://host/api/v1'."
        )


def _parse_openrouter_fallback_models(raw: str | None) -> list[str]:
    if not raw:
        return []
    models: list[str] = []
    seen: set[str] = set()
    for candidate in raw.split(","):
        model = candidate.strip()
        if not model or model in seen:
            continue
        seen.add(model)
        models.append(model)
    return models


def _openrouter_fallback_chain(primary_model: str) -> list[str]:
    chain: list[str] = []
    seen: set[str] = set()

    def append_unique(models: list[str]) -> None:
        for model in models:
            if model and model not in seen:
                seen.add(model)
                chain.append(model)

    batch = (os.getenv(_OPENROUTER_BATCH_ENV) or "").strip()
    append_unique(_rankings_fallback_models_for_batch(batch))
    append_unique(
        _parse_openrouter_fallback_models(os.getenv(_OPENROUTER_FALLBACK_MODELS_ENV))
    )
    return [model for model in chain if model != primary_model]


def _load_openrouter_rankings() -> dict[str, Any]:
    """Load ranked OpenRouter task batches from storycraftr/config/rankings.json."""
    try:
        raw = _OPENROUTER_RANKINGS_PATH.read_text(encoding="utf-8")
    except OSError:
        return {}

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        _OPENROUTER_LOGGER.warning(
            "openrouter_rankings_malformed",
            path=str(_OPENROUTER_RANKINGS_PATH),
        )
        return {}

    if not isinstance(data, dict):
        return {}

    try:
        return _validate_openrouter_rankings(data)
    except ValueError as exc:
        _OPENROUTER_LOGGER.warning(
            "openrouter_rankings_invalid",
            path=str(_OPENROUTER_RANKINGS_PATH),
            error=str(exc),
        )
        return {}


def validate_openrouter_rankings_config() -> dict[str, Any]:
    """Validate rankings.json and return normalized config or raise an error.

    This helper is used by CLI diagnostics so users can fail fast with a
    specific message instead of silently falling back to env-only routing.
    """

    try:
        raw = _OPENROUTER_RANKINGS_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise LLMConfigurationError(
            "OpenRouter rankings config is missing or unreadable at "
            f"'{_OPENROUTER_RANKINGS_PATH}'."
        ) from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LLMConfigurationError(
            "OpenRouter rankings config is malformed JSON at "
            f"'{_OPENROUTER_RANKINGS_PATH}'."
        ) from exc

    if not isinstance(data, dict):
        raise LLMConfigurationError("OpenRouter rankings config must be a JSON object.")

    try:
        return _validate_openrouter_rankings(data)
    except ValueError as exc:
        raise LLMConfigurationError(
            f"OpenRouter rankings config failed strict validation: {exc}"
        ) from exc


def validate_ranking_consensus(
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Pre-flight: verify all ranking models are currently free; auto-substitute paid ones.

    Loads rankings.json and queries the OpenRouter discovery catalog (cached by default).
    For each role, if the primary or fallback model is paid/unavailable it is replaced with
    the next free candidate in the live catalog.  Raises ``LLMConfigurationError`` if no
    free model is available for any required role.

    Must be called BEFORE Chapter 1 begins so no generation tokens are spent on a
    misconfigured model.

    Returns:
        Validated (possibly substituted) rankings dict ready for runtime use.
    """
    try:
        raw = _OPENROUTER_RANKINGS_PATH.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise LLMConfigurationError(
            f"Pre-flight cannot read OpenRouter rankings config: {exc}"
        ) from exc

    if not isinstance(data, dict):
        raise LLMConfigurationError("OpenRouter rankings config must be a JSON object.")

    expected_roles = _OPENROUTER_RANKING_ROLES
    if set(data.keys()) != expected_roles:
        expected = ", ".join(sorted(expected_roles))
        found = ", ".join(sorted(data.keys()))
        raise LLMConfigurationError(
            f"OpenRouter rankings config has invalid roles; "
            f"expected [{expected}], found [{found}]."
        )

    free_models = get_free_models(force_refresh=force_refresh)
    free_ids_ordered: list[str] = []
    for entry in free_models:
        model_id = getattr(entry, "model_id", entry)
        if isinstance(model_id, str):
            cleaned = model_id.strip()
            if cleaned:
                free_ids_ordered.append(cleaned)
    free_ids_lower: set[str] = {model_id.lower() for model_id in free_ids_ordered}

    def _model_is_free(model_id: str) -> bool:
        return model_id == "openrouter/free" or model_id.lower() in free_ids_lower

    def _next_free_excluding(exclude: set[str]) -> Optional[str]:
        for candidate in free_ids_ordered:
            if candidate.lower() not in {e.lower() for e in exclude}:
                return candidate
        return None

    result: dict[str, Any] = {}
    for role, entry in data.items():
        if not isinstance(entry, dict):
            raise LLMConfigurationError(f"rankings.{role} must be a JSON object.")

        primary = str(entry.get("primary", "")).strip()
        fallbacks: list[str] = [str(fb).strip() for fb in entry.get("fallbacks", [])]
        used_in_role: set[str] = set()

        # Validate / substitute primary
        if _model_is_free(primary):
            new_primary = primary
            used_in_role.add(primary.lower())
        else:
            exclude = {primary.lower()} | {fb.lower() for fb in fallbacks}
            sub = _next_free_excluding(exclude)
            if sub is None:
                raise LLMConfigurationError(
                    f"Pre-flight consensus failed for role '{role}': primary model "
                    f"'{primary}' is not currently free and no free substitute is "
                    "available. Update rankings.json or wait for a free model slot."
                )
            _OPENROUTER_LOGGER.warning(
                "openrouter_preflight_primary_substituted",
                role=role,
                previous_model=primary,
                substituted_model=sub,
            )
            new_primary = sub
            used_in_role.add(sub.lower())

        # Validate / substitute fallbacks
        new_fallbacks: list[str] = []
        for fb in fallbacks:
            if _model_is_free(fb) and fb.lower() not in used_in_role:
                new_fallbacks.append(fb)
                used_in_role.add(fb.lower())
            else:
                sub = _next_free_excluding(used_in_role)
                if sub is not None:
                    _OPENROUTER_LOGGER.warning(
                        "openrouter_preflight_fallback_substituted",
                        role=role,
                        previous_model=fb,
                        substituted_model=sub,
                    )
                    new_fallbacks.append(sub)
                    used_in_role.add(sub.lower())
                # Fewer fallbacks is acceptable; fail only when primary has no free path.

        new_entry = dict(entry)
        new_entry["primary"] = new_primary
        new_entry["fallbacks"] = new_fallbacks
        result[role] = new_entry

    return result


def _openrouter_allow_free_prose() -> bool:
    """Return True when openrouter/free is explicitly allowed for prose batches."""

    value = (os.getenv(_OPENROUTER_ALLOW_FREE_PROSE_ENV) or "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _validate_openrouter_model_id(model_id: str) -> str:
    """Validate and normalize a rankings model ID."""

    normalized = (model_id or "").strip()
    if not _OPENROUTER_MODEL_ID_PATTERN.fullmatch(normalized):
        raise ValueError("model IDs must be 'openrouter/free' or 'provider/model:free'")
    return normalized


def _validate_openrouter_rankings(data: dict[str, Any]) -> dict[str, Any]:
    """Validate rankings.json with fail-closed semantics and runtime constraints."""

    keys = set(data.keys())
    if keys != _OPENROUTER_RANKING_ROLES:
        expected = ", ".join(sorted(_OPENROUTER_RANKING_ROLES))
        found = ", ".join(sorted(keys))
        raise ValueError(f"expected keys [{expected}] but found [{found}]")

    normalized: dict[str, dict[str, Any]] = {}
    allow_free_prose = _openrouter_allow_free_prose()

    for role in sorted(_OPENROUTER_RANKING_ROLES):
        raw_entry = data.get(role)
        if not isinstance(raw_entry, dict):
            raise ValueError(f"{role} must be an object")

        allowed_keys = {"primary", "fallbacks", "why"}
        if role == "coherence_check":
            allowed_keys.add("context_limit")
        if set(raw_entry.keys()) != allowed_keys and not (
            role == "coherence_check"
            and set(raw_entry.keys()) == {"primary", "fallbacks", "why"}
        ):
            allowed = ", ".join(sorted(allowed_keys))
            raise ValueError(f"{role} has invalid keys; allowed keys are [{allowed}]")

        primary = _validate_openrouter_model_id(str(raw_entry.get("primary", "")))

        raw_fallbacks = raw_entry.get("fallbacks")
        if not isinstance(raw_fallbacks, list):
            raise ValueError(f"{role}.fallbacks must be a list")
        if len(raw_fallbacks) < 1 or len(raw_fallbacks) > 5:
            raise ValueError(f"{role}.fallbacks must contain between 1 and 5 items")

        fallbacks: list[str] = []
        seen_fallbacks: set[str] = set()
        for item in raw_fallbacks:
            model_id = _validate_openrouter_model_id(str(item))
            if model_id in seen_fallbacks:
                raise ValueError(f"{role}.fallbacks must not contain duplicates")
            seen_fallbacks.add(model_id)
            fallbacks.append(model_id)

        why = str(raw_entry.get("why", "")).strip()
        if len(why) < 12 or len(why) > 500:
            raise ValueError(f"{role}.why must be between 12 and 500 characters")

        if primary in fallbacks:
            raise ValueError(f"{role}.primary must not appear in {role}.fallbacks")

        role_models = [primary, *fallbacks]
        if len(set(role_models)) != len(role_models):
            raise ValueError(f"{role} contains duplicate model IDs")

        if (
            role == "batch_prose"
            and not allow_free_prose
            and "openrouter/free" in role_models
        ):
            raise ValueError(
                "openrouter/free is not allowed for batch_prose unless "
                f"{_OPENROUTER_ALLOW_FREE_PROSE_ENV}=1"
            )

        if (
            role == "repair_json"
            and primary not in _OPENROUTER_REPAIR_JSON_PRIMARY_ALLOWLIST
        ):
            allowlist_text = ", ".join(
                sorted(_OPENROUTER_REPAIR_JSON_PRIMARY_ALLOWLIST)
            )
            raise ValueError(f"repair_json.primary must be one of: {allowlist_text}")

        for model_id in role_models:
            if not is_model_free(model_id):
                raise ValueError(
                    f"{role} contains model '{model_id}' that is not currently "
                    "free/available"
                )

        entry: dict[str, Any] = {
            "primary": primary,
            "fallbacks": fallbacks,
            "why": why,
        }

        if role == "coherence_check":
            if "context_limit" in raw_entry:
                context_limit = raw_entry.get("context_limit")
                if not isinstance(context_limit, int):
                    raise ValueError("coherence_check.context_limit must be an integer")
                if context_limit < 4096 or context_limit > 2_000_000:
                    raise ValueError(
                        "coherence_check.context_limit must be between 4096 and 2000000"
                    )

                primary_limits = get_model_limits(primary)
                if primary_limits is None:
                    raise ValueError(
                        "coherence_check.primary context window could not be verified"
                    )
                if context_limit > primary_limits.context_length:
                    raise ValueError(
                        "coherence_check.context_limit exceeds discovered "
                        f"context for '{primary}' ({primary_limits.context_length})"
                    )
                entry["context_limit"] = context_limit

        normalized[role] = entry

    return normalized


def _rankings_fallback_models_for_batch(batch: str) -> list[str]:
    """Return fallback models for a configured task batch.

    This is a wiring stub for Phase 7A. Runtime callers can set
    STORYCRAFTR_OPENROUTER_BATCH to select a ranked batch.
    """
    if not batch:
        return []
    rankings = _load_openrouter_rankings()
    raw_entry = rankings.get(batch)
    if not isinstance(raw_entry, dict):
        return []
    raw_fallback = raw_entry.get("fallbacks")
    if not isinstance(raw_fallback, list):
        return []
    return [str(item).strip() for item in raw_fallback if str(item).strip()]


def _is_http_429(exc: Exception) -> bool:
    """Return True when an exception is explicitly an HTTP 429 rate limit."""
    status_candidates = [
        getattr(exc, "status_code", None),
        getattr(exc, "http_status", None),
    ]
    response = getattr(exc, "response", None)
    if response is not None:
        status_candidates.append(getattr(response, "status_code", None))

    for candidate in status_candidates:
        if candidate == 429:
            return True

    text = str(exc).lower()
    return "429" in text and "too many" in text


def _extract_http_status_code(exc: Exception) -> int | None:
    """Return an HTTP status code from known provider exception shapes."""

    status_candidates = [
        getattr(exc, "status_code", None),
        getattr(exc, "http_status", None),
    ]
    response = getattr(exc, "response", None)
    if response is not None:
        status_candidates.append(getattr(response, "status_code", None))

    for candidate in status_candidates:
        if isinstance(candidate, int):
            return candidate
        if isinstance(candidate, str) and candidate.isdigit():
            return int(candidate)
    return None


def _is_http_5xx(exc: Exception) -> bool:
    """Return True when an exception indicates a transient upstream 5xx error."""

    status_candidates = [
        getattr(exc, "status_code", None),
        getattr(exc, "http_status", None),
    ]
    response = getattr(exc, "response", None)
    if response is not None:
        status_candidates.append(getattr(response, "status_code", None))

    for candidate in status_candidates:
        if isinstance(candidate, int) and 500 <= candidate <= 599:
            return True

    text = str(exc).lower()
    return any(
        token in text
        for token in (
            "500",
            "502",
            "503",
            "504",
            "bad gateway",
            "gateway timeout",
            "service unavailable",
        )
    )


def _is_empty_chat_result(result: ChatResult) -> bool:
    """Treat blank provider responses as transient transport failures."""

    generations = getattr(result, "generations", None)
    if generations is None:
        return False
    if not generations:
        return True

    for generation in generations:
        message = getattr(generation, "message", None)
        content = getattr(message, "content", "") if message is not None else ""
        if str(content).strip():
            return False
    return True


def _extract_request_id(exc: Exception) -> str | None:
    """Extract provider request ID from common exception shapes."""

    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if isinstance(headers, dict):
        for key in ("x-request-id", "request-id", "x-amzn-requestid"):
            value = headers.get(key) or headers.get(key.upper())
            if value is not None:
                cleaned = str(value).strip()
                if cleaned:
                    return cleaned
    request_id = getattr(exc, "request_id", None)
    if request_id is None:
        return None
    cleaned = str(request_id).strip()
    return cleaned or None


def build_transport_error_payload(
    exc: Exception,
    *,
    provider: str,
    configured_model: str,
    effective_model: str,
) -> dict[str, Any]:
    """Build stable provider failure telemetry for packet diagnostics."""

    status_code = _extract_http_status_code(exc)
    _code, raw_body = _extract_provider_error_details(exc)
    error_kind = _classify_provider_exception(exc)
    retryable = error_kind in {
        "rate_limit",
        "timeout",
        "connection",
        "server_error",
        "empty_response",
    } or (_is_http_5xx(exc) and error_kind != "auth")
    return {
        "http_status": status_code,
        "exception_class": type(exc).__name__,
        "provider": str(provider).strip(),
        "configured_model": str(configured_model).strip(),
        "effective_model": str(effective_model).strip(),
        "raw_error_body": str(raw_body).strip() or "<no-error-body>",
        "request_id": _extract_request_id(exc),
        "retryable": bool(retryable),
        "error_kind": error_kind,
    }


def _ensure_openrouter_model_is_free(model_name: str) -> None:
    if is_model_free(model_name):
        return
    raise LLMConfigurationError(
        "OpenRouter model validation failed for free-only mode. "
        f"Model '{model_name}' is not currently listed as free, unknown, or unavailable. "
        "Use a current free model ID from /model-list or storycraftr model-list."
    )


def _message_content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("input_text")
                if isinstance(text, str) and text.strip():
                    parts.append(text)
            elif item is not None:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)
    if content is None:
        return ""
    return str(content)


def _estimate_prompt_tokens(messages: list[BaseMessage], model_name: str) -> int:
    prompt_text = "\n".join(
        _message_content_to_text(getattr(message, "content", ""))
        for message in messages
    ).strip()
    if not prompt_text:
        return 0

    try:
        encoding = tiktoken.encoding_for_model(model_name)
    except Exception:
        try:
            encoding = tiktoken.get_encoding(_TOKEN_COUNT_FALLBACK_ENCODING)
        except Exception:
            # Offline fallback when tokenizer assets are unavailable locally.
            return max(1, len(prompt_text) // 4)
    return len(encoding.encode(prompt_text, disallowed_special=()))


def _default_context_length_for_provider(provider_name: str) -> int:
    normalized = str(provider_name).strip().lower()
    if normalized == "openai":
        return _OPENAI_DEFAULT_CONTEXT_LENGTH
    if normalized == "ollama":
        return _OLLAMA_DEFAULT_CONTEXT_LENGTH
    return _OLLAMA_DEFAULT_CONTEXT_LENGTH


def _token_budget_payload(
    *,
    provider: str,
    configured_model: str,
    effective_model: str,
    prompt_tokens: int,
    reserved_completion_tokens: int,
    context_length: int,
) -> dict[str, Any]:
    detail = (
        "token_budget_exceeded: "
        f"prompt={prompt_tokens}, "
        f"reserved={reserved_completion_tokens}, "
        f"context={context_length}"
    )
    return {
        "http_status": None,
        "exception_class": "TokenBudgetExceeded",
        "provider": str(provider).strip() or "unknown",
        "configured_model": str(configured_model).strip(),
        "effective_model": str(effective_model).strip(),
        "raw_error_body": detail,
        "request_id": None,
        "retryable": False,
        "error_kind": "token_budget_exceeded",
        "prompt_tokens": prompt_tokens,
        "reserved_completion_tokens": reserved_completion_tokens,
        "context_length": context_length,
    }


class _ResilientOpenRouterChatModel(BaseChatModel):
    """OpenRouter wrapper with bounded retry/backoff and explicit fallbacks."""

    primary_model: Any
    fallback_models: List[Any] = []
    model_sequence: List[str] = []
    max_attempts: int = _OPENROUTER_MAX_ATTEMPTS
    retry_base_seconds: float = _OPENROUTER_RETRY_BASE_SECONDS
    max_backoff_seconds: float = _OPENROUTER_MAX_BACKOFF_SECONDS
    primary_rate_limit_failover_threshold: int = (
        _OPENROUTER_PRIMARY_RATE_LIMIT_FAILOVER_THRESHOLD
    )
    last_resolved_model_index: int = 0
    last_resolved_model: str = ""
    last_transport_error: Dict[str, Any] = {}
    quarantine_events: List[Dict[str, Any]] = []
    _invocation_stage: str = "unknown"

    def __init__(
        self,
        *,
        primary_model: Any,
        fallback_models: List[Any],
        model_sequence: List[str],
        max_attempts: int,
        retry_base_seconds: float,
        max_backoff_seconds: float,
        primary_rate_limit_failover_threshold: int,
    ):
        super().__init__(
            primary_model=primary_model,
            fallback_models=fallback_models,
            model_sequence=model_sequence,
            max_attempts=max_attempts,
            retry_base_seconds=retry_base_seconds,
            max_backoff_seconds=max_backoff_seconds,
            primary_rate_limit_failover_threshold=primary_rate_limit_failover_threshold,
        )

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs,
    ) -> ChatResult:
        health_registry = get_model_health_registry()
        models = [self.primary_model, *self.fallback_models]
        last_exc: Exception | None = None
        self.last_transport_error = {}
        self.quarantine_events = []

        for model_index, model in enumerate(models):
            model_name = (
                self.model_sequence[model_index]
                if model_index < len(self.model_sequence)
                else f"openrouter-model-{model_index + 1}"
            )

            if health_registry.is_quarantined(model_name):
                _OPENROUTER_LOGGER.info(
                    "openrouter_model_skipped_quarantined",
                    model=model_name,
                    stage=self._invocation_stage,
                )
                self.quarantine_events.append(
                    {
                        "timestamp": time.time(),
                        "stage": self._invocation_stage,
                        "model": model_name,
                        "decision": "skip_quarantined",
                        "quarantined_until": health_registry._entry(  # noqa: SLF001
                            model_name
                        ).quarantined_until,
                    }
                )
                continue

            if health_registry.is_degraded(model_name):
                _OPENROUTER_LOGGER.info(
                    "openrouter_model_skipped_degraded",
                    model=model_name,
                    stage=self._invocation_stage,
                )
                continue

            model_limits = get_model_limits(model_name)
            context_length = model_limits.context_length if model_limits else 8192
            reserved_completion_tokens = _OPENROUTER_DEFAULT_MAX_TOKENS
            if model_limits and model_limits.max_completion_tokens is not None:
                reserved_completion_tokens = min(
                    reserved_completion_tokens,
                    model_limits.max_completion_tokens,
                )
            prompt_tokens = _estimate_prompt_tokens(messages, model_name)
            if prompt_tokens + reserved_completion_tokens > context_length:
                payload = _token_budget_payload(
                    provider="openrouter",
                    configured_model=(
                        self.model_sequence[0] if self.model_sequence else model_name
                    ),
                    effective_model=model_name,
                    prompt_tokens=prompt_tokens,
                    reserved_completion_tokens=reserved_completion_tokens,
                    context_length=context_length,
                )
                self.last_transport_error = payload
                last_exc = RuntimeError(payload["raw_error_body"])
                _OPENROUTER_LOGGER.warning(
                    "openrouter_token_budget_exceeded",
                    model=model_name,
                    stage=self._invocation_stage,
                    prompt_tokens=prompt_tokens,
                    reserved_completion_tokens=reserved_completion_tokens,
                    context_length=context_length,
                )
                continue

            breaker = _openrouter_circuit_breaker(model_name)
            primary_rate_limit_hits = 0

            def _invoke_once() -> ChatResult:
                nonlocal primary_rate_limit_hits
                started = time.monotonic()
                try:
                    result = breaker.call(
                        model._generate,  # noqa: SLF001
                        messages,
                        stop=stop,
                        run_manager=run_manager,
                        **kwargs,
                    )
                    if _is_empty_chat_result(result):
                        health_registry.record_empty_response(model_name)
                        raise RuntimeError("empty response from provider")
                    health_registry.record_success(
                        model_name,
                        latency_seconds=time.monotonic() - started,
                    )
                    return result
                except pybreaker.CircuitBreakerError:
                    raise
                except Exception as exc:
                    health_registry.record_error(model_name)
                    health_registry.record_http_failure(
                        model_name,
                        status_code=_extract_http_status_code(exc),
                    )
                    self.last_transport_error = build_transport_error_payload(
                        exc,
                        provider="openrouter",
                        configured_model=(
                            self.model_sequence[0]
                            if self.model_sequence
                            else model_name
                        ),
                        effective_model=model_name,
                    )
                    error_kind = (
                        "rate_limit"
                        if _is_http_429(exc)
                        else _classify_provider_exception(exc)
                    )
                    if error_kind == "auth":
                        raise

                    if error_kind == "rate_limit" and model_index == 0:
                        primary_rate_limit_hits += 1
                        if primary_rate_limit_hits >= max(
                            1, self.primary_rate_limit_failover_threshold
                        ):
                            raise _PrimaryRateLimitFailover(
                                "primary rate-limit failover"
                            ) from exc

                    signature = ""
                    if error_kind == "rate_limit":
                        signature = "http_429"
                    elif _extract_http_status_code(exc) == 503:
                        signature = "http_503"
                    elif error_kind == "timeout":
                        signature = "timeout"
                    elif error_kind == "empty_response":
                        signature = "empty_response"

                    if signature:
                        quarantined = health_registry.record_stage_transient_failure(
                            model_name,
                            stage_name=self._invocation_stage,
                            failure_signature=signature,
                        )
                        if quarantined:
                            _OPENROUTER_LOGGER.warning(
                                "openrouter_model_quarantined",
                                model=model_name,
                                stage=self._invocation_stage,
                                reason=signature,
                            )
                            self.quarantine_events.append(
                                {
                                    "timestamp": time.time(),
                                    "stage": self._invocation_stage,
                                    "model": model_name,
                                    "decision": "quarantined",
                                    "reason": signature,
                                    "quarantined_until": health_registry._entry(  # noqa: SLF001
                                        model_name
                                    ).quarantined_until,
                                }
                            )
                            raise _QuarantinedModelFailover(
                                "model quarantined after repeated transient failures"
                            ) from exc
                    raise

            def _log_retry_before_sleep(retry_state: Any) -> None:
                exc = None
                outcome = getattr(retry_state, "outcome", None)
                if outcome is not None and hasattr(outcome, "exception"):
                    exc = outcome.exception()
                _OPENROUTER_LOGGER.warning(
                    "openrouter_retry",
                    model=model_name,
                    stage=self._invocation_stage,
                    attempt=getattr(retry_state, "attempt_number", 0),
                    error_kind=(
                        _classify_provider_exception(exc)
                        if isinstance(exc, Exception)
                        else "unknown"
                    ),
                    error=str(exc) if exc is not None else "",
                )

            retryer = Retrying(
                stop=stop_after_attempt(max(1, self.max_attempts)),
                wait=wait_exponential(
                    multiplier=max(0.1, self.retry_base_seconds),
                    min=max(0.1, self.retry_base_seconds),
                    max=max(0.1, self.max_backoff_seconds),
                ),
                retry=retry_if_exception(_should_retry_openrouter_exception),
                before_sleep=_log_retry_before_sleep,
                sleep=time.sleep,
                reraise=True,
            )

            try:
                result = retryer(_invoke_once)
                if model_index > 0:
                    _OPENROUTER_LOGGER.info(
                        "openrouter_resolved_model",
                        model=model_name,
                        stage=self._invocation_stage,
                    )
                self.last_resolved_model_index = model_index
                self.last_resolved_model = model_name
                return result
            except pybreaker.CircuitBreakerError as exc:
                last_exc = exc
                _OPENROUTER_LOGGER.warning(
                    "openrouter_breaker_open",
                    model=model_name,
                    stage=self._invocation_stage,
                )
                self.quarantine_events.append(
                    {
                        "timestamp": time.time(),
                        "stage": self._invocation_stage,
                        "model": model_name,
                        "decision": "breaker_open",
                    }
                )
                continue
            except _PrimaryRateLimitFailover as exc:
                cause = exc.__cause__
                last_exc = cause if isinstance(cause, Exception) else exc
                _OPENROUTER_LOGGER.warning(
                    "openrouter_rate_limit_failover",
                    model=model_name,
                    stage=self._invocation_stage,
                )
                continue
            except _QuarantinedModelFailover as exc:
                cause = exc.__cause__
                last_exc = cause if isinstance(cause, Exception) else exc
                continue
            except Exception as exc:
                last_exc = exc
                if _classify_provider_exception(exc) == "auth":
                    raise
                continue

        if last_exc is not None:
            payload = dict(self.last_transport_error)
            if payload.get("raw_error_body"):
                message = f"OpenRouter invocation failed: {payload['raw_error_body']}"
            else:
                message = f"OpenRouter invocation failed: {last_exc}"
            raise LLMInvocationError(
                message,
                transport_error=payload,
                quarantine_events=self.quarantine_events,
            ) from last_exc
        raise RuntimeError("OpenRouter request failed without an explicit exception.")

    @property
    def _llm_type(self) -> str:
        return "openrouter-resilient"

    def set_invocation_stage(self, stage_name: str) -> None:
        """Set caller stage for stage/model circuit-breaker accounting."""

        self._invocation_stage = str(stage_name or "unknown").strip() or "unknown"


class _ResilientSingleProviderChatModel(BaseChatModel):
    """Retry + circuit-breaker wrapper for single-provider chat backends."""

    provider_name: str
    model_name: str
    wrapped_model: Any
    context_length: int = _OLLAMA_DEFAULT_CONTEXT_LENGTH
    reserved_completion_tokens: int = _OPENROUTER_DEFAULT_MAX_TOKENS
    max_attempts: int = _PROVIDER_MAX_ATTEMPTS
    retry_base_seconds: float = _PROVIDER_RETRY_BASE_SECONDS
    max_backoff_seconds: float = _PROVIDER_MAX_BACKOFF_SECONDS
    last_resolved_model_index: int = 0
    last_resolved_model: str = ""
    last_transport_error: Dict[str, Any] = {}
    quarantine_events: List[Dict[str, Any]] = []
    _invocation_stage: str = "unknown"

    def __init__(
        self,
        *,
        provider_name: str,
        model_name: str,
        wrapped_model: Any,
        context_length: int,
        reserved_completion_tokens: int,
        max_attempts: int = _PROVIDER_MAX_ATTEMPTS,
        retry_base_seconds: float = _PROVIDER_RETRY_BASE_SECONDS,
        max_backoff_seconds: float = _PROVIDER_MAX_BACKOFF_SECONDS,
    ):
        super().__init__(
            provider_name=provider_name,
            model_name=model_name,
            wrapped_model=wrapped_model,
            context_length=max(1, int(context_length)),
            reserved_completion_tokens=max(1, int(reserved_completion_tokens)),
            max_attempts=max_attempts,
            retry_base_seconds=retry_base_seconds,
            max_backoff_seconds=max_backoff_seconds,
        )

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs,
    ) -> ChatResult:
        self.last_transport_error = {}
        self.quarantine_events = []
        breaker = _provider_circuit_breaker(self.provider_name, self.model_name)
        prompt_tokens = _estimate_prompt_tokens(messages, self.model_name)
        if prompt_tokens + self.reserved_completion_tokens > self.context_length:
            payload = _token_budget_payload(
                provider=self.provider_name,
                configured_model=self.model_name,
                effective_model=self.model_name,
                prompt_tokens=prompt_tokens,
                reserved_completion_tokens=self.reserved_completion_tokens,
                context_length=self.context_length,
            )
            self.last_transport_error = payload
            _OPENROUTER_LOGGER.warning(
                "provider_token_budget_exceeded",
                provider=self.provider_name,
                model=self.model_name,
                stage=self._invocation_stage,
                prompt_tokens=prompt_tokens,
                reserved_completion_tokens=self.reserved_completion_tokens,
                context_length=self.context_length,
            )
            raise LLMInvocationError(
                f"{self.provider_name} invocation failed: {payload['raw_error_body']}",
                transport_error=payload,
                quarantine_events=self.quarantine_events,
            )

        def _invoke_once() -> ChatResult:
            try:
                result = breaker.call(
                    self.wrapped_model._generate,  # noqa: SLF001
                    messages,
                    stop=stop,
                    run_manager=run_manager,
                    **kwargs,
                )
            except pybreaker.CircuitBreakerError:
                raise
            except Exception as exc:
                self.last_transport_error = build_transport_error_payload(
                    exc,
                    provider=self.provider_name,
                    configured_model=self.model_name,
                    effective_model=self.model_name,
                )
                raise
            if _is_empty_chat_result(result):
                empty_exc = RuntimeError("empty response from provider")
                self.last_transport_error = build_transport_error_payload(
                    empty_exc,
                    provider=self.provider_name,
                    configured_model=self.model_name,
                    effective_model=self.model_name,
                )
                raise empty_exc
            return result

        def _log_retry_before_sleep(retry_state: Any) -> None:
            exc = None
            outcome = getattr(retry_state, "outcome", None)
            if outcome is not None and hasattr(outcome, "exception"):
                exc = outcome.exception()
            _OPENROUTER_LOGGER.warning(
                "provider_retry",
                provider=self.provider_name,
                model=self.model_name,
                stage=self._invocation_stage,
                attempt=getattr(retry_state, "attempt_number", 0),
                error_kind=(
                    _classify_provider_exception(exc)
                    if isinstance(exc, Exception)
                    else "unknown"
                ),
                error=str(exc) if exc is not None else "",
            )

        retryer = Retrying(
            stop=stop_after_attempt(max(1, self.max_attempts)),
            wait=wait_exponential(
                multiplier=max(0.1, self.retry_base_seconds),
                min=max(0.1, self.retry_base_seconds),
                max=max(0.1, self.max_backoff_seconds),
            ),
            retry=retry_if_exception(_should_retry_provider_exception),
            before_sleep=_log_retry_before_sleep,
            sleep=time.sleep,
            reraise=True,
        )

        try:
            result = retryer(_invoke_once)
            self.last_resolved_model = self.model_name
            self.last_resolved_model_index = 0
            return result
        except pybreaker.CircuitBreakerError as exc:
            self.quarantine_events = [
                {
                    "timestamp": time.time(),
                    "stage": self._invocation_stage,
                    "model": self.model_name,
                    "decision": "breaker_open",
                }
            ]
            raise LLMInvocationError(
                f"{self.provider_name} invocation blocked by circuit breaker",
                transport_error=self.last_transport_error,
                quarantine_events=self.quarantine_events,
            ) from exc
        except Exception as exc:
            if _classify_provider_exception(exc) == "auth":
                raise
            payload = (
                dict(self.last_transport_error)
                if self.last_transport_error
                else build_transport_error_payload(
                    exc,
                    provider=self.provider_name,
                    configured_model=self.model_name,
                    effective_model=self.model_name,
                )
            )
            detail = str(payload.get("raw_error_body", "")).strip() or str(exc)
            raise LLMInvocationError(
                f"{self.provider_name} invocation failed: {detail}",
                transport_error=payload,
                quarantine_events=self.quarantine_events,
            ) from exc

    @property
    def _llm_type(self) -> str:
        return f"{self.provider_name}-resilient"

    def set_invocation_stage(self, stage_name: str) -> None:
        self._invocation_stage = str(stage_name or "unknown").strip() or "unknown"


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
    _validate_max_tokens(settings.max_tokens)

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
        if provider == "openrouter":
            params["max_tokens"] = _OPENROUTER_DEFAULT_MAX_TOKENS
        elif settings.max_tokens is not None:
            params["max_tokens"] = settings.max_tokens
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

        if provider == "openrouter":
            _ensure_openrouter_model_is_free(model_name)

        try:
            primary_model = ChatOpenAI(api_key=api_key, **params)
        except Exception as exc:
            _raise_provider_error(
                provider=provider,
                model_name=model_name,
                endpoint=endpoint_text,
                env_var=api_key_env,
                exc=exc,
            )

        if provider != "openrouter":
            reserved_completion_tokens = (
                int(settings.max_tokens)
                if isinstance(settings.max_tokens, int) and settings.max_tokens > 0
                else _OPENROUTER_DEFAULT_MAX_TOKENS
            )
            return _ResilientSingleProviderChatModel(
                provider_name=provider,
                model_name=model_name,
                wrapped_model=primary_model,
                context_length=_default_context_length_for_provider(provider),
                reserved_completion_tokens=reserved_completion_tokens,
            )

        fallback_models: list[Any] = []
        model_sequence = [model_name]
        for fallback_model_name in _openrouter_fallback_chain(model_name):
            try:
                _ensure_openrouter_model_is_free(fallback_model_name)
            except LLMConfigurationError as exc:
                _OPENROUTER_LOGGER.warning(
                    "openrouter_fallback_skipped_not_free",
                    fallback_model=fallback_model_name,
                    error=str(exc),
                )
                continue
            fallback_params = dict(params)
            fallback_params["model"] = fallback_model_name
            try:
                fallback_model = ChatOpenAI(api_key=api_key, **fallback_params)
            except Exception as exc:
                error_kind = _classify_provider_exception(exc)
                redacted = _sanitize_error_text(str(exc), [api_key])
                _OPENROUTER_LOGGER.warning(
                    "openrouter_fallback_init_failed",
                    fallback_model=fallback_model_name,
                    error_kind=error_kind,
                    exception_class=type(exc).__name__,
                    error=redacted,
                )
                continue
            fallback_models.append(fallback_model)
            model_sequence.append(fallback_model_name)

        return _ResilientOpenRouterChatModel(
            primary_model=primary_model,
            fallback_models=fallback_models,
            model_sequence=model_sequence,
            max_attempts=_OPENROUTER_MAX_ATTEMPTS,
            retry_base_seconds=_OPENROUTER_RETRY_BASE_SECONDS,
            max_backoff_seconds=_OPENROUTER_MAX_BACKOFF_SECONDS,
            primary_rate_limit_failover_threshold=(
                _OPENROUTER_PRIMARY_RATE_LIMIT_FAILOVER_THRESHOLD
            ),
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
            ollama_model = ChatOllama(**params)
        except Exception as exc:
            _raise_provider_error(
                provider=provider,
                model_name=model_name,
                endpoint=endpoint_text,
                env_var=None,
                exc=exc,
            )
        return _ResilientSingleProviderChatModel(
            provider_name=provider,
            model_name=model_name,
            wrapped_model=ollama_model,
            context_length=_default_context_length_for_provider(provider),
            reserved_completion_tokens=(
                int(settings.max_tokens)
                if isinstance(settings.max_tokens, int) and settings.max_tokens > 0
                else _OPENROUTER_DEFAULT_MAX_TOKENS
            ),
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
