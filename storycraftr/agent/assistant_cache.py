from __future__ import annotations

import threading
from typing import TypeVar

T = TypeVar("T")

# Shared assistant cache keyed by project path + model override.
_ASSISTANT_CACHE: dict[str, object] = {}
_ASSISTANT_CACHE_LOCK = threading.RLock()


def assistant_cache_key(book_path: str, model_override: str | None = None) -> str:
    override_key = "<default>"
    if model_override is not None:
        override_key = model_override.strip()
    return f"{book_path}:{override_key}"


def get_cached_assistant(cache_key: str) -> T | None:
    with _ASSISTANT_CACHE_LOCK:
        cached = _ASSISTANT_CACHE.get(cache_key)
        return cached if cached is not None else None


def get_cached_assistant_by_params(
    book_path: str,
    model_override: str | None = None,
) -> T | None:
    return get_cached_assistant(assistant_cache_key(book_path, model_override))


def store_assistant_if_absent(cache_key: str, assistant: T) -> T:
    with _ASSISTANT_CACHE_LOCK:
        existing = _ASSISTANT_CACHE.get(cache_key)
        if existing is not None:
            return existing  # type: ignore[return-value]
        _ASSISTANT_CACHE[cache_key] = assistant
        return assistant


def clear_assistant_cache() -> None:
    with _ASSISTANT_CACHE_LOCK:
        _ASSISTANT_CACHE.clear()
