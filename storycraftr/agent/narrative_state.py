from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from storycraftr.utils.project_lock import project_write_lock


_DEFAULT_STATE: dict[str, dict[str, dict[str, Any]]] = {
    "characters": {},
    "world": {},
}


@dataclass(frozen=True)
class NarrativeStateSnapshot:
    """Structured narrative state loaded from project storage."""

    characters: dict[str, dict[str, Any]]
    world: dict[str, dict[str, Any]]


class NarrativeStateStore:
    """JSON-backed state store for deterministic character/world constraints."""

    def __init__(self, book_path: str) -> None:
        self.book_path = str(Path(book_path).resolve())
        self._file_path = Path(self.book_path) / "outline" / "narrative_state.json"

    def load(self) -> NarrativeStateSnapshot:
        """Return narrative state snapshot; empty snapshot on missing/invalid data."""

        if not self._file_path.exists():
            return NarrativeStateSnapshot(characters={}, world={})

        try:
            payload = json.loads(self._file_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return NarrativeStateSnapshot(characters={}, world={})

        if not isinstance(payload, dict):
            return NarrativeStateSnapshot(characters={}, world={})

        characters_raw = payload.get("characters")
        world_raw = payload.get("world")
        characters = (
            _normalize_mapping(characters_raw)
            if isinstance(characters_raw, dict)
            else {}
        )
        world = _normalize_mapping(world_raw) if isinstance(world_raw, dict) else {}
        return NarrativeStateSnapshot(characters=characters, world=world)

    def save(self, snapshot: NarrativeStateSnapshot) -> None:
        """Persist one full snapshot under project write lock."""

        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "characters": snapshot.characters,
            "world": snapshot.world,
        }
        with project_write_lock(self.book_path):
            self._file_path.write_text(
                json.dumps(payload, indent=2, sort_keys=True),
                encoding="utf-8",
            )

    def upsert_character(
        self, name: str, fields: dict[str, Any]
    ) -> NarrativeStateSnapshot:
        """Merge one character record and persist updated snapshot."""

        key = " ".join(name.split()).strip()
        if not key:
            return self.load()

        snapshot = self.load()
        merged = dict(snapshot.characters.get(key, {}))
        merged.update(_normalize_fields(fields))
        characters = dict(snapshot.characters)
        characters[key] = merged
        updated = NarrativeStateSnapshot(characters=characters, world=snapshot.world)
        self.save(updated)
        return updated

    def upsert_world(self, key: str, fields: dict[str, Any]) -> NarrativeStateSnapshot:
        """Merge one world record and persist updated snapshot."""

        item_key = " ".join(key.split()).strip()
        if not item_key:
            return self.load()

        snapshot = self.load()
        merged = dict(snapshot.world.get(item_key, {}))
        merged.update(_normalize_fields(fields))
        world = dict(snapshot.world)
        world[item_key] = merged
        updated = NarrativeStateSnapshot(characters=snapshot.characters, world=world)
        self.save(updated)
        return updated

    def render_prompt_block(self, *, max_chars: int = 2400) -> str:
        """Render strict JSON block for prompt injection."""

        snapshot = self.load()
        if not snapshot.characters and not snapshot.world:
            return ""

        payload = {
            "characters": snapshot.characters,
            "world": snapshot.world,
        }
        raw = json.dumps(payload, ensure_ascii=True, sort_keys=True, indent=2)
        if len(raw) <= max_chars:
            return raw
        if max_chars <= 3:
            return raw[:max_chars]
        return raw[: max_chars - 3].rstrip() + "..."


def _normalize_mapping(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    normalized: dict[str, dict[str, Any]] = {}
    for key, value in raw.items():
        if not isinstance(value, dict):
            continue
        cleaned_key = " ".join(str(key).split()).strip()
        if not cleaned_key:
            continue
        normalized[cleaned_key] = _normalize_fields(value)
    return normalized


def _normalize_fields(raw: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in raw.items():
        clean_key = " ".join(str(key).split()).strip()
        if not clean_key:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            cleaned[clean_key] = value
            continue
        if isinstance(value, list):
            cleaned_list = [
                item for item in value if isinstance(item, (str, int, float, bool))
            ]
            cleaned[clean_key] = cleaned_list
            continue
        cleaned[clean_key] = str(value)
    return cleaned
