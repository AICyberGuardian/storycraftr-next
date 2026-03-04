from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


DEFAULT_INTERNAL_STATE_DIR = ".storycraftr"
DEFAULT_SUBAGENTS_DIR = "subagents"
DEFAULT_SUBAGENT_LOGS_DIR = "logs"
DEFAULT_SESSIONS_DIR = "sessions"
DEFAULT_VECTOR_STORE_DIR = "vector_store"
DEFAULT_VSCODE_EVENTS_FILE = "vscode-events.jsonl"


@dataclass(frozen=True)
class ProjectPaths:
    """Normalized project-relative paths resolved from the project root."""

    root: Path
    internal_state_root: Path
    subagents_root: Path
    subagents_logs_root: Path
    sessions_root: Path
    vector_store_root: Path
    vscode_events_file: Path


def _as_path(value: Optional[str], default: str) -> Path:
    if value is None:
        return Path(default)
    raw = str(value).strip()
    if not raw:
        return Path(default)
    return Path(raw).expanduser()


def _resolve_project_root(book_path: str, config: object | None = None) -> Path:
    runtime_root = Path(book_path).expanduser().resolve()
    if config is None:
        return runtime_root

    config_root_raw = getattr(config, "book_path", None)
    if not config_root_raw:
        return runtime_root

    configured_root = Path(str(config_root_raw)).expanduser()
    if not configured_root.is_absolute():
        return runtime_root

    try:
        return configured_root.resolve()
    except OSError:
        return runtime_root


def _resolve_under_root(root: Path, value: Optional[str], default: str) -> Path:
    candidate = _as_path(value, default)
    if candidate.is_absolute():
        return candidate
    return (root / candidate).resolve()


def resolve_project_paths(book_path: str, config: object | None = None) -> ProjectPaths:
    """
    Resolve project directories from the configured project root.
    """

    root = _resolve_project_root(book_path, config)
    state_root = _resolve_under_root(
        root,
        getattr(config, "internal_state_dir", None) if config else None,
        DEFAULT_INTERNAL_STATE_DIR,
    )

    subagents_root = _resolve_under_root(
        root,
        getattr(config, "subagents_dir", None) if config else None,
        str(state_root / DEFAULT_SUBAGENTS_DIR),
    )
    subagent_logs = _resolve_under_root(
        root,
        getattr(config, "subagent_logs_dir", None) if config else None,
        str(subagents_root / DEFAULT_SUBAGENT_LOGS_DIR),
    )
    sessions_root = _resolve_under_root(
        root,
        getattr(config, "sessions_dir", None) if config else None,
        str(state_root / DEFAULT_SESSIONS_DIR),
    )
    vector_store_root = _resolve_under_root(
        root,
        getattr(config, "vector_store_dir", None) if config else None,
        DEFAULT_VECTOR_STORE_DIR,
    )
    vscode_events_file = _resolve_under_root(
        root,
        getattr(config, "vscode_events_file", None) if config else None,
        str(state_root / DEFAULT_VSCODE_EVENTS_FILE),
    )

    return ProjectPaths(
        root=root,
        internal_state_root=state_root,
        subagents_root=subagents_root,
        subagents_logs_root=subagent_logs,
        sessions_root=sessions_root,
        vector_store_root=vector_store_root,
        vscode_events_file=vscode_events_file,
    )
