from __future__ import annotations

import langchain_openai
import pytest

from storycraftr.llm.embeddings import EmbeddingSettings, build_embedding_model
from storycraftr.llm.factory import LLMConfigurationError


class _DummyEmbeddings:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


def test_build_api_embeddings_openrouter(monkeypatch):
    fake_key = "test-key"  # pragma: allowlist secret
    monkeypatch.setenv("OPENROUTER_API_KEY", fake_key)
    monkeypatch.setattr(langchain_openai, "OpenAIEmbeddings", _DummyEmbeddings)

    result = build_embedding_model(
        EmbeddingSettings(
            model_name="text-embedding-3-small",
            device="api",
            api_provider="openrouter",
        )
    )

    assert isinstance(result, _DummyEmbeddings)
    assert result.kwargs["model"] == "text-embedding-3-small"
    assert result.kwargs["openai_api_key"] == fake_key
    assert result.kwargs["openai_api_base"] == "https://openrouter.ai/api/v1"


def test_build_api_embeddings_requires_api_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    with pytest.raises(LLMConfigurationError, match="OPENROUTER_API_KEY"):
        build_embedding_model(
            EmbeddingSettings(
                model_name="text-embedding-3-small",
                device="api",
                api_provider="openrouter",
            )
        )


def test_build_local_embeddings_install_hint_mentions_core_install(monkeypatch):
    from storycraftr.llm import embeddings as embeddings_module

    def _fake_import(name):
        if name == "transformers.logging":
            raise ImportError("optional")
        if name == "torch":
            raise ImportError("missing torch")
        raise AssertionError(f"unexpected import: {name}")

    monkeypatch.setattr(embeddings_module, "import_module", _fake_import)

    with pytest.raises(LLMConfigurationError, match="uv pip install -e ."):
        build_embedding_model(
            EmbeddingSettings(
                model_name="BAAI/bge-large-en-v1.5",
                device="cpu",
            )
        )
