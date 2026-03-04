import json
from types import SimpleNamespace

from storycraftr.utils.core import load_book_config, llm_settings_from_config


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


def test_llm_settings_from_config_openai_missing_model_uses_openai_default():
    config = SimpleNamespace(llm_provider="openai")

    settings = llm_settings_from_config(config)

    assert settings.model == "gpt-4o"


def test_llm_settings_from_config_openrouter_missing_model_stays_empty():
    config = SimpleNamespace(llm_provider="openrouter")

    settings = llm_settings_from_config(config)

    assert settings.model == ""
