from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, Mapping, Optional

from rich.console import Console

console = Console()

try:
    import keyring
    from keyring.errors import KeyringError, NoKeyringError
except ImportError:  # pragma: no cover - exercised through dependency matrix.
    keyring = None
    KeyringError = Exception  # type: ignore[assignment]
    NoKeyringError = Exception  # type: ignore[assignment]

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
_KEYRING_BACKEND_AVAILABLE: Optional[bool] = None
_KEYRING_BACKEND_WARNING_SHOWN = False


def _search_dirs(extra_dirs: Iterable[Path] | None) -> list[Path]:
    home_dir = Path.home()
    search_dirs = [
        home_dir / ".storycraftr",
        home_dir / ".papercraftr",
    ]
    if extra_dirs:
        search_dirs.extend(Path(p) for p in extra_dirs)
    return search_dirs


def _legacy_key_path(env_var: str) -> Path:
    filenames = _KEY_FILE_MAP.get(env_var, ())
    if not filenames:
        raise ValueError(f"Unsupported credential variable: {env_var}")
    return Path.home() / ".storycraftr" / filenames[0]


def _persist_legacy_credential(env_var: str, value: str) -> Path:
    key_path = _legacy_key_path(env_var)
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_text(value, encoding="utf-8")
    try:
        key_path.chmod(0o600)
    except OSError:
        # Best effort: chmod can fail on some platforms/filesystems.
        pass
    return key_path


def _warn_keyring_backend_unavailable(_service_name: str, _exc: Exception) -> None:
    global _KEYRING_BACKEND_WARNING_SHOWN
    if _KEYRING_BACKEND_WARNING_SHOWN:
        return
    console.print(
        "[yellow]"
        "OS keyring backend unavailable. Falling back to environment variables and legacy credential files."
        "[/yellow]"
    )
    _KEYRING_BACKEND_WARNING_SHOWN = True


def _load_from_keyring(env_var: str, service_name: str) -> Optional[str]:
    global _KEYRING_BACKEND_AVAILABLE

    if keyring is None:
        return None
    if _KEYRING_BACKEND_AVAILABLE is False:
        return None

    usernames = _KEYRING_USERNAME_MAP.get(env_var, (env_var,))
    for username in usernames:
        try:
            value = keyring.get_password(service_name, username)
            _KEYRING_BACKEND_AVAILABLE = True
        except NoKeyringError as exc:
            _KEYRING_BACKEND_AVAILABLE = False
            _warn_keyring_backend_unavailable(service_name, exc)
            return None
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
    Persist a provider API key into the OS keyring when available.

    Falls back to the legacy plaintext path when the keyring package or backend
    is unavailable.
    """

    if env_var not in _KEYRING_USERNAME_MAP:
        raise ValueError(f"Unsupported credential variable: {env_var}")

    value = (api_key or "").strip()
    if not value:
        raise ValueError("API key value cannot be empty.")

    resolved_service = (
        service_name
        or os.getenv("STORYCRAFTR_KEYRING_SERVICE")
        or _DEFAULT_KEYRING_SERVICE
    )
    username = _KEYRING_USERNAME_MAP[env_var][0]

    if keyring is None:
        key_path = _persist_legacy_credential(env_var, value)
        console.print(
            "[yellow]"
            f"The 'keyring' package is not installed. Stored {env_var} in legacy file {key_path}. "
            "Install keyring + an OS backend for secure storage."
            "[/yellow]"
        )
    else:
        global _KEYRING_BACKEND_AVAILABLE
        try:
            keyring.set_password(resolved_service, username, value)
            _KEYRING_BACKEND_AVAILABLE = True
        except NoKeyringError as exc:
            _KEYRING_BACKEND_AVAILABLE = False
            _warn_keyring_backend_unavailable(resolved_service, exc)
            key_path = _persist_legacy_credential(env_var, value)
            console.print(
                "[yellow]"
                f"Stored {env_var} in legacy file {key_path} because no OS keyring backend is available."
                "[/yellow]"
            )
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


def credential_lookup_details(
    env_var: str, extra_dirs: Iterable[Path] | None = None
) -> dict:
    """
    Describe the local credential lookup chain for one environment variable.
    """

    service_name = os.getenv("STORYCRAFTR_KEYRING_SERVICE") or _DEFAULT_KEYRING_SERVICE
    keyring_usernames = list(_KEYRING_USERNAME_MAP.get(env_var, (env_var,)))
    legacy_files = []
    for base_dir in _search_dirs(extra_dirs):
        for filename in _KEY_FILE_MAP.get(env_var, ()):
            legacy_files.append(str(base_dir / filename))

    return {
        "env_var": env_var,
        "keyring_service": service_name,
        "keyring_usernames": keyring_usernames,
        "legacy_files": legacy_files,
    }
