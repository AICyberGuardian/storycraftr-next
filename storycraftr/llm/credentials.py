from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, Mapping, Optional

from rich.console import Console

console = Console()

try:
    import keyring
    from keyring.errors import KeyringError
except ImportError:  # pragma: no cover - exercised through dependency matrix.
    keyring = None
    KeyringError = Exception  # type: ignore[assignment]

_KEY_FILE_MAP: Mapping[str, tuple[str, ...]] = {
    "OPENAI_API_KEY": ("openai_api_key.txt",),
    "OPENROUTER_API_KEY": ("openrouter_api_key.txt",),
    "OLLAMA_API_KEY": ("ollama_api_key.txt",),
}
_KEYRING_USERNAME_MAP: Mapping[str, tuple[str, ...]] = {
    "OPENAI_API_KEY": ("OPENAI_API_KEY", "openai_api_key"),
    "OPENROUTER_API_KEY": ("OPENROUTER_API_KEY", "openrouter_api_key"),
    "OLLAMA_API_KEY": ("OLLAMA_API_KEY", "ollama_api_key"),
}
_DEFAULT_KEYRING_SERVICE = "storycraftr"


def _search_dirs(extra_dirs: Iterable[Path] | None) -> list[Path]:
    home_dir = Path.home()
    search_dirs = [
        home_dir / ".storycraftr",
        home_dir / ".papercraftr",
    ]
    if extra_dirs:
        search_dirs.extend(Path(p) for p in extra_dirs)
    return search_dirs


def _load_from_keyring(env_var: str, service_name: str) -> Optional[str]:
    if keyring is None:
        return None

    usernames = _KEYRING_USERNAME_MAP.get(env_var, (env_var,))
    for username in usernames:
        try:
            value = keyring.get_password(service_name, username)
        except KeyringError as exc:
            console.print(
                f"[yellow]Unable to read {env_var} from OS keyring '{service_name}': {exc}[/yellow]"
            )
            return None
        if value:
            stripped = value.strip()
            if stripped:
                return stripped
    return None


def _load_from_plaintext_files(
    env_var: str, search_dirs: Iterable[Path]
) -> tuple[Optional[str], Optional[Path]]:
    for base_dir in search_dirs:
        for filename in _KEY_FILE_MAP.get(env_var, ()):
            key_path = base_dir / filename
            if not key_path.exists():
                continue
            api_key = key_path.read_text(encoding="utf-8").strip()
            if api_key:
                return api_key, key_path
    return None, None


def store_local_credential(
    env_var: str, api_key: str, service_name: Optional[str] = None
) -> None:
    """
    Securely persist a provider API key into the system keyring.
    """

    if env_var not in _KEYRING_USERNAME_MAP:
        raise ValueError(f"Unsupported credential variable: {env_var}")

    value = (api_key or "").strip()
    if not value:
        raise ValueError("API key value cannot be empty.")

    if keyring is None:
        raise RuntimeError(
            "The 'keyring' package is not installed. Install it to store credentials securely."
        )

    resolved_service = (
        service_name
        or os.getenv("STORYCRAFTR_KEYRING_SERVICE")
        or _DEFAULT_KEYRING_SERVICE
    )
    username = _KEYRING_USERNAME_MAP[env_var][0]
    try:
        keyring.set_password(resolved_service, username, value)
    except KeyringError as exc:
        raise RuntimeError(
            f"Unable to store credential '{env_var}' in keyring service '{resolved_service}'."
        ) from exc

    os.environ[env_var] = value


def load_local_credentials(extra_dirs: Iterable[Path] | None = None) -> None:
    """
    Populate provider API key environment variables from secure local sources.

    Credentials are loaded in this order:
    1. Existing environment variables.
    2. OS keyring entries under service `storycraftr` (override with STORYCRAFTR_KEYRING_SERVICE).
    3. Legacy plaintext files under ~/.storycraftr and ~/.papercraftr (compatibility fallback).

    This preserves backward compatibility while preferring secure storage by default.
    """

    service_name = os.getenv("STORYCRAFTR_KEYRING_SERVICE") or _DEFAULT_KEYRING_SERVICE
    search_dirs = _search_dirs(extra_dirs)

    for env_var in _KEY_FILE_MAP:
        if os.getenv(env_var):
            continue

        keyring_value = _load_from_keyring(env_var, service_name)
        if keyring_value:
            os.environ[env_var] = keyring_value
            console.print(
                f"[green]{env_var} loaded from OS keyring service '{service_name}'[/green]"
            )
            continue

        api_key, key_path = _load_from_plaintext_files(env_var, search_dirs)
        if api_key and key_path:
            os.environ[env_var] = api_key
            console.print(
                "[yellow]"
                f"{env_var} loaded from legacy plaintext file {key_path}. "
                "Store it in the OS keyring to avoid local secret exposure."
                "[/yellow]"
            )
