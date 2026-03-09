import json
from contextlib import contextmanager

from storycraftr.utils.core import (
    BookConfig,
    generate_prompt_with_hash,
    load_book_config,
    llm_settings_from_config,
)


def test_load_book_config_openrouter_missing_model_does_not_fallback(tmp_path):
    config_data = {
        "book_name": "Test",
        "llm_provider": "openrouter",
    }
    (tmp_path / "storycraftr.json").write_text(
        json.dumps(config_data), encoding="utf-8"
    )

    config = load_book_config(str(tmp_path))

    assert config is not None
    assert config.llm_provider == "openrouter"
    assert config.llm_model == ""


def test_llm_settings_from_config_openai_missing_model_uses_openai_default(tmp_path):
    config = BookConfig.from_mapping(
        book_path=str(tmp_path / "test_book"),
        config_data={"llm_provider": "openai"},
    )

    settings = llm_settings_from_config(config)

    assert settings.model == "gpt-4o"
    assert settings.max_tokens == 8192


def test_llm_settings_from_config_openrouter_missing_model_stays_empty(tmp_path):
    config = BookConfig.from_mapping(
        book_path=str(tmp_path / "test_book"),
        config_data={"llm_provider": "openrouter"},
    )

    settings = llm_settings_from_config(config)

    assert settings.model == ""
    assert settings.max_tokens == 8192


def test_load_book_config_defaults_max_tokens(tmp_path):
    config_data = {
        "book_name": "Test",
        "llm_provider": "openai",
    }
    (tmp_path / "storycraftr.json").write_text(
        json.dumps(config_data), encoding="utf-8"
    )

    config = load_book_config(str(tmp_path))

    assert config is not None
    assert config.max_tokens == 8192


def test_load_book_config_respects_configured_max_tokens(tmp_path):
    config_data = {
        "book_name": "Test",
        "llm_provider": "openai",
        "max_tokens": 4096,
    }
    (tmp_path / "storycraftr.json").write_text(
        json.dumps(config_data), encoding="utf-8"
    )

    config = load_book_config(str(tmp_path))

    assert config is not None
    assert config.max_tokens == 4096


def test_load_book_config_returns_typed_book_config(tmp_path):
    config_data = {
        "book_name": "Typed",
        "llm_provider": "OpenAI",
        "multiple_answer": "false",
        "request_timeout": "90",
        "max_tokens": "2048",
    }
    (tmp_path / "storycraftr.json").write_text(
        json.dumps(config_data), encoding="utf-8"
    )

    config = load_book_config(str(tmp_path))

    assert isinstance(config, BookConfig)
    assert config is not None
    assert config.llm_provider == "openai"
    assert config.multiple_answer is False
    assert config.request_timeout == 90
    assert config.max_tokens == 2048


def test_load_book_config_coerces_enable_semantic_review(tmp_path):
    config_data = {
        "book_name": "Semantic",
        "llm_provider": "openrouter",
        "enable_semantic_review": "true",
    }
    (tmp_path / "storycraftr.json").write_text(
        json.dumps(config_data), encoding="utf-8"
    )

    config = load_book_config(str(tmp_path))

    assert config is not None
    assert config.enable_semantic_review is True


def test_generate_prompt_with_hash_uses_project_write_lock(monkeypatch, tmp_path):
    calls: list[str] = []

    @contextmanager
    def fake_lock(book_path: str, *, config=None, **_kwargs):
        calls.append(book_path)
        yield tmp_path / ".storycraftr" / "project.lock"

    monkeypatch.setattr("storycraftr.utils.core.project_write_lock", fake_lock)
    monkeypatch.setattr("storycraftr.utils.core.longer_date_formats", ["Date: {date}"])

    result = generate_prompt_with_hash("hello", "March 06, 2026", str(tmp_path))

    assert result.startswith("Date: March 06, 2026")
    assert calls == [str(tmp_path)]
