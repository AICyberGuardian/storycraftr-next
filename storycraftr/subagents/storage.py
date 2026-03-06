from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List

import yaml

from storycraftr.utils.paths import resolve_project_paths
from storycraftr.utils.project_lock import project_write_lock

from .defaults import get_default_roles_for_language
from .models import SubAgentRole

LOGS_DIRNAME = "logs"
logger = logging.getLogger(__name__)


def subagent_root(book_path: str, config: object | None = None) -> Path:
    return resolve_project_paths(book_path, config=config).subagents_root


def ensure_storage_dirs(book_path: str, config: object | None = None) -> Path:
    paths = resolve_project_paths(book_path, config=config)
    root = paths.subagents_root
    root.mkdir(parents=True, exist_ok=True)
    paths.subagents_logs_root.mkdir(parents=True, exist_ok=True)
    return root


def role_file_path(root: Path, slug: str) -> Path:
    return root / f"{slug}.yaml"


def load_roles(book_path: str, config: object | None = None) -> Dict[str, SubAgentRole]:
    root = ensure_storage_dirs(book_path, config=config)
    roles: Dict[str, SubAgentRole] = {}
    for file_path in root.glob("*.yaml"):
        try:
            raw_text = file_path.read_text(encoding="utf-8")
            data = yaml.safe_load(raw_text) or {}
            if not isinstance(data, dict):
                raise ValueError("Role document must be a YAML mapping.")
            slug = str(data.get("slug", file_path.stem)).strip().lower()
            role = SubAgentRole.from_dict(slug, data)
        except Exception as exc:
            logger.warning(
                "Skipping invalid sub-agent role file %s: %s", file_path, exc
            )
            continue

        roles[role.slug] = role
    return roles


def seed_default_roles(
    book_path: str,
    language: str = "en",
    *,
    force: bool = False,
    config: object | None = None,
) -> List[Path]:
    """
    Materialise the default role YAML files for the project.

    Args:
        book_path: Path to the project root.
        language: Preferred language for prompts; falls back to English.
        force: Overwrite existing files when True.
    Returns:
        A list of file paths that were created or updated.
    """
    root = ensure_storage_dirs(book_path, config=config)
    roles = get_default_roles_for_language(language)
    written: List[Path] = []

    with project_write_lock(book_path, config=config):
        for role in roles:
            file_path = role_file_path(root, role.slug)
            if file_path.exists() and not force:
                continue
            file_path.write_text(
                yaml.safe_dump(role.to_dict(), sort_keys=False), encoding="utf-8"
            )
            written.append(file_path)

    return written
