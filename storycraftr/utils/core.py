from __future__ import annotations

import json
import os
import secrets  # Para generar números aleatorios seguros
from pathlib import Path
from typing import Any

import yaml
from rich.console import Console
from rich.markdown import Markdown  # Importar soporte de Markdown de Rich

from storycraftr.llm.embeddings import EmbeddingSettings
from storycraftr.llm.factory import LLMSettings
from storycraftr.prompts.permute import longer_date_formats
from storycraftr.state import debug_state  # Importar el estado de debug
from types import SimpleNamespace

from storycraftr.utils.project_lock import project_write_lock

console = Console()


def _default_model_for_provider(provider: str) -> str:
    normalized = (provider or "").strip().lower()
    return "gpt-4o" if normalized == "openai" else ""


def generate_prompt_with_hash(original_prompt: str, date: str, book_path: str) -> str:
    """
    Generates a modified prompt by combining a random phrase from a list,
    a date, and the original prompt. Logs the prompt details in a YAML file.

    Args:
        original_prompt (str): The original prompt to be modified.
        date (str): The current date to be used in the prompt.
        book_path (str): Path to the book's directory where prompts.yaml will be saved.

    Returns:
        str: The modified prompt with the date and random phrase.
    """
    # Selecciona una frase aleatoria segura de la lista
    random_phrase = secrets.choice(longer_date_formats).format(date=date)
    modified_prompt = f"{random_phrase}\n\n{original_prompt}"

    # Define la ruta del archivo YAML
    yaml_path = Path(book_path) / "prompts.yaml"

    # Nueva entrada de log con fecha y prompt original
    log_entry = {"date": str(date), "original_prompt": original_prompt}

    with project_write_lock(book_path):
        # Verifica si el archivo YAML existe y carga los datos
        if yaml_path.exists():
            with yaml_path.open("r", encoding="utf-8") as file:
                existing_data = (
                    yaml.safe_load(file) or []
                )  # Carga una lista vacía si está vacío
        else:
            existing_data = []

        # Añade la nueva entrada al log
        existing_data.append(log_entry)

        # Guarda los datos actualizados en el archivo YAML
        with yaml_path.open("w", encoding="utf-8") as file:
            yaml.dump(existing_data, file, default_flow_style=False)

    # Imprime el prompt modificado en Markdown si el modo debug está activado
    if debug_state.is_debug():
        console.print(Markdown(modified_prompt))

    return modified_prompt


def _coerce_str(value: Any, fallback: str) -> str:
    if value is None:
        return fallback
    return str(value)


def _coerce_bool(value: Any, fallback: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return fallback


def _coerce_float(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _coerce_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _coerce_str_list(value: Any, fallback: list[str] | None = None) -> list[str]:
    if value is None:
        return list(fallback or [])
    if isinstance(value, list):
        return [str(item) for item in value]
    return list(fallback or [])


class BookConfig(SimpleNamespace):
    """
    Typed view over the project's persisted configuration.

    Attributes:
        book_path (str): The path to the book's directory.
        book_name (str): The name of the book.
        primary_language (str): The primary language of the project.
        alternate_languages (list): A list of alternate languages.
        default_author (str): The default author of the book or paper.
        genre (str): The genre of the book (StoryCraftr only).
        license (str): The license type for the book.
        reference_author (str): A reference author for style guidance.
        keywords (str): Keywords for the paper (optional).
        cli_name (str): The CLI tool name (`storycraftr` or `papercraftr`).
        multiple_answer (bool): Whether multi-part responses are enabled.
        llm_provider (str): Selected LLM provider (openai, openrouter, ollama).
        llm_model (str): Target model identifier for the provider.
        llm_endpoint (str): Optional custom endpoint/base URL.
        llm_api_key_env (str): Optional environment variable override for API key lookup.
        temperature (float): Sampling temperature for completions.
        request_timeout (int): Timeout in seconds for LLM calls.
        max_tokens (int): Maximum output tokens per generation.
        embed_model (str): Embedding model identifier.
        embed_device (str): Embedding runtime mode (`api`, `auto`, `cpu`, `cuda`, ...).
        embed_cache_dir (str): Local cache directory for embeddings.
        enable_semantic_review (bool): Enables optional semantic reviewer pass in
            `storycraftr book` before state extraction/commit.
    """

    book_path: str
    book_name: str
    primary_language: str
    alternate_languages: list[str]
    authors: list[str]
    default_author: str
    genre: str
    license: str
    reference_author: str
    keywords: str
    cli_name: str
    multiple_answer: bool
    llm_provider: str
    llm_model: str
    llm_endpoint: str
    llm_api_key_env: str
    temperature: float
    request_timeout: int
    max_tokens: int
    embed_model: str
    embed_device: str
    embed_cache_dir: str
    enable_semantic_review: bool
    internal_state_dir: str
    subagents_dir: str
    subagent_logs_dir: str
    sessions_dir: str
    vector_store_dir: str
    vscode_events_file: str

    DEFAULTS: dict[str, Any] = {
        "book_name": "Untitled Paper",
        "authors": [],
        "primary_language": "en",
        "alternate_languages": [],
        "default_author": "Unknown Author",
        "genre": "research",
        "license": "CC BY",
        "reference_author": "",
        "keywords": "",
        "cli_name": "papercraftr",
        "multiple_answer": True,
        "llm_provider": "openai",
        "llm_model": "",
        "llm_endpoint": "",
        "llm_api_key_env": "",
        "temperature": 0.7,
        "request_timeout": 120,
        "max_tokens": 8192,
        "embed_model": "text-embedding-3-small",
        "embed_device": "api",
        "embed_cache_dir": "",
        "enable_semantic_review": False,
        "internal_state_dir": "",
        "subagents_dir": "",
        "subagent_logs_dir": "",
        "sessions_dir": "",
        "vector_store_dir": "",
        "vscode_events_file": "",
    }

    @classmethod
    def from_mapping(
        cls,
        *,
        book_path: str,
        config_data: dict[str, Any],
        model_override: str | None = None,
    ) -> "BookConfig":
        normalized: dict[str, Any] = dict(cls.DEFAULTS)
        normalized.update(config_data)
        normalized["book_path"] = book_path

        provider = _coerce_str(normalized.get("llm_provider"), "openai").strip().lower()
        normalized["llm_provider"] = provider

        if "llm_model" not in config_data:
            normalized["llm_model"] = _default_model_for_provider(provider)

        if model_override is not None:
            normalized["llm_model"] = str(model_override).strip()

        normalized["book_name"] = _coerce_str(
            normalized.get("book_name"), cls.DEFAULTS["book_name"]
        )
        normalized["primary_language"] = _coerce_str(
            normalized.get("primary_language"), cls.DEFAULTS["primary_language"]
        )
        normalized["alternate_languages"] = _coerce_str_list(
            normalized.get("alternate_languages"), cls.DEFAULTS["alternate_languages"]
        )
        normalized["authors"] = _coerce_str_list(
            normalized.get("authors"), cls.DEFAULTS["authors"]
        )
        normalized["default_author"] = _coerce_str(
            normalized.get("default_author"), cls.DEFAULTS["default_author"]
        )
        normalized["genre"] = _coerce_str(
            normalized.get("genre"), cls.DEFAULTS["genre"]
        )
        normalized["license"] = _coerce_str(
            normalized.get("license"), cls.DEFAULTS["license"]
        )
        normalized["reference_author"] = _coerce_str(
            normalized.get("reference_author"), cls.DEFAULTS["reference_author"]
        )
        normalized["keywords"] = _coerce_str(
            normalized.get("keywords"), cls.DEFAULTS["keywords"]
        )
        normalized["cli_name"] = _coerce_str(
            normalized.get("cli_name"), cls.DEFAULTS["cli_name"]
        )
        normalized["multiple_answer"] = _coerce_bool(
            normalized.get("multiple_answer"), cls.DEFAULTS["multiple_answer"]
        )
        normalized["llm_model"] = _coerce_str(
            normalized.get("llm_model"), cls.DEFAULTS["llm_model"]
        ).strip()
        normalized["llm_endpoint"] = _coerce_str(
            normalized.get("llm_endpoint"), cls.DEFAULTS["llm_endpoint"]
        )
        normalized["llm_api_key_env"] = _coerce_str(
            normalized.get("llm_api_key_env"), cls.DEFAULTS["llm_api_key_env"]
        )
        normalized["temperature"] = _coerce_float(
            normalized.get("temperature"), cls.DEFAULTS["temperature"]
        )
        normalized["request_timeout"] = max(
            1,
            _coerce_int(
                normalized.get("request_timeout"), cls.DEFAULTS["request_timeout"]
            ),
        )
        normalized["max_tokens"] = max(
            1,
            _coerce_int(normalized.get("max_tokens"), cls.DEFAULTS["max_tokens"]),
        )
        normalized["embed_model"] = _coerce_str(
            normalized.get("embed_model"), cls.DEFAULTS["embed_model"]
        )
        normalized["embed_device"] = _coerce_str(
            normalized.get("embed_device"), cls.DEFAULTS["embed_device"]
        )
        normalized["embed_cache_dir"] = _coerce_str(
            normalized.get("embed_cache_dir"), cls.DEFAULTS["embed_cache_dir"]
        )
        normalized["enable_semantic_review"] = _coerce_bool(
            normalized.get("enable_semantic_review"),
            cls.DEFAULTS["enable_semantic_review"],
        )
        normalized["internal_state_dir"] = _coerce_str(
            normalized.get("internal_state_dir"), cls.DEFAULTS["internal_state_dir"]
        )
        normalized["subagents_dir"] = _coerce_str(
            normalized.get("subagents_dir"), cls.DEFAULTS["subagents_dir"]
        )
        normalized["subagent_logs_dir"] = _coerce_str(
            normalized.get("subagent_logs_dir"), cls.DEFAULTS["subagent_logs_dir"]
        )
        normalized["sessions_dir"] = _coerce_str(
            normalized.get("sessions_dir"), cls.DEFAULTS["sessions_dir"]
        )
        normalized["vector_store_dir"] = _coerce_str(
            normalized.get("vector_store_dir"), cls.DEFAULTS["vector_store_dir"]
        )
        normalized["vscode_events_file"] = _coerce_str(
            normalized.get("vscode_events_file"), cls.DEFAULTS["vscode_events_file"]
        )

        return cls(**normalized)


def load_book_config(
    book_path: str, model_override: str | None = None
) -> BookConfig | None:
    """
    Load configuration from the book path.
    """
    if not book_path:
        console.print(
            "[red]Error: Please either:\n"
            "1. Run the command inside a StoryCraftr/PaperCraftr project directory, or\n"
            "2. Specify the project path using --book-path[/red]"
        )
        return None

    try:
        resolved_book_path = str(Path(book_path).resolve())

        # Intentar cargar papercraftr.json primero
        config_path = Path(book_path) / "papercraftr.json"
        if not config_path.exists():
            # Si no existe, intentar storycraftr.json
            config_path = Path(book_path) / "storycraftr.json"
            if not config_path.exists():
                console.print(
                    "[red]Error: No configuration file found. Please either:\n"
                    "1. Run the command inside a StoryCraftr/PaperCraftr project directory, or\n"
                    "2. Specify the project path using --book-path[/red]"
                )
                return None

        config_data = json.loads(config_path.read_text(encoding="utf-8"))

        if not isinstance(config_data, dict):
            raise ValueError("Configuration payload must be a JSON object.")

        return BookConfig.from_mapping(
            book_path=resolved_book_path,
            config_data=config_data,
            model_override=model_override,
        )

    except Exception as e:
        console.print(f"[red]Error loading configuration: {str(e)}[/red]")
        return None


def llm_settings_from_config(
    config: BookConfig, model_override: str | None = None
) -> LLMSettings:
    """
    Map the persisted configuration to normalized LLM settings.
    """

    provider = config.llm_provider
    model = model_override if model_override is not None else config.llm_model
    if model is None:
        model = _default_model_for_provider(provider)

    return LLMSettings(
        provider=provider,
        model=model,
        endpoint=config.llm_endpoint,
        api_key_env=config.llm_api_key_env,
        temperature=config.temperature,
        request_timeout=config.request_timeout,
        max_tokens=config.max_tokens,
    )


def embedding_settings_from_config(config: BookConfig) -> EmbeddingSettings:
    """
    Map the persisted configuration to embedding settings.
    """

    api_provider = (
        config.llm_provider
        if config.llm_provider in {"openai", "openrouter"}
        else "openrouter"
    )

    return EmbeddingSettings(
        model_name=config.embed_model,
        device=config.embed_device,
        cache_dir=config.embed_cache_dir or None,
        api_provider=api_provider,
        api_base=config.llm_endpoint or None,
        api_key_env=config.llm_api_key_env or None,
    )


def file_has_more_than_three_lines(file_path: str) -> bool:
    """
    Check if a file has more than three lines.

    Args:
        file_path (str): The path to the file.

    Returns:
        bool: True if the file has more than three lines, False otherwise.
    """
    try:
        with Path(file_path).open("r", encoding="utf-8") as file:
            # Itera sobre las primeras 4 líneas y devuelve True si hay más de 3 líneas
            for i, _ in enumerate(file, start=1):
                if i > 3:
                    return True
    except FileNotFoundError:
        console.print(f"[red bold]Error:[/red bold] File not found: {file_path}")
        return False
    return False
