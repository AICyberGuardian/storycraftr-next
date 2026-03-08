from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_PROMPTS_ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class CraftRuleSet:
    """Static storytelling rule fragments injected into prompt composition."""

    planner: str
    drafter: str
    editor: str


@lru_cache(maxsize=1)
def load_craft_rule_set() -> CraftRuleSet:
    """Load static craft rules from repository prompt fragments.

    The files are deterministic sources of universal storytelling mechanics and
    are intentionally loaded from disk instead of semantic retrieval systems.
    """

    return CraftRuleSet(
        planner=_load_required("planner_rules.md"),
        drafter=_load_required("drafter_rules.md"),
        editor=_load_required("editor_rules.md"),
    )


def _load_required(file_name: str) -> str:
    path = _PROMPTS_ROOT / file_name
    try:
        content = path.read_text(encoding="utf-8").strip()
    except OSError as exc:  # pragma: no cover - fail-closed runtime path
        raise RuntimeError(f"Failed to load craft rules file: {path}") from exc

    if not content:
        raise RuntimeError(f"Craft rules file is empty: {path}")
    return content
