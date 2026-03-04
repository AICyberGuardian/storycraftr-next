from __future__ import annotations

import os
from dataclasses import dataclass
from importlib import import_module
from typing import Optional


@dataclass
class EmbeddingSettings:
    """Normalized configuration to construct embedding models."""

    model_name: str = "BAAI/bge-large-en-v1.5"
    device: str = "auto"
    cache_dir: Optional[str] = None
    normalize: Optional[bool] = None


def _should_normalize(model_name: str, explicit: Optional[bool]) -> bool:
    if explicit is not None:
        return explicit
    return "bge" in model_name.lower()


def _raise_configuration_error(message: str, exc: Exception | None = None) -> None:
    from storycraftr.llm.factory import LLMConfigurationError

    if exc is None:
        raise LLMConfigurationError(message)
    raise LLMConfigurationError(message) from exc


def _resolve_device(configured_device: Optional[str], torch_module) -> str:
    normalized = (configured_device or "").strip().lower()
    if normalized not in {"", "auto"}:
        return normalized
    if torch_module.cuda.is_available():
        return "cuda"
    if (
        hasattr(torch_module.backends, "mps")
        and torch_module.backends.mps.is_available()
    ):
        return "mps"
    return "cpu"


def build_embedding_model(settings: EmbeddingSettings):
    """
    Build a HuggingFace embedding model with sane defaults for local usage.
    """

    model_name_lower = settings.model_name.lower()
    if model_name_lower in {"fake", "offline", "offline-placeholder"}:
        _raise_configuration_error(
            "Embedding provider is set to a placeholder model. Configure a valid embedding model."
        )

    install_hint = (
        "Missing ML stack for local embeddings. "
        "Run 'poetry install --with embeddings' or "
        "'uv pip install torch sentence-transformers'."
    )
    import logging

    os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
    logging.getLogger("transformers").setLevel(logging.ERROR)
    logging.getLogger("sentence_transformers").setLevel(logging.ERROR)

    try:
        torch = import_module("torch")
    except ImportError as exc:
        _raise_configuration_error(install_hint, exc)

    try:
        huggingface_module = import_module("langchain_huggingface")
        HuggingFaceEmbeddings = huggingface_module.HuggingFaceEmbeddings
    except (ImportError, AttributeError) as exc:
        _raise_configuration_error(install_hint, exc)

    model_kwargs = {}
    model_kwargs["device"] = _resolve_device(settings.device, torch)
    cache_dir = settings.cache_dir or os.getenv("STORYCRAFTR_EMBED_CACHE")
    if cache_dir:
        model_kwargs["cache_dir"] = cache_dir

    encode_kwargs = {}
    if _should_normalize(settings.model_name, settings.normalize):
        encode_kwargs["normalize_embeddings"] = True

    try:
        return HuggingFaceEmbeddings(
            model_name=settings.model_name,
            model_kwargs=model_kwargs,
            encode_kwargs=encode_kwargs,
        )
    except ImportError as exc:
        _raise_configuration_error(install_hint, exc)
    except Exception as exc:
        _raise_configuration_error(
            f"Failed to load embedding model '{settings.model_name}'. "
            "Verify model identifier, local ML dependencies, and hardware runtime.",
            exc,
        )
