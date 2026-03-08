from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_PROMPTS_ROOT = Path(__file__).resolve().parent
_CHARS_PER_TOKEN_ESTIMATE = 4


@dataclass(frozen=True)
class CraftRuleFragment:
    """One static craft rule fragment with budget metadata."""

    text: str
    role: str
    priority: int
    max_tokens: int
    source_file: str


@dataclass(frozen=True)
class CraftRuleSet:
    """Static storytelling rule fragments injected into prompt composition."""

    planner: CraftRuleFragment
    drafter: CraftRuleFragment
    editor: CraftRuleFragment
    stitcher: CraftRuleFragment


@lru_cache(maxsize=1)
def load_craft_rule_set() -> CraftRuleSet:
    """Load static craft rules from repository prompt fragments.

    The files are deterministic sources of universal storytelling mechanics and
    are intentionally loaded from disk instead of semantic retrieval systems.
    """

    return CraftRuleSet(
        planner=_load_required("planner_rules.md", default_role="planner"),
        drafter=_load_required("drafter_rules.md", default_role="drafter"),
        editor=_load_required("editor_rules.md", default_role="editor"),
        stitcher=_load_required("stitcher_rules.md", default_role="stitcher"),
    )


def trim_fragment_to_budget(text: str, max_tokens: int) -> str:
    """Trim a rule fragment to its configured token budget."""
    budget = max(1, max_tokens)
    max_chars = budget * _CHARS_PER_TOKEN_ESTIMATE
    if len(text) <= max_chars:
        return text
    if max_chars <= 3:
        return text[:max_chars]
    return text[: max_chars - 3].rstrip() + "..."


def _load_required(file_name: str, *, default_role: str) -> CraftRuleFragment:
    path = _PROMPTS_ROOT / file_name
    try:
        raw_content = path.read_text(encoding="utf-8")
    except OSError as exc:  # pragma: no cover - fail-closed runtime path
        raise RuntimeError(f"Failed to load craft rules file: {path}") from exc

    metadata, content = _split_frontmatter(raw_content, source_path=path)

    if not content.strip():
        raise RuntimeError(f"Craft rules file is empty: {path}")

    role = str(metadata.get("role", default_role)).strip() or default_role
    priority = _as_int(metadata.get("priority"), default=5)
    max_tokens = _as_int(metadata.get("max_tokens"), default=320)
    return CraftRuleFragment(
        text=content.strip(),
        role=role,
        priority=max(1, priority),
        max_tokens=max(1, max_tokens),
        source_file=file_name,
    )


def _split_frontmatter(
    raw_content: str, *, source_path: Path
) -> tuple[dict[str, Any], str]:
    stripped = raw_content.lstrip()
    if not stripped.startswith("---\n"):
        return {}, raw_content

    lines = stripped.splitlines()
    if not lines:
        return {}, raw_content

    end_index = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end_index = idx
            break

    if end_index is None:
        raise RuntimeError(
            f"Unterminated frontmatter in craft rules file: {source_path}"
        )

    frontmatter_text = "\n".join(lines[1:end_index])
    body = "\n".join(lines[end_index + 1 :]).strip()
    try:
        parsed = yaml.safe_load(frontmatter_text) if frontmatter_text.strip() else {}
    except yaml.YAMLError as exc:
        raise RuntimeError(
            f"Invalid frontmatter in craft rules file: {source_path}"
        ) from exc

    if parsed is None:
        parsed = {}
    if not isinstance(parsed, dict):
        raise RuntimeError(
            f"Frontmatter must be a mapping in craft rules file: {source_path}"
        )
    return parsed, body


def _as_int(value: Any, *, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default
